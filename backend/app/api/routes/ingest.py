"""Document ingestion endpoints."""

# NOTE: deliberately no `from __future__ import annotations` here.
# slowapi's @limiter.limit wrapper makes FastAPI resolve type hints against
# slowapi's module globals, where these types do not exist, so string
# annotations break dependency injection on every decorated route.
import logging
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import limiter, require_principal
from app.config.settings import Settings, get_settings
from app.db.session import get_db
from app.models.document import IngestedDocument
from app.retrieval.chunking import SUPPORTED_SUFFIXES, UnsupportedDocument
from app.services import ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class IngestResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    indexed_faiss: int
    indexed_moss: int
    moss_status: str
    warnings: list[str] = Field(default_factory=list)


class TextIngestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500_000)


class DocumentSummary(BaseModel):
    id: str
    filename: str
    chunk_count: int
    indexed_moss: bool
    status: str


def _safe_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe basename.

    Strips any directory component before sanitising, so a crafted name like
    ``../../etc/passwd`` cannot escape the upload directory.
    """
    base = Path(name).name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "document"
    return cleaned[:200]


@router.post("", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def ingest_document(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
    file: Annotated[UploadFile, File(description="A .txt, .md or .pdf document")],
) -> IngestResponse:
    """Upload a document, chunk it, embed it and index it."""
    filename = _safe_filename(file.filename or "document.txt")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type {suffix or '(none)'}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
            ),
        )

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty."
        )

    # Store under a unique name so concurrent uploads of the same filename
    # cannot overwrite one another mid-read.
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    stored = settings.uploads_path / f"{uuid.uuid4().hex}_{filename}"
    stored.write_bytes(payload)

    try:
        result = await ingestion.ingest_file(
            stored,
            db=db,
            original_name=filename,
            content_type=file.content_type or "application/octet-stream",
        )
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return IngestResponse(**asdict(result))


@router.post("/text", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def ingest_text(
    request: Request,
    payload: TextIngestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
) -> IngestResponse:
    """Ingest a plain-text document supplied inline."""
    try:
        result = await ingestion.ingest_raw_text(
            payload.text, db=db, name=_safe_filename(payload.name)
        )
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return IngestResponse(**asdict(result))


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[str, Depends(require_principal)],
) -> list[DocumentSummary]:
    """List what is currently in the corpus."""
    rows = (
        await db.execute(
            select(IngestedDocument).order_by(IngestedDocument.created_at.desc()).limit(100)
        )
    ).scalars().all()
    return [
        DocumentSummary(
            id=row.id,
            filename=row.filename,
            chunk_count=row.chunk_count,
            indexed_moss=bool(row.indexed_moss),
            status=row.status,
        )
        for row in rows
    ]
