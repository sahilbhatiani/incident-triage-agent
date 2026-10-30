"""Shared fixtures and steps. ScriptedChatModel lets agent scenarios run without the API."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pytest_bdd import given, parsers

from sim.render import render
from triage.rag import HashEmbedder, HybridRetriever
from triage.schemas import ChaosSpec


class ScriptedChatModel(BaseChatModel):
    """Fake chat model. `responder(messages, bound_tool_names)` returns the next AIMessage."""

    responder: Callable[..., AIMessage]
    bound: list[str] = []
    delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        return self.model_copy(update={"bound": [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        if self.delay:
            time.sleep(self.delay)
        msg = self.responder(messages, self.bound)
        msg.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, args: dict | None = None, i: int = 0) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": f"call_{name}_{i}_{time.time_ns()}"}])


@pytest.fixture
def ctx():
    return {}


@pytest.fixture(scope="session")
def kb_retriever():
    return HybridRetriever.from_dir("kb", HashEmbedder())


@given(parsers.parse('a rendered incident with fault "{fault}" on "{service}"'), target_fixture="incident_dir")
def rendered_incident(ctx, tmp_path, fault, service):
    spec = ChaosSpec(incident_id="bdd-1", fault=fault, service=service, onset_min=20, severity=0.8, seed=11)
    ctx["incident_dir"] = render(spec, tmp_path / "incidents")
    return ctx["incident_dir"]


def pytest_collection_modifyitems(config, items):
    if os.getenv("OPENAI_API_KEY"):
        return
    skip = pytest.mark.skip(reason="OPENAI_API_KEY not set")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
