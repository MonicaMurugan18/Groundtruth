"""Record of documents ingested into the retrieval corpus."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestedDocument(Base):
    """One source document and how it was chunked and indexed.

    Kept alongside the traces so a retrieval failure can be traced back to what
    was actually in the corpus at the time.
    """

    __tablename__ = "ingested_documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="text/plain")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    # Which engines successfully indexed this document.
    indexed_faiss: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed_moss: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(20), default="indexed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
