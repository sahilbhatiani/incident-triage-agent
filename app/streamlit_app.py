"""Chaos Arena: War Room (live triage), Arena (results) and Incident Explorer."""

from __future__ import annotations

import json
import queue
import random
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.render import render  # noqa: E402
from sim.world import EDGES, METRICS, SERVICES  # noqa: E402
from triage.anomaly import anomalies  # noqa: E402
from triage.schemas import FAULTS, ChaosSpec, RedHerring  # noqa: E402

DATA = ROOT / "data" / "incidents"
RESULTS = ROOT / "results" / "results.csv"
FAULT_SERVICES = {
    "bad_deploy": ["orders", "payments", "inventory"],
    "db_pool_saturation": ["postgres"],
    "downstream_timeout": ["payments", "inventory"],
    "memory_leak": ["orders", "payments", "inventory"],
    "cache_stampede": ["redis"],
}
LANES = {"single": ["single"], "multi": ["logs", "metrics", "knowledge", "coordinator"]}

st.set_page_config(page_title="Chaos Arena", page_icon="🔥", layout="wide")


# --- helpers ---------------------------------------------------------------------------------

def incident_dirs() -> list[Path]:
    return sorted(p for split in ("standard", "adversarial", "live") if (DATA / split).exists()
                  for p in (DATA / split).iterdir() if (p / "label.json").exists())


def load(d: Path):
    alert = json.loads((d / "alert.json").read_text())
    logs = pd.read_json(d / "logs.jsonl", lines=True)
    metrics = pd.read_parquet(d / "metrics.parquet")
    label = json.loads((d / "label.json").read_text())
    return alert, logs, metrics, label


def service_graph(anomalous: set[str], touched: set[str], diagnosed: str | None, truth: str | None) -> str:
    lines = ['digraph G { rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=12, color="#8a94a6"];',
             'edge [color="#8a94a6"];']
    for s in SERVICES:
        fill = "#ffd8cc" if s in anomalous else "#eef1f5"
        pen = "3" if s in touched else "1"
        color = "#1c5d99" if s in touched else "#8a94a6"
        extra = ""
        if diagnosed == s:
            extra = ', peripheries=2, color="#d9480f", penwidth=3'
        label = s + ("\\n✓ root cause" if truth == s else "")
        lines.append(f'"{s}" [label="{label}", fillcolor="{fill}", penwidth={pen}, color="{color}"{extra}];')
    for a, b in EDGES:
        lines.append(f'"{a}" -> "{b}";')
    lines.append("}")
    return "\n".join(lines)


def metric_chart(metrics: pd.DataFrame, service: str, metric: str, windows: list[tuple[int, int]] = ()):
    sub = metrics[metrics["service"] == service]
    fig = go.Figure(go.Scatter(x=sub["t"] / 60, y=sub[metric], mode="lines", name=f"{service}.{metric}",
                               line=dict(color="#d9480f")))
    for t0, t1 in windows:
        fig.add_vrect(x0=t0 / 60, x1=t1 / 60, fillcolor="#1c5d99", opacity=0.15, line_width=0)
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10), title=f"{service}.{metric}",
                      xaxis_title="minute", showlegend=False)
    return fig


def describe(ev: dict) -> str:
    e = ev["event"]
    if e == "tool_call":
        args = {k: v for k, v in (ev.get("args") or {}).items() if v not in (None, "")}
        return f"🔧 `{ev['tool']}` {json.dumps(args)}"
    if e == "finding":
        refs = ", ".join(c["ref"] for c in ev.get("citations", []))
        return f"📌 **{ev['claim']}** _(conf {ev['confidence']:.2f}; {refs})_"
    if e == "followup":
        return f"❓ follow-up → **{ev['specialist']}**: {ev['question']}"
    if e == "diagnosis":
        return f"🎯 **{ev['fault']} on {ev['service']}** (confidence {ev['confidence']:.2f})"
    if e == "dropped_citations":
        return f"✂️ dropped ungrounded citations: {', '.join(ev['refs'])}"
    if e == "start":
        return "▶️ started" + (" (follow-up)" if ev.get("followup") else "")
    if e == "end":
        return f"⏹ done · {ev['tool_calls']} tool calls · {ev['findings']} findings"
    return ""


