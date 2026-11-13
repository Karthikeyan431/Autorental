"""Document metadata. Never the storage key, the key id or a file path."""

from datetime import datetime

from pydantic import BaseModel

from app.modules.documents.models import Document

CONTENT_URL = "/api/v1/documents/{id}/content"


class DocumentOut(BaseModel):
    id: int
    owner_type: str
    owner_id: int
    doc_type: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_by: int
    uploaded_at: datetime
    content_url: str


def document_out(document: Document) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        owner_type=document.owner_type,
        owner_id=document.owner_id,
        doc_type=document.doc_type,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        uploaded_by=document.uploaded_by,
        uploaded_at=document.uploaded_at,
        content_url=CONTENT_URL.format(id=document.id),
    )
