# incident-triage-agent — Chaos Arena

Does a coordinator plus three specialist agents (Logs, Metrics, Knowledge) diagnose production incidents better than a single agent holding the same tools? Incidents come from a deterministic fault-injection simulator, so ground truth holds by construction.

## Setup
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # add OPENAI_API_KEY
.venv/bin/pytest
```

## Layout
| Path | Component |
|---|---|
| `sim/` | Chaos Engine: world model, faults, propagation, renderer |
| `kb/` | Runbooks and postmortems indexed for RAG |
| `triage/` | Schemas, read-only tools, hybrid RAG, single/multi-agent graphs, tracer |
| `chaos/` | Red-team Chaos Agent |
| `eval/` | Runner, citation verifier, LLM judge, scorer, report |
| `app/` | Streamlit War Room |
| `tests/` | BDD feature files and step definitions |
