"""Knowledge Base store with BM25 search.

Zero external dependencies — uses only Python stdlib (math, re, collections).
Production seam: the KnowledgeBase protocol can be backed by pgvector, Pinecone,
or any vector DB later. The BM25 implementation here is good enough for catalogs
up to ~1000 documents; beyond that, swap in a proper search engine.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Document:
    """One searchable item (a product, an FAQ entry, a policy snippet, etc.)."""
    id: str
    text: str
    metadata: dict = field(default_factory=dict)

    def format_for_llm(self) -> str:
        """Human-readable string injected into the LLM context."""
        parts = [self.text]
        if self.metadata.get("price_inr"):
            parts.append(f"Price: Rs.{self.metadata['price_inr']:,}")
        if self.metadata.get("in_stock") is False:
            parts.append("(Currently out of stock)")
        return " | ".join(parts)


class KnowledgeBase(Protocol):
    """Seam: swap BM25 for vector search without touching the pipeline."""
    def search(self, query: str, top_k: int = 3) -> list[Document]: ...
    @property
    def size(self) -> int: ...


# ── Tokeniser ────────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could i me my we our you your "
    "he she it they them their this that these those of in to for on with "
    "at by from and or not but if".split()
)

_SPLIT_RE = re.compile(r"[a-z0-9]+")


def _tokenise(text: str) -> list[str]:
    return [w for w in _SPLIT_RE.findall(text.lower()) if w not in _STOP_WORDS]


# ── BM25 ─────────────────────────────────────────────────────────────────────

class BM25Store:
    """In-memory BM25 index over Documents."""

    def __init__(self, docs: list[Document], *, k1: float = 1.5, b: float = 0.75):
        self._docs = docs
        self._k1 = k1
        self._b = b

        self._doc_tokens: list[list[str]] = [_tokenise(d.text) for d in docs]
        self._doc_lens = [len(t) for t in self._doc_tokens]
        self._avgdl = sum(self._doc_lens) / max(len(docs), 1)
        self._n = len(docs)

        # Term -> number of docs containing it
        self._df: dict[str, int] = Counter()
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] += 1

    @property
    def size(self) -> int:
        return self._n

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        if not self._docs:
            return []

        q_tokens = _tokenise(query)
        if not q_tokens:
            return []

        scores: list[float] = []
        for i, doc_tokens in enumerate(self._doc_tokens):
            score = 0.0
            tf_counter = Counter(doc_tokens)
            dl = self._doc_lens[i]

            for qt in q_tokens:
                if qt not in self._df:
                    continue
                tf = tf_counter[qt]
                df = self._df[qt]
                idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * dl / self._avgdl)
                score += idf * numerator / denominator

            scores.append(score)

        # Return top-k with score > 0
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, sc in ranked:
            if sc <= 0 or len(results) >= top_k:
                break
            results.append(self._docs[idx])
        return results


# ── Loader ───────────────────────────────────────────────────────────────────

def load_product_catalog(path: str | Path) -> BM25Store:
    """Load a JSON product catalog and build a BM25 index."""
    path = Path(path)
    with open(path) as f:
        items = json.load(f)

    docs = []
    for item in items:
        # Build searchable text from all fields
        parts = [
            item.get("name", ""),
            item.get("category", ""),
            item.get("metal", ""),
            item.get("description", ""),
        ]
        if item.get("stones"):
            parts.append(item["stones"])
        text = " ".join(p for p in parts if p)

        docs.append(Document(
            id=item.get("sku", item.get("name", "")),
            text=text,
            metadata=item,
        ))

    return BM25Store(docs)


class EmptyKnowledgeBase:
    """No-op KB for when no catalog is configured."""
    def search(self, query: str, top_k: int = 3) -> list[Document]:
        return []

    @property
    def size(self) -> int:
        return 0


# ── Redis-backed document storage (per-org) ──────────────────────────────────

def _kb_key(org_id: str) -> str:
    return f"kb:{org_id}:docs"


async def save_documents(redis, org_id: str, docs: list[Document]) -> int:
    """Add documents to the org's KB in Redis. Returns count added."""
    key = _kb_key(org_id)
    pipe = redis.pipeline()
    for doc in docs:
        pipe.hset(key, doc.id, json.dumps({"text": doc.text, "metadata": doc.metadata}))
    await pipe.execute()
    return len(docs)


async def delete_document(redis, org_id: str, doc_id: str) -> bool:
    """Remove one document. Returns True if it existed."""
    return await redis.hdel(_kb_key(org_id), doc_id) > 0


async def list_documents(redis, org_id: str) -> list[Document]:
    """List all uploaded documents for an org."""
    raw = await redis.hgetall(_kb_key(org_id))
    docs = []
    for doc_id, data_str in raw.items():
        data = json.loads(data_str)
        docs.append(Document(id=doc_id, text=data["text"], metadata=data.get("metadata", {})))
    return docs


async def load_kb_for_org(
    redis,
    org_id: str,
    catalog_path: str | Path | None = None,
) -> BM25Store:
    """Build a BM25 index from static catalog + org's uploaded documents."""
    all_docs: list[Document] = []

    if catalog_path:
        p = Path(catalog_path)
        if p.exists():
            store = load_product_catalog(p)
            all_docs.extend(store._docs)

    uploaded = await list_documents(redis, org_id)
    all_docs.extend(uploaded)

    return BM25Store(all_docs) if all_docs else BM25Store([])
