"""Saved chat conversations, owned by an API key. The demo key never saves anything."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models import ChatMessage, ChatSession

TITLE_CHARS = 80


def get_owned(db: Session, api_key_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession:
    row = db.get(ChatSession, session_id)
    if row is None or row.api_key_id != api_key_id:
        raise APIError(404, "not_found", "No saved conversation with that id for this key.")
    return row


def start(db: Session, api_key_id: uuid.UUID, first_message: str, company: dict | None):
    title = " ".join(first_message.split())
    if len(title) > TITLE_CHARS:
        title = title[: TITLE_CHARS - 1].rstrip() + "\u2026"
    row = ChatSession(
        api_key_id=api_key_id,
        title=title,
        company_cik=(company or {}).get("cik"),
    )
    db.add(row)
    db.flush()
    return row


def append(db: Session, session: ChatSession, question: str, reply: dict) -> None:
    seq = db.scalar(
        select(func.coalesce(func.max(ChatMessage.seq), 0)).where(
            ChatMessage.session_id == session.id
        )
    )
    reply = {k: v for k, v in reply.items() if k != "session_id"}
    db.add(ChatMessage(session_id=session.id, seq=seq + 1, role="user", content=question))
    db.add(
        ChatMessage(
            session_id=session.id,
            seq=seq + 2,
            role="assistant",
            content=reply.get("answer") or "",
            reply=json.dumps(reply),
        )
    )
    session.updated_at = datetime.now(UTC)
    if reply.get("company") and not session.company_cik:
        session.company_cik = reply["company"]["cik"]
    db.commit()


def list_for(db: Session, api_key_id: uuid.UUID, limit: int) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.api_key_id == api_key_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
    )


def session_dict(row: ChatSession) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "company_cik": row.company_cik,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def messages(db: Session, session: ChatSession) -> list[dict]:
    out = []
    for m in db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.seq)
    ):
        item = {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        if m.reply:
            item["reply"] = json.loads(m.reply)
        out.append(item)
    return out


def delete(db: Session, session: ChatSession) -> None:
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()
