"""Shared fixtures. FakeLLM lets agent scenarios run deterministically without the API."""

from __future__ import annotations

import os

import pytest


class FakeLLM:
    """Replays a scripted list of responses (tool calls or final structured output)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list = []

    def next(self, messages):
        self.calls.append(messages)
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        return self.script.pop(0)


@pytest.fixture
def fake_llm_factory():
    return FakeLLM


@pytest.fixture
def tmp_incidents(tmp_path):
    d = tmp_path / "incidents"
    d.mkdir()
    return d


def pytest_collection_modifyitems(config, items):
    if os.getenv("OPENAI_API_KEY"):
        return
    skip = pytest.mark.skip(reason="OPENAI_API_KEY not set")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
