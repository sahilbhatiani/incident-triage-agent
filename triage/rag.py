"""Knowledge base ingestion and hybrid (BM25 + vector) retrieval fused with RRF."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import chromadb
import numpy as np
import tiktoken
import yaml
from rank_bm25 import BM25Okapi

RRF_K = 60
MAX_TOKENS = 400
OVERLAP_TOKENS = 50
CANDIDATES = 10

_enc = tiktoken.get_encoding("cl100k_base")


def n_tokens(text: str) -> int:
    return len(_enc.encode(text))


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


# --- ingestion -------------------------------------------------------------------------------

def _parse(path: Path) -> tuple[dict, str]:
    raw = path.read_text()
    _, front, body = raw.split("---", 2)
    return yaml.safe_load(front), body.strip()


def _window(text: str) -> list[str]:
    """Split text over MAX_TOKENS into overlapping token windows."""
    toks = _enc.encode(text)
    if len(toks) <= MAX_TOKENS:
        return [text]
    step = MAX_TOKENS - OVERLAP_TOKENS
    return [_enc.decode(toks[i:i + MAX_TOKENS]) for i in range(0, len(toks), step)]


def load_and_chunk(kb_dir) -> list[dict]:
    """Split markdown docs on headings into chunks tagged with doc_type/service/fault_tags."""
    chunks = []
    for path in sorted(Path(kb_dir).rglob("*.md")):
        meta, body = _parse(path)
        title = body.splitlines()[0].lstrip("# ").strip()
        sections = re.split(r"\n(?=## )", body)
        n = 0
        for sec in sections:
            sec = sec.strip()
            if sec.startswith("# ") and "\n## " not in sec and len(sec.splitlines()) == 1:
                continue  # bare title line
            for piece in _window(sec):
                chunks.append({
                    "chunk_id": f"{meta['doc_id']}#{n}",
                    "doc_id": meta["doc_id"],
                    "text": f"{title}\n{piece}" if not piece.startswith("# ") else piece,
                    "doc_type": meta["doc_type"],
                    "service": meta["service"],
                    "fault_tags": list(meta.get("fault_tags") or []),
                })
                n += 1
    return chunks


# --- embedders -------------------------------------------------------------------------------

class HashEmbedder:
    """Deterministic bag-of-words hashing embedder for offline tests."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def __call__(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = np.zeros(self.dim)
            for tok in tokenize(t):
                stem = tok[:5]
                v[int(hashlib.md5(stem.encode()).hexdigest(), 16) % self.dim] += 1
            norm = np.linalg.norm(v) or 1.0
            out.append((v / norm).tolist())
        return out


class OpenAIEmbedder:
    """OpenAI embeddings with an on-disk cache keyed by text hash."""

    def __init__(self, model: str = "text-embedding-3-small", cache_path: str = ".cache/embeddings.json"):
        from langchain_openai import OpenAIEmbeddings

        self.client = OpenAIEmbeddings(model=model)
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def __call__(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
        missing = [t for t, k in zip(texts, keys) if k not in self.cache]
        if missing:
            for t, vec in zip(missing, self.client.embed_documents(missing)):
                self.cache[hashlib.sha1(t.encode()).hexdigest()] = vec
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))
        return [self.cache[k] for k in keys]


# --- retrieval -------------------------------------------------------------------------------

def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion over several ranked lists of chunk ids."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class HybridRetriever:
    """BM25 + Chroma retriever over the KB chunks."""

    def __init__(self, chunks: list[dict], embedder):
        self.chunks = {c["chunk_id"]: c for c in chunks}
        self.ids = [c["chunk_id"] for c in chunks]
        self.embedder = embedder
        self.bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])
        client = chromadb.EphemeralClient()
        self.col = client.create_collection(f"kb-{uuid.uuid4().hex[:8]}", metadata={"hnsw:space": "cosine"})
        self.col.add(
            ids=self.ids,
            documents=[c["text"] for c in chunks],
            embeddings=embedder([c["text"] for c in chunks]),
            metadatas=[{"doc_id": c["doc_id"], "doc_type": c["doc_type"], "service": c["service"],
                        "fault_tags": ",".join(c["fault_tags"])} for c in chunks],
        )

    @classmethod
    def from_dir(cls, kb_dir, embedder) -> "HybridRetriever":
        return cls(load_and_chunk(kb_dir), embedder)

    def bm25_rank(self, query: str, n: int = CANDIDATES) -> list[str]:
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(-scores, kind="stable")[:n]
        return [self.ids[i] for i in order if scores[i] > 0]

    def vector_rank(self, query: str, n: int = CANDIDATES) -> list[str]:
        res = self.col.query(query_embeddings=self.embedder([query]), n_results=min(n, len(self.ids)))
        return res["ids"][0]

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Return top-k {chunk_id, doc_id, text, score} fused from BM25 and vector rankings."""
        fused = rrf_fuse([self.bm25_rank(query), self.vector_rank(query)])[:k]
        return [{"chunk_id": cid, "doc_id": self.chunks[cid]["doc_id"], "text": self.chunks[cid]["text"],
                 "score": round(score, 5), "fault_tags": self.chunks[cid]["fault_tags"]} for cid, score in fused]
