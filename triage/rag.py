"""Knowledge base ingestion and hybrid (BM25 + vector) retrieval fused with RRF."""

from __future__ import annotations

RRF_K = 60


def load_and_chunk(kb_dir):
    """Split markdown docs on headings into chunks tagged with doc_type/service/fault_tags."""
    raise NotImplementedError


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over several ranked lists of chunk ids."""
    raise NotImplementedError


class HybridRetriever:
    """BM25 + Chroma retriever over the KB chunks."""

    def __init__(self, chunks, embedder):
        raise NotImplementedError

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Return top-k {chunk_id, doc_id, text, score}."""
        raise NotImplementedError
