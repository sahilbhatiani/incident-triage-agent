"""One entry point for both approaches, used by the eval runner, the UI and the CLI."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from triage.multi import build_multi_agent
from triage.single import build_single_agent
from triage.tools import IncidentTools
from triage.tracing import Tracer

load_dotenv()

APPROACHES = {"single": build_single_agent, "multi": build_multi_agent}


def agent_model() -> str:
    return os.getenv("AGENT_MODEL", "gpt-4.1-mini")


def make_llm(model: str | None = None, seed: int | None = None):
    from langchain_openai import ChatOpenAI

    kwargs = {"model": model or agent_model(), "temperature": 0}
    if seed is not None:
        kwargs["seed"] = seed
    return ChatOpenAI(**kwargs)


_retriever = None


def default_retriever():
    global _retriever
    if _retriever is None:
        from triage.rag import HybridRetriever, OpenAIEmbedder

        _retriever = HybridRetriever.from_dir("kb", OpenAIEmbedder(os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")))
    return _retriever


def triage_incident(incident_dir, approach: str, llm=None, retriever=None, tracer=None, trace_dir=None, live_queue=None):
    """Run one approach on one incident. Returns {diagnosis, usage, events}."""
    incident_dir = Path(incident_dir)
    tracer = tracer or Tracer(f"{incident_dir.name}-{approach}-{uuid.uuid4().hex[:6]}", trace_dir, live_queue, agent_model())
    tools = IncidentTools(incident_dir, retriever or default_retriever(), tracer)
    agent = APPROACHES[approach](llm or make_llm(), tools, tracer)
    diagnosis = agent.triage(tools.alert)
    return {"diagnosis": diagnosis, "usage": tracer.summary(), "events": tracer.events, "agent": agent}


if __name__ == "__main__":
    import sys

    out = triage_incident(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "single", trace_dir="traces")
    print(json.dumps({"diagnosis": out["diagnosis"].model_dump(), "usage": out["usage"]}, indent=2))
