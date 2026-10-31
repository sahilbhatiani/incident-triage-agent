# Chaos Arena: Multi-Agent Incident Triage

**Question.** When a production alert fires, does a coordinator plus three specialist agents (Logs, Metrics, Knowledge) diagnose the root cause more accurately or more cheaply than one agent holding the same tools?

**Answer (measured, see [Results](#results) and the full [Results and Observations report](REPORT.md)).** No. On 90 runs over 15 simulated incidents, the **single agent was more accurate (36/45, 80%) than the coordinator + specialists (28/45, 62%)**, with better calibration, at about 20% higher cost. The multi-agent team localised the failing service almost as well (93% vs 100%) but lost the fault *mechanism* at the handoff. We therefore choose **Approach A (single agent)**, and document below where B fails and what would fix it.

Scope: read-only triage of simulated backend incidents. There is no remediation and no real infrastructure.

## Why a simulator

Hand-labelled incidents are slow to make and easy to get wrong. Here a deterministic fault-injection simulator *creates* each incident from a `ChaosSpec` (fault, service, onset, severity, red herrings, seed). The label is a fact about what was injected, sealed in `label.json`, and the agents never see it. Rendering the same spec and seed again gives byte-identical files.

- 6 services: `gateway → orders → {payments, inventory, redis}`, `{payments, inventory} → postgres`
- 5 faults: `bad_deploy`, `db_pool_saturation`, `downstream_timeout`, `memory_leak`, `cache_stampede`
- Symptoms propagate **upstream** with 30–90 s lag and 0.65× damping per hop, so the alerting gateway is the loudest signal but never the cause
- Red herrings: cron CPU spikes, unrelated deploys, config warnings, GC pauses, disk warnings

## Architecture

```
ChaosSpec ─▶ Chaos Engine ─▶ incident (alert, logs, metrics │ sealed label)
kb/*.md ─▶ chunk + tag ─▶ BM25 + Chroma ─▶ RRF (k=60)
                │
        read-only tool layer (query_logs, get_metric, list_anomalies, search_kb, get_topology)
          │                                   │
   A: single ReAct agent           B: Logs ∥ Metrics ∥ Knowledge ─▶ Coordinator (≤1 follow-up)
          └──────────────┬────────────────────┘
                     Diagnosis (Pydantic) ─▶ citation verifier ─▶ LLM judge ─▶ scorer ─▶ report
                                                                       │
                                          Red-team Chaos Agent ◀── failures ─▶ new ChaosSpecs
```

Full system design with diagrams: [Chaos Arena System Design](https://claude.ai/artifact/9rGFmFqJocsdWsEssEyrNW).

| Component | Path | Notes |
|---|---|---|
| Chaos Engine | `sim/` | world model, fault library, propagation, renderer |
| Knowledge base | `kb/` | 6 runbooks + 8 postmortems written for this project (no real company data), 38 chunks |
| Hybrid retrieval | `triage/rag.py` | heading-aware chunking (≤400 tokens), BM25 + `text-embedding-3-small` in Chroma, RRF |
| Tools | `triage/tools.py` | read-only, size-capped, traced; never read the label |
| Approach A | `triage/single.py` | one ReAct agent, all 5 tools, 15 tool calls |
| Approach B | `triage/multi.py` | 3 specialists in parallel via LangGraph `Send` (4 calls each) + coordinator with no data tools + ≤1 follow-up (≤3 calls) = 15 |
| Shared loop | `triage/loop.py` | budgeted ReAct subgraph; answers are `submit_*` tool calls |
| Evaluation | `eval/` | verifier, LLM judge, cached matrix runner, ablation, report |
| Red team | `chaos/red_team.py` | LLM proposes `ChaosSpec`s from past failures; the simulator renders them |
| UI | `app/streamlit_app.py` | War Room (live lanes), Arena (leaderboard), Explorer |

### Fairness controls
Both approaches use the same incidents, model (`gpt-4.1-mini`, temperature 0), tool implementations, retrieval index, `Diagnosis` schema, taxonomy prompt and **total tool budget of 15**. Only the orchestration differs.

## Framework choices

| Choice | Why |
|---|---|
| LangGraph | Explicit graphs make both orchestrations inspectable. `Send` gives real parallel fan-out, typed state makes handoffs measurable, and the same ReAct subgraph is reused by every agent so the baseline is fair. |
| OpenAI `gpt-4.1-mini` (agents), `gpt-4.1` (judge, red team) | Reliable tool calling at low cost for 100+ runs. A stronger, different-sized model judges. |
| Pydantic v2 | Every agent output is validated. Out-of-taxonomy answers are coerced to `unknown`, never silently accepted. |
| BM25 + Chroma + RRF | Exact error strings (`OOMKilled`, `pool 100/100`) need lexical match, paraphrased symptoms need vectors, and RRF fuses the two without score calibration. |
| pytest-bdd | 52 Gherkin scenarios were written and reviewed before implementation. A scripted fake chat model keeps the agent tests deterministic and free. |
| Streamlit | The fastest path to a live demo in Python. |

## Evaluation method

- **Primary:** root-cause accuracy as an exact `(fault, service)` match against the sealed label, reported as n/N.
- **Evidence:** a deterministic citation verifier. Log ids must exist, metric windows must overlap a detected anomaly, and doc chunk ids must exist.
- **LLM-as-judge** (`gpt-4.1`): root-cause match (correct/partial/incorrect), evidence support (1–5, judged only on verified evidence), and whether the next steps are safe.
- **Efficiency:** tokens, estimated $ per run, wall-clock latency, tool calls.
- **Calibration:** expected calibration error, plus a **smoking-gun ablation** that deletes every key-evidence log line and re-runs.
- **Adversarial split:** incidents designed by the red-team agent from the baseline's failures.
- Standard split: 15 incidents (5 faults × 3 difficulty variants) × 2 approaches × 3 seeds = 90 runs.

## Results

All numbers come from `results/results.csv` (standard split), `results/adversarial.csv` and `results/ablation_summary.csv`, produced by the commands under [Running it](#running-it). Models: `gpt-4.1-mini` agents, `gpt-4.1` judge. Costs are estimates from token counts.

### Standard split: 15 incidents × 3 seeds

| Metric | A: Single agent | B: Coordinator + specialists |
|---|---|---|
| **Root-cause accuracy (fault + service)** | **36/45 (80.0%)** | 28/45 (62.2%) |
| Correct service only | 45/45 (100%) | 42/45 (93.3%) |
| Correct fault type only | 36/45 (80.0%) | 28/45 (62.2%) |
| Valid-citation rate (deterministic) | 0.952 | 0.959 |
| Judge: correct or partial | 100% | 97.8% |
| Judge: evidence support (1–5) | 4.82 | 4.40 |
| Judge: next steps safe | 86.7% | 77.8% |
| Calibration error (ECE, lower is better) | **0.14** | 0.33 |
| Mean confidence | 0.94 | 0.95 |
| Tool calls / LLM calls per run | 13.8 / 6.6 | 13.0 / 10.2 |
| Tokens per run (in + out) | 20,666 | 13,976 |
| Est. cost per run | $0.0094 | **$0.0077** |
| p50 latency | 10.6 s | **8.4 s** |

Accuracy by fault type (correct runs out of 9 per approach):

| Fault | Single | Multi |
|---|---|---|
| bad_deploy | 9 | 7 |
| db_pool_saturation | 7 | 4 |
| downstream_timeout | 9 | 8 |
| memory_leak | 7 | 9 |
| cache_stampede | 4 | **0** |

### Adversarial split (red-team designed)

The red-team agent (`gpt-4.1`) read the standard-split failures and designed 6 incidents: low severity (0.13–0.19), late onset (minutes 29–44), and one red herring each. Labels come from the simulator. The accepted and rejected designs are in `data/incidents/adversarial/_red_team_log.json`.

| Metric | A: Single agent | B: Coordinator + specialists |
|---|---|---|
| **Root-cause accuracy** | **18/18 (100%)** | 13/18 (72.2%) |
| Valid-citation rate | 0.967 | 0.881 |
| Judge: evidence support (1–5) | 5.00 | 4.28 |
| Judge: next steps safe | 94.4% | 88.9% |
| ECE | 0.05 | 0.22 |
| Est. cost per run / p50 latency | $0.0093 / 11.4 s | $0.0071 / 7.7 s |

The red team did **not** make incidents harder for A. Lowering severity still leaves the deploy and pool-exhaustion log lines intact, and A reads them directly. It did reproduce B's weakness: both of B's failing incidents (adv-01, adv-02) are subtle `bad_deploy`s that B labelled `downstream_timeout`, the same mechanism-loss pattern as on the standard split. A stronger red team would need simulator support for log-level deception (for example, misleading error text), which the current fault library does not have.

### Smoking-gun ablation: key evidence logs deleted (5 incidents, seed 0)

| | Accuracy full → ablated | Confidence full → ablated | Answered `unknown` |
|---|---|---|---|
| Single | 100% → 40% | 0.94 → 0.93 | 0% |
| Multi | 60% → 40% | 0.96 → 0.90 | 20% |

Both approaches lose accuracy without the decisive logs, but **neither lowers its confidence meaningfully**: the single agent stays at 0.93 while being right 40% of the time. Only the multi-agent coordinator ever abstains.

### Decision

**Approach A, the single agent.** It is 18 points more accurate on the standard split, better calibrated, and gives better-supported evidence. Approach B's advantages are real but smaller: it is 18% cheaper, 2 s faster, and more willing to say `unknown`. Under an equal tool budget, splitting the investigation across specialists spreads 15 calls thinly (4 each) and filters raw evidence through summaries. In this domain the fault type is often decided by a single log line on one service, so that filtering is what costs accuracy.

## Failure analysis: attempts, failures and pivots

### What failed, and why

1. **Multi-agent: mechanism lost at the handoff (the main finding).** B found the right service in 93% of runs but the right fault in only 62%. 16 of its 17 wrong answers were "downstream_timeout", the most generic label. In `std-05a` (cache stampede), the Logs specialist spent its 4 calls on topology and the *callers'* `502` errors, never queried redis's own logs, and so never saw `cache miss storm: hit ratio dropped to 11%`. The Knowledge specialist listed 4 hypotheses in its 5 findings and left out cache stampede. The coordinator received correct timing ("redis errors first") with no mechanism and defaulted to timeout. Cache stampede: **0/9** for B.
2. **Overconfidence everywhere.** Mean confidence when wrong was 0.92 (A) and 0.94 (B). The ablation confirms that confidence barely moves when the decisive evidence is removed.
3. **Unsafe next steps.** The judge failed 6 (A) and 10 (B) runs for recommending actions such as restarting services or rolling back without operator approval, despite the read-only instruction.
4. **Shared confusion: db pool saturation vs timeout.** Both approaches sometimes read the postgres latency spike as a slow dependency. They ignored `db_pool_used` at 100%, even though it is listed in the runbook.

### Attempts and pivots during the build

| # | Attempt | What went wrong | Pivot |
|---|---|---|---|
| 1 | Budget of 6 tool calls per specialist | Gave B up to 19 calls against A's 15, an unfair comparison (caught in BDD review) | 4 per specialist + 3 for one follow-up = 15, enforced and tested |
| 2 | Memory leak propagated from leak onset | Callers degraded before memory was even high, which is unrealistic | Propagation starts at the first OOM kill |
| 3 | Knowledge specialist given a "symptom summary" | Computing it would give B free data access outside the budget | Knowledge sees only the alert and acts as a hypothesis generator |
| 4 | Coordinator could cite anything | It has no data, so any new citation would be invented | Its citations are filtered to the specialists' handoffs, and drops are traced (none occurred in the standard run) |
| 5 | Parallel eval workers | Concurrent Chroma client creation crashed every run (`Could not connect to tenant default_tenant`) | Lock around retriever creation and queries |
| 6 | Full run | 1/90 runs died with an OpenAI 400: a malformed tool call had no reply message | The loop now answers `invalid_tool_calls` too, and the run was re-executed from cache |
| 7 | Red team, attempt 1 | 6/6 proposals rejected: untyped `red_herrings` let the model invent fields (`minute`) | Typed herring schema (`results/red_team_attempt1_log.json`) |
| 8 | Red team, attempt 2 | 6/6 rejected again: it asked for a "downstream_timeout" red herring, which the simulator does not have. It was trying to mimic the agents' favourite wrong answer | One revision round with the validation errors fed back. The specs are still validated and never patched (`results/red_team_attempt2_log.json`) |
| 9 | pytest-bdd on pytest 9 | Internal API error | Pinned `pytest<9` |

### What would fix B next
- Give the Logs specialist an explicit "query the earliest-anomalous service's own logs" step, or route the Metrics specialist's earliest anomaly to Logs before it starts (a sequential handoff instead of pure fan-out).
- Require findings to quote the mechanism-defining log line verbatim instead of a paraphrase.
- Give the Knowledge specialist all 5 fault types by construction (one finding each), rather than letting it choose.
- Add a calibration step: lower confidence when no log line directly names the mechanism.

## Running it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                                   # add OPENAI_API_KEY
.venv/bin/pytest                                       # 50 offline scenarios (+2 live with a key)
.venv/bin/python -m sim.render                         # re-render the standard split
.venv/bin/python -m triage.run data/incidents/standard/std-02c multi
.venv/bin/python -m eval.run --seeds 0,1,2             # full comparison, cached in .cache/eval
.venv/bin/python -m chaos.red_team --n 6               # adversarial split from failures
.venv/bin/python -m eval.run --splits adversarial --seeds 0,1,2 --out results/adversarial.csv
.venv/bin/python -m eval.ablation                      # smoking-gun ablation
.venv/bin/python -m eval.report                        # summary tables and charts
.venv/bin/streamlit run app/streamlit_app.py           # War Room
```