def random_spec() -> ChaosSpec:
    rng = random.Random()
    fault = rng.choice(FAULTS)
    service = rng.choice(FAULT_SERVICES[fault])
    kinds = ["cpu_spike", "noisy_warning", "unrelated_deploy", "gc_logs", "disk_warning"]
    herrings = [RedHerring(kind=rng.choice(kinds), service=rng.choice([s for s in SERVICES if s != service]),
                           at_min=rng.randint(6, 30)) for _ in range(rng.randint(1, 3))]
    return ChaosSpec(incident_id=f"live-{int(time.time())}", fault=fault, service=service,
                     onset_min=rng.randint(12, 35), severity=round(rng.uniform(0.4, 0.9), 2),
                     red_herrings=herrings, noise=round(rng.uniform(0.1, 0.3), 2), seed=rng.randint(0, 10_000))


# --- pages -----------------------------------------------------------------------------------

def war_room():
    st.title("🔥 War Room")
    st.caption("Fire an incident and watch the agents investigate live. The ground truth stays sealed until you reveal it.")
    dirs = incident_dirs()
    c1, c2, c3 = st.columns([3, 2, 2])
    with c3:
        st.write("")
        if st.button("💥 Unleash chaos", width="stretch", help="Render a fresh random incident with red herrings"):
            d = render(random_spec(), DATA / "live")
            st.session_state["incident"] = str(d)
            st.rerun()
    names = [f"{d.parent.name}/{d.name}" for d in dirs]
    default = names.index(str(Path(st.session_state["incident"]).relative_to(DATA))) if "incident" in st.session_state else 0
    with c1:
        choice = st.selectbox("Incident", names, index=default)
    with c2:
        approach = st.radio("Approach", ["multi", "single"], horizontal=True,
                            format_func={"multi": "B · Coordinator + specialists", "single": "A · Single agent"}.get)
    d = DATA / choice
    alert, logs, metrics, label = load(d)
    anoms = anomalies(metrics)
    st.error(f"🚨 **{alert['title']}** · {alert['severity']} · fired {alert['fired_at']}")

    graph_slot = st.empty()
    graph_slot.graphviz_chart(service_graph(set(), set(), None, None))
    lane_names = LANES[approach]
    cols = st.columns(len(lane_names))
    lanes = {}
    for col, name in zip(cols, lane_names):
        col.markdown(f"**{name.title()}**")
        lanes[name] = col.container(height=360)

    if st.button("▶️ Start triage", type="primary"):
        from triage.run import triage_incident

        q: queue.Queue = queue.Queue()
        result: dict = {}

        def work():
            try:
                result.update(triage_incident(d, approach, live_queue=q, trace_dir=ROOT / "traces"))
            except Exception as e:
                result["error"] = str(e)

        th = threading.Thread(target=work, daemon=True)
        th.start()
        touched: set[str] = set()
        while th.is_alive() or not q.empty():
            try:
                ev = q.get(timeout=0.3)
            except queue.Empty:
                continue
            svc = (ev.get("args") or {}).get("service")
            if svc:
                touched.add(svc)
            if ev["event"] == "tool_call" and ev.get("tool") == "list_anomalies":
                graph_slot.graphviz_chart(service_graph({a["service"] for a in anoms}, touched, None, None))
            elif ev["event"] == "tool_call":
                graph_slot.graphviz_chart(service_graph(set(), touched, None, None))
            text = describe(ev)
            if text and ev["agent"] in lanes:
                lanes[ev["agent"]].markdown(text)
        if "error" in result:
            st.exception(RuntimeError(result["error"]))
            return
        st.session_state["last_run"] = {"incident": choice, "approach": approach,
                                        "diagnosis": result["diagnosis"].model_dump(), "usage": result["usage"]}

    run = st.session_state.get("last_run")
    if run and run["incident"] == choice:
        dx, usage = run["diagnosis"], run["usage"]
        reveal = st.toggle("🔓 Reveal sealed ground truth")
        graph_slot.graphviz_chart(service_graph({a["service"] for a in anoms}, set(), dx["service"],
                                                label["service"] if reveal else None))
        m = st.columns(5)
        m[0].metric("Diagnosis", f"{dx['fault']}", dx["service"])
        m[1].metric("Confidence", f"{dx['confidence']:.0%}")
        m[2].metric("Tool calls", usage["tool_calls"])
        m[3].metric("Tokens", f"{usage['tokens_in'] + usage['tokens_out']:,}")
        m[4].metric("Cost / latency", f"${usage['cost_usd']:.4f}", f"{usage['latency_s']}s", delta_color="off")
        if reveal:
            ok = dx["fault"] == label["fault"] and dx["service"] == label["service"]
            (st.success if ok else st.error)(f"Ground truth: **{label['fault']} on {label['service']}** "
                                             f"(onset t={label['onset_ts']}s) → {'✅ correct' if ok else '❌ wrong'}")
        st.markdown(f"**Explanation.** {dx['explanation']}")
        cited = [c["ref"] for c in dx["citations"] if c["kind"] == "metric"]
        charts = []
        for ref in cited[:4]:
            try:
                series, window = ref.split("@")
                svc, metric = series.split(".", 1)
                t0, t1 = map(int, window.split("-"))
                charts.append(metric_chart(metrics, svc, metric, [(t0, t1)]))
            except ValueError:
                continue
        if charts:
            st.markdown("**Cited metric windows** (shaded)")
            for col, fig in zip(st.columns(len(charts)), charts):
                col.plotly_chart(fig, width="stretch")
        log_refs = [c["ref"] for c in dx["citations"] if c["kind"] == "log"]
        if log_refs:
            st.markdown("**Cited log lines**")
            st.dataframe(logs[logs["id"].isin(log_refs)][["id", "time", "service", "level", "msg"]],
                         hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        c1.markdown("**Operator checks**\n" + "\n".join(f"- {x}" for x in dx["operator_checks"]))
        c2.markdown("**Safe next steps**\n" + "\n".join(f"- {x}" for x in dx["safe_next_steps"]))


def arena():
    st.title("🏟️ Arena")
    if not RESULTS.exists():
        st.info("No results yet. Run `python -m eval.run` first.")
        return
    from eval.report import summarise

    df = pd.read_csv(RESULTS)
    summary = summarise(df)
    st.subheader("Leaderboard")
    st.dataframe(summary, hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    acc = df.groupby(["split", "approach", "fault_true"])["correct"].mean().reset_index()
    fig = go.Figure()
    for a, g in acc.groupby("approach"):
        g = g[g["split"] == "standard"] if (g["split"] == "standard").any() else g
        fig.add_bar(x=g["fault_true"], y=g["correct"], name=a)
    fig.update_layout(barmode="group", title="Accuracy by fault type (standard split)", yaxis_tickformat=".0%", height=360)
    c1.plotly_chart(fig, width="stretch")
    fig2 = go.Figure()
    for a, g in df.groupby("approach"):
        fig2.add_scatter(x=g["cost_usd"], y=g["latency_s"], mode="markers", name=a,
                         marker=dict(symbol=["circle" if c else "x" for c in g["correct"]], size=9))
    fig2.update_layout(title="Cost vs latency per run (x = wrong)", xaxis_title="USD", yaxis_title="seconds", height=360)
    c2.plotly_chart(fig2, width="stretch")
    st.subheader("Failures")
    wrong = df[~df["correct"].astype(bool)]
    st.dataframe(wrong[["split", "incident", "approach", "seed", "fault_true", "service_true", "fault_pred",
                        "service_pred", "confidence", "explanation"]], hide_index=True, width="stretch")


def explorer():
    st.title("🔎 Incident Explorer")
    dirs = incident_dirs()
    choice = st.selectbox("Incident", [f"{d.parent.name}/{d.name}" for d in dirs])
    d = DATA / choice
    alert, logs, metrics, label = load(d)
    st.json(alert, expanded=False)
    if st.toggle("🔓 Reveal sealed label"):
        st.success(f"{label['fault']} on {label['service']} at t={label['onset_ts']}s · "
                   f"{len(label['key_evidence_ids'])} key evidence lines")
    metric = st.selectbox("Metric", METRICS, index=1)
    fig = go.Figure()
    for s in SERVICES:
        sub = metrics[metrics["service"] == s]
        fig.add_scatter(x=sub["t"] / 60, y=sub[metric], mode="lines", name=s)
    fig.update_layout(height=380, xaxis_title="minute", title=metric)
    st.plotly_chart(fig, width="stretch")
    st.markdown("**Detected anomalies**")
    st.dataframe(pd.DataFrame(anomalies(metrics)), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    svc = c1.multiselect("Service", SERVICES)
    lvl = c2.multiselect("Level", ["INFO", "WARN", "ERROR"], default=["WARN", "ERROR"])
    view = logs[(logs["service"].isin(svc) if svc else True) & logs["level"].isin(lvl)]
    st.dataframe(view[["id", "time", "service", "level", "msg"]], hide_index=True, width="stretch", height=400)


PAGES = {"War Room": war_room, "Arena": arena, "Incident Explorer": explorer}
page = st.sidebar.radio("Chaos Arena", list(PAGES))
st.sidebar.caption("Single agent vs coordinator + specialists, on incidents from a fault-injection simulator.")
PAGES[page]()
