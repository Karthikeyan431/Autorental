"""Documents: metadata and the only way to read a file (docs/kyc.md, docs/security.md).

`GET /documents/{id}/content` checks access, logs the view (document_access_log and the audit
log) and streams the decrypted file with `Cache-Control: no-store`. PDFs are always sent as
attachments, never inline; images are sent inline for the review screen. A reader without access
gets 404.
"""

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import AppError
from app.core.files import MIME_PDF, FileDecryptError
from app.core.permissions import CurrentUser, authenticated
from app.core.request_context import client_ip
from app.modules.documents import service
from app.modules.documents.schemas import DocumentOut, document_out

router = APIRouter(prefix="/documents", tags=["documents"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", MIME_PDF: "pdf"}


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: DbSession, user: SignedIn) -> DocumentOut:
    return document_out(service.get_visible_document(session, user, document_id))


@router.get("/{document_id}/content")
def get_document_content(
    document_id: int,
    request: Request,
    session: DbSession,
    user: SignedIn,
    purpose: Annotated[Literal["view", "download"], Query()] = "view",
) -> StreamingResponse:
    opened = service.open_document(
        session,
        request.app.state.settings,
        user,
        document_id,
        purpose=purpose,
        ip=client_ip(request),
    )
    document = opened.document
    try:
        first = next(opened.chunks)  # fail before any byte is sent if the file is damaged
    except (FileDecryptError, StopIteration) as exc:
        raise AppError(
            "DOCUMENT_UNREADABLE",
            "This document could not be read. Please upload it again.",
            status_code=500,
        ) from exc

    def body() -> Iterator[bytes]:
        yield first
        yield from opened.chunks

    filename = f"{document.doc_type}-{document.id}.{_EXTENSIONS[document.mime_type]}"
    inline = document.mime_type != MIME_PDF and purpose == "view"
    disposition = "inline" if inline else "attachment"
    headers = {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Length": str(document.size_bytes),
    }
    return StreamingResponse(body(), media_type=document.mime_type, headers=headers)
