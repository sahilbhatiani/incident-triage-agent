"""Aggregate results.csv into tables and charts under results/."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px

from eval.score import expected_calibration_error


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, approach), g in df.groupby(["split", "approach"]):
        n, k = len(g), int(g["correct"].astype(bool).sum())
        judged = g["judge_match"].dropna() if "judge_match" in g else pd.Series(dtype=object)
        rows.append({
            "split": split, "approach": approach,
            "accuracy": f"{k}/{n}", "accuracy_pct": round(100 * k / n, 1) if n else 0.0,
            "citation_rate": round(g["citation_rate"].mean(), 3),
            "judge_correct_or_partial_pct": round(100 * judged.isin(["correct", "partial"]).mean(), 1) if len(judged) else None,
            "judge_support": round(pd.to_numeric(g.get("judge_support"), errors="coerce").mean(), 2) if "judge_support" in g else None,
            "safe_steps_pct": round(100 * g["judge_safe"].dropna().astype(bool).mean(), 1) if "judge_safe" in g and g["judge_safe"].notna().any() else None,
            "cost_usd_mean": round(g["cost_usd"].mean(), 4),
            "latency_p50_s": round(g["latency_s"].median(), 1),
            "tokens_mean": int((g["tokens_in"] + g["tokens_out"]).mean()),
            "tool_calls_mean": round(g["tool_calls"].mean(), 1),
            "ece": expected_calibration_error(g["confidence"], g["correct"].astype(bool)),
            "mean_confidence": round(g["confidence"].mean(), 2),
        })
    return pd.DataFrame(rows)


def build_report(results_csv, out_dir) -> pd.DataFrame:
    df = pd.read_csv(results_csv)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(df)
    summary.to_csv(out / "summary.csv", index=False)
    (out / "summary.md").write_text(summary.to_markdown(index=False))

    per_fault = df.groupby(["split", "approach", "fault_true"])["correct"].mean().reset_index()
    px.bar(per_fault, x="fault_true", y="correct", color="approach", barmode="group", facet_col="split",
           title="Root-cause accuracy by fault type").write_html(out / "accuracy_by_fault.html")
    px.scatter(df, x="cost_usd", y="latency_s", color="approach", symbol="correct",
               title="Cost vs latency per run").write_html(out / "cost_latency.html")
    return summary


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "results/results.csv"
    print(build_report(src, "results").to_string(index=False))
