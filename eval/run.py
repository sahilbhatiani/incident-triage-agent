"""Replay incidents x approaches x seeds, caching each result on disk."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from eval.judge import judge, judge_model
from eval.score import is_correct
from eval.verify import verify_citations
from triage.schemas import Diagnosis, Label

RESULT_COLUMNS = ["incident", "split", "approach", "seed", "fault_true", "service_true", "fault_pred", "service_pred",
                  "correct", "confidence", "citation_rate", "n_citations", "tokens_in", "tokens_out", "cost_usd",
                  "latency_s", "tool_calls", "llm_calls", "log_ids_seen", "log_ids_handed_off",
                  "judge_match", "judge_support", "judge_safe"]


def default_agent_fn(incident_dir, approach, seed):
    from triage.run import make_llm, triage_incident

    out = triage_incident(incident_dir, approach, llm=make_llm(seed=seed), trace_dir="traces")
    return {"diagnosis": out["diagnosis"], "usage": out["usage"]}


def _kb_chunks():
    from triage.rag import load_and_chunk

    return {c["chunk_id"]: c["text"] for c in load_and_chunk("kb")}


def evaluate_one(incident_dir, approach, seed, agent_fn, kb_chunks, judge_llm=None) -> dict:
    d = Path(incident_dir)
    label = Label.model_validate_json((d / "label.json").read_text())
    out = agent_fn(d, approach, seed)
    diag: Diagnosis = out["diagnosis"]
    ver = verify_citations(diag, d, kb_chunks)
    row = {
        "incident": d.name, "split": d.parent.name, "approach": approach, "seed": seed,
        "fault_true": label.fault, "service_true": label.service,
        "fault_pred": diag.fault, "service_pred": diag.service,
        "correct": is_correct(diag, label), "confidence": diag.confidence,
        "citation_rate": ver["rate"], "n_citations": ver["total"],
        **{k: out["usage"].get(k, 0) for k in ("tokens_in", "tokens_out", "cost_usd", "latency_s", "tool_calls",
                                               "llm_calls", "log_ids_seen", "log_ids_handed_off")},
        "judge_match": None, "judge_support": None, "judge_safe": None,
        "explanation": diag.explanation, "citations": json.dumps([c.model_dump() for c in diag.citations]),
        "invalid_citations": json.dumps([x for x in ver["details"] if not x["valid"]]),
    }
    if judge_llm is not None:
        v = judge(judge_llm, diag, label, ver["evidence_text"])
        row.update(judge_match=v.root_cause_match, judge_support=v.evidence_support, judge_safe=v.next_steps_safe,
                   judge_rationale=v.rationale)
    return row


def run_matrix(incident_dirs, approaches, seeds, cache_dir, agent_fn=None, judge_llm=None, kb_chunks=None,
               workers: int = 4, out_csv=None) -> pd.DataFrame:
    """Evaluate every (incident, approach, seed); cached cells are read back instead of re-run."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    agent_fn = agent_fn or default_agent_fn
    kb_chunks = kb_chunks if kb_chunks is not None else _kb_chunks()
    rows, todo = [], []
    for d in map(Path, incident_dirs):
        for a in approaches:
            for s in seeds:
                f = cache / f"{d.parent.name}__{d.name}__{a}__{s}.json"
                if f.exists():
                    rows.append(json.loads(f.read_text()))
                else:
                    todo.append((d, a, s, f))

    def work(item):
        d, a, s, f = item
        row = evaluate_one(d, a, s, agent_fn, kb_chunks, judge_llm)
        f.write_text(json.dumps(row, default=str))
        return row

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, t) for t in todo]
        for fut in as_completed(futures):
            try:
                rows.append(fut.result())
            except Exception as e:  # one failed run must not lose the rest
                print(f"run failed: {e}")
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["split", "incident", "approach", "seed"]).reset_index(drop=True)
    if out_csv:
        Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_csv, index=False)
    return df


def main():
    p = argparse.ArgumentParser(description="Run the comparative evaluation")
    p.add_argument("--splits", default="standard")
    p.add_argument("--approaches", default="single,multi")
    p.add_argument("--seeds", default="0,1,2")
    p.add_argument("--n", type=int, default=0, help="limit incidents per split (0 = all)")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", default="results/results.csv")
    args = p.parse_args()

    dirs = []
    for split in args.splits.split(","):
        ds = sorted(x for x in Path("data/incidents", split).iterdir() if (x / "label.json").exists())
        dirs += ds[: args.n] if args.n else ds
    df = run_matrix(dirs, args.approaches.split(","), [int(s) for s in args.seeds.split(",")], ".cache/eval",
                    judge_llm=None if args.no_judge else judge_model(), workers=args.workers, out_csv=args.out)
    print(df.groupby(["split", "approach"])["correct"].agg(["sum", "count"]))


if __name__ == "__main__":
    main()
