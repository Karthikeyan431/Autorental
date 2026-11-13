"""Storing and serving documents (docs/kyc.md "Documents").

* `store_document` checks and cleans the upload (app.core.files), encrypts it to disk and adds
  the `documents` row in the caller's transaction. If the transaction rolls back, the encrypted
  file is left without a row; it cannot be served and holds nothing readable without the key.
* `open_document` checks the reader's access, then writes a `document_access_log` row and an
  audit entry in the same transaction before anything is streamed. A reader without access gets
  404 and nothing is logged as a view.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import Settings
from app.core.files import document_store, prepare_upload
from app.core.permissions import CurrentUser
from app.core.time import utc_now
from app.modules.documents.models import Document, DocumentAccessLog
from app.modules.drivers.access import is_owner_or_manager, not_found
from app.modules.drivers.models import Driver
from app.modules.kyc.models import KycCheck


def store_document(
    session: Session,
    settings: Settings,
    *,
    data: bytes,
    owner_type: str,
    owner_id: int,
    doc_type: str,
    uploaded_by: int,
    max_side: int | None = None,
) -> Document:
    prepared = prepare_upload(data, max_side=max_side)
    stored = document_store(settings).save(prepared.data)
    document = Document(
        owner_type=owner_type,
        owner_id=owner_id,
        doc_type=doc_type,
        storage_key=stored.storage_key,
        sha256=prepared.sha256,
        mime_type=prepared.mime_type,
        size_bytes=len(prepared.data),
        key_id=stored.key_id,
        uploaded_by=uploaded_by,
    )
    session.add(document)
    session.flush()
    return document


def document_driver(session: Session, document: Document) -> Driver | None:
    if document.owner_type == "driver":
        return session.get(Driver, document.owner_id)
    check = session.get(KycCheck, document.owner_id)
    return session.get(Driver, check.driver_id) if check is not None else None


def get_visible_document(session: Session, user: CurrentUser, document_id: int) -> Document:
    """The document if this user may see it, else 404 (never 403: docs/security.md). Driver
    photos and vehicle papers: every signed-in user (N1). KYC documents: the owner and the
    current manager (D46)."""
    document = session.get(Document, document_id)
    if document is None or document.purged_at is not None:
        raise not_found()
    if document.owner_type == "vehicle":
        return document  # vehicle papers hold no personal data: every signed-in user
    driver = document_driver(session, document)
    if driver is None:
        raise not_found()
    if document.doc_type == "driver_photo":
        return document  # every signed-in user sees driver photos (N1)
    # D46: KYC document images show masked values in full: owner and current manager only.
    if not is_owner_or_manager(user, driver):
        raise not_found()
    return document


@dataclass(frozen=True)
class OpenedDocument:
    document: Document
    chunks: Iterator[bytes]


def open_document(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    document_id: int,
    *,
    purpose: str,
    ip: str | None,
) -> OpenedDocument:
    document = get_visible_document(session, user, document_id)
    session.add(
        DocumentAccessLog(
            document_id=document.id, user_id=user.id, at=utc_now(), ip=ip, purpose=purpose
        )
    )
    write_audit(
        session,
        action="document.viewed",
        entity_type="document",
        entity_id=document.id,
        actor_id=user.id,
        after={"doc_type": document.doc_type, "purpose": purpose},
        ip=ip,
    )
    session.flush()
    store = document_store(settings)
    chunks = store.read_chunks(document.storage_key, document.key_id)
    return OpenedDocument(document=document, chunks=chunks)
