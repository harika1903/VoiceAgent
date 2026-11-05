"""Knowledge Base API — search, upload, and manage KB documents.

POST   /v1/kb/documents       — upload documents to the org's KB
GET    /v1/kb/documents       — list uploaded documents
DELETE /v1/kb/documents/{id}  — remove one document
GET    /v1/kb/search?q=...    — search the full KB (catalog + uploads)
GET    /v1/kb/stats            — catalog size and sample
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.auth import AuthContext, get_auth

router = APIRouter(prefix="/v1/kb", tags=["knowledge-base"])


class SearchResult(BaseModel):
    id: str
    text: str
    metadata: dict


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


class StatsResponse(BaseModel):
    size: int
    sample: list[SearchResult]


class DocumentInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    text: str = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)


class UploadRequest(BaseModel):
    documents: list[DocumentInput] = Field(..., min_length=1, max_length=100)


class UploadResponse(BaseModel):
    added: int
    total: int


class DeleteResponse(BaseModel):
    deleted: bool


# ── Helpers ───────────────────────────────────────────────────────────────

async def _build_kb(request: Request, org_id: str):
    from app.kb.store import load_kb_for_org
    from app.config import get_settings
    settings = get_settings()
    redis = request.app.state.redis
    return await load_kb_for_org(redis, org_id, catalog_path=settings.kb_default_catalog)


# ── Document CRUD ─────────────────────────────────────────────────────────

@router.post("/documents", response_model=UploadResponse)
async def upload_documents(
    body: UploadRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
):
    from app.kb.store import Document, save_documents, list_documents
    redis = request.app.state.redis
    docs = [Document(id=d.id, text=d.text, metadata=d.metadata) for d in body.documents]
    added = await save_documents(redis, auth.org_id, docs)
    all_docs = await list_documents(redis, auth.org_id)
    return UploadResponse(added=added, total=len(all_docs))


@router.get("/documents", response_model=list[SearchResult])
async def get_documents(
    request: Request,
    auth: AuthContext = Depends(get_auth),
):
    from app.kb.store import list_documents
    redis = request.app.state.redis
    docs = await list_documents(redis, auth.org_id)
    return [SearchResult(id=d.id, text=d.text, metadata=d.metadata) for d in docs]


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
):
    from app.kb.store import delete_document as kb_delete
    redis = request.app.state.redis
    deleted = await kb_delete(redis, auth.org_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return DeleteResponse(deleted=True)


# ── Search & Stats ────────────────────────────────────────────────────────

@router.get("/search", response_model=SearchResponse)
async def search_kb(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    top_k: int = Query(3, ge=1, le=10),
    auth: AuthContext = Depends(get_auth),
):
    kb = await _build_kb(request, auth.org_id)
    results = kb.search(q, top_k=top_k)
    return SearchResponse(
        query=q,
        results=[SearchResult(id=r.id, text=r.text, metadata=r.metadata) for r in results],
    )


@router.get("/stats", response_model=StatsResponse)
async def kb_stats(
    request: Request,
    auth: AuthContext = Depends(get_auth),
):
    kb = await _build_kb(request, auth.org_id)
    from app.kb.store import BM25Store
    sample = []
    if isinstance(kb, BM25Store) and kb._docs:
        for doc in kb._docs[:5]:
            sample.append(SearchResult(id=doc.id, text=doc.text, metadata=doc.metadata))
    return StatsResponse(size=kb.size, sample=sample)
