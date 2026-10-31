"""Smoking-gun ablation: delete every key evidence log line and re-run both approaches.

A well-calibrated system should lower its confidence or answer "unknown" when the decisive logs are gone.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from eval.judge import judge_model
from eval.run import run_matrix
from eval.score import ablate_key_evidence


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", default="std-01b,std-02b,std-03b,std-04b,std-05b")
    ap.add_argument("--out", default="results/ablation.csv")
    args = ap.parse_args()
    src = [Path("data/incidents/standard", i) for i in args.incidents.split(",")]
    ablated = [ablate_key_evidence(d, Path("data/incidents/ablated")) for d in src]
    df = run_matrix(ablated, ["single", "multi"], [0], ".cache/eval", judge_llm=judge_model(), workers=6, out_csv=args.out)
    base = pd.read_csv("results/results.csv")
    base = base[(base["incident"].isin([d.name for d in src])) & (base["seed"] == 0)]
    df["incident_base"] = df["incident"].str.replace("-ablated", "")
    merged = df.merge(base, left_on=["incident_base", "approach"], right_on=["incident", "approach"], suffixes=("_ablated", "_full"))
    table = merged.groupby("approach").agg(
        accuracy_full=("correct_full", "mean"), accuracy_ablated=("correct_ablated", "mean"),
        confidence_full=("confidence_full", "mean"), confidence_ablated=("confidence_ablated", "mean"),
        unknown_ablated=("fault_pred_ablated", lambda s: (s == "unknown").mean())).round(2)
    table.to_csv("results/ablation_summary.csv")
    print(table.to_string())


if __name__ == "__main__":
    main()
