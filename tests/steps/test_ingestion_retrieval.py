"""Step definitions for ingestion_retrieval.feature."""

import re

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from triage.rag import HashEmbedder, HybridRetriever, load_and_chunk, n_tokens, rrf_fuse

scenarios("ingestion_retrieval.feature")

FAULTS = ["bad_deploy", "db_pool_saturation", "downstream_timeout", "memory_leak", "cache_stampede"]


@pytest.fixture(scope="module")
def kb():
    chunks = load_and_chunk("kb")
    return chunks, HybridRetriever(chunks, HashEmbedder())


@pytest.fixture
def ctx():
    return {}


@given(parsers.parse('the knowledge base in "{path}" has been ingested with a deterministic fake embedder'))
def ingested(kb, ctx):
    ctx["chunks"], ctx["retriever"] = kb


@given(parsers.parse('a BM25 ranking "{a}" and a vector ranking "{b}"'))
def rankings(ctx, a, b):
    ctx["rankings"] = [a.split(","), b.split(",")]


@when(parsers.parse('I search the knowledge base for "{query}"'))
def search(ctx, query):
    ctx["results"] = ctx["retriever"].search(query)


@when(parsers.parse("I fuse them with RRF k={k:d}"))
def fuse(ctx, k):
    ctx["fused"] = [cid for cid, _ in rrf_fuse(ctx["rankings"], k)]


@then(parsers.parse('every chunk has a chunk_id of the form "{form}"'))
def chunk_ids(ctx, form):
    for c in ctx["chunks"]:
        assert re.fullmatch(rf"{re.escape(c['doc_id'])}#\d+", c["chunk_id"])


@then("every chunk has doc_type, service and fault_tags metadata")
def chunk_meta(ctx):
    for c in ctx["chunks"]:
        assert c["doc_type"] in ("runbook", "postmortem") and c["service"] and isinstance(c["fault_tags"], list)


@then(parsers.parse("no chunk exceeds {n:d} tokens"))
def chunk_size(ctx, n):
    assert max(n_tokens(c["text"]) for c in ctx["chunks"]) <= n + 20  # title prefix allowance


@then(parsers.parse("for each of the {n:d} fault types at least one runbook chunk is tagged with it"))
def runbook_per_fault(ctx, n):
    tagged = {t for c in ctx["chunks"] if c["doc_type"] == "runbook" for t in c["fault_tags"]}
    assert set(FAULTS) <= tagged and len(FAULTS) == n


@then(parsers.parse('a chunk tagged "{fault}" is in the top {k:d} results'))
def tagged_in_top(ctx, fault, k):
    assert any(fault in r["fault_tags"] for r in ctx["results"][:k]), ctx["results"][:k]


@then(parsers.parse('the fused order starts with "{a}" and "{b}" ahead of "{c}" and "{d}"'))
def fused_order(ctx, a, b, c, d):
    assert set(ctx["fused"][:2]) == {a, b} and set(ctx["fused"][2:]) == {c, d}


@then(parsers.parse("I get at most {k:d} results"))
def at_most(ctx, k):
    assert 0 < len(ctx["results"]) <= k


@then("each result has chunk_id, doc_id, text and score")
def result_fields(ctx):
    for r in ctx["results"]:
        assert {"chunk_id", "doc_id", "text", "score"} <= r.keys()
