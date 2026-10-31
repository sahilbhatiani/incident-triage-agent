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


COLORS = {"single": "#2a6fdb", "multi": "#e8833a"}


def grouped_bars_svg(title: str, groups: list[str], series: dict[str, list[float]], labels: dict[str, list[str]],
                     ymax: float = 100, unit: str = "%") -> str:
    """Dependency-free grouped bar chart as SVG, so it renders inline on GitHub."""
    w, h, left, top, bottom = 760, 340, 50, 50, 60
    plot_w, plot_h = w - left - 20, h - top - bottom
    slot = plot_w / len(groups)
    bar = slot * 0.8 / len(series)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Helvetica,Arial,sans-serif" font-size="12">',
             f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
             f'<text x="{left}" y="24" font-size="15" font-weight="bold" fill="#222">{title}</text>']
    for tick in range(0, 101, 25):
        y = top + plot_h * (1 - tick / 100)
        parts.append(f'<line x1="{left}" x2="{w - 20}" y1="{y}" y2="{y}" stroke="#e5e5e5"/>'
                     f'<text x="{left - 6}" y="{y + 4}" text-anchor="end" fill="#666">{tick * ymax / 100:g}{unit}</text>')
    for i, g in enumerate(groups):
        x0 = left + i * slot + slot * 0.1
        for j, (name, vals) in enumerate(series.items()):
            bh = plot_h * vals[i] / ymax
            x, y = x0 + j * bar, top + plot_h - bh
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar - 3:.1f}" height="{bh:.1f}" fill="{COLORS.get(name, "#888")}"/>'
                         f'<text x="{x + (bar - 3) / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" fill="#333">{labels[name][i]}</text>')
        parts.append(f'<text x="{left + i * slot + slot / 2:.1f}" y="{top + plot_h + 18}" text-anchor="middle" fill="#333">{g}</text>')
    for j, name in enumerate(series):
        x = left + j * 130
        parts.append(f'<rect x="{x}" y="{h - 22}" width="12" height="12" fill="{COLORS.get(name, "#888")}"/>'
                     f'<text x="{x + 18}" y="{h - 12}" fill="#333">{name}</text>')
    return "\n".join(parts + ["</svg>"])


def write_svgs(results_csv, adversarial_csv, ablation_csv, out_dir) -> None:
    out = Path(out_dir)
    std = pd.read_csv(results_csv)
    faults = sorted(std["fault_true"].unique())
    acc = std.groupby(["approach", "fault_true"])["correct"].agg(["sum", "count"])
    series = {a: [100 * acc.loc[(a, f), "sum"] / acc.loc[(a, f), "count"] for f in faults] for a in ("single", "multi")}
    labels = {a: [f'{acc.loc[(a, f), "sum"]}/{acc.loc[(a, f), "count"]}' for f in faults] for a in ("single", "multi")}
    (out / "accuracy_by_fault.svg").write_text(
        grouped_bars_svg("Root-cause accuracy by fault type (standard split)", faults, series, labels))

    adv = pd.read_csv(adversarial_csv)
    abl = pd.read_csv(ablation_csv).set_index("approach")
    groups = ["standard", "adversarial", "ablation: full", "ablation: evidence removed"]
    series, labels = {}, {}
    for a in ("single", "multi"):
        s, v = std[std.approach == a]["correct"], adv[adv.approach == a]["correct"]
        series[a] = [100 * s.mean(), 100 * v.mean(), 100 * abl.loc[a, "accuracy_full"], 100 * abl.loc[a, "accuracy_ablated"]]
        labels[a] = [f"{s.sum()}/{len(s)}", f"{v.sum()}/{len(v)}",
                     f'{abl.loc[a, "accuracy_full"]:.0%}', f'{abl.loc[a, "accuracy_ablated"]:.0%}']
    (out / "accuracy_by_split.svg").write_text(grouped_bars_svg("Root-cause accuracy by split", groups, series, labels))


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
    if Path("results/adversarial.csv").exists() and Path("results/ablation_summary.csv").exists():
        write_svgs(src, "results/adversarial.csv", "results/ablation_summary.csv", "results")
