"""Chat / conversation API endpoints.

Provides a RAG-powered question-answering endpoint and CRUD operations
for conversation sessions and their messages.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.ratelimit import CHAT_LIMIT, limiter
from app.core.response import success_response
from app.models.conversation import ConversationMessage, ConversationSession
from app.models.user import User
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    query: str
    session_id: int | None = None
    doc_id: int | None = None


class CreateSessionRequest(BaseModel):
    title: str


class UpdateSessionRequest(BaseModel):
    title: str


class SessionItem(BaseModel):
    """Lightweight session model for list responses."""

    id: int
    title: str | None
    created_at: str | None
    updated_at: str | None


class MessageItem(BaseModel):
    """Lightweight message model for list responses."""

    id: int
    role: str
    content: str
    created_at: str | None


def _session_to_item(session: ConversationSession) -> SessionItem:
    """Convert a ConversationSession ORM instance to a serialisable model."""
    return SessionItem(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
    )


def _message_to_item(msg: ConversationMessage) -> MessageItem:
    """Convert a ConversationMessage ORM instance to a serialisable model."""
    return MessageItem(
        id=msg.id,
        role=msg.role.value if hasattr(msg.role, "value") else str(msg.role),
        content=msg.content,
        created_at=msg.created_at.isoformat() if msg.created_at else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/ask")
@limiter.limit(CHAT_LIMIT)
async def ask_question(
    request: Request,  # noqa: ARG001 — consumed by slowapi
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question using RAG and return the generated answer.

    Accepts an optional ``session_id`` to continue an existing
    conversation, and optional ``doc_id`` to restrict the search scope to a single document.
    """
    if not body.query.strip():
        return success_response(
            data={
                "answer": "请输入问题。",
                "sources": [],
                "session_id": None,
            },
        )

    rag = RAGService(db_session=db)
    result = await rag.answer_question(
        query=body.query,
        user_id=current_user.id,
        session_id=body.session_id,
        doc_id=body.doc_id,
    )

    return success_response(data=result)


@router.post("/ask/stream")
async def ask_question_stream(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question using RAG and stream the answer via SSE.

    Accepts the same request body as ``POST /ask`` but returns a
    ``text/event-stream`` response with the following events:

    - ``meta``: ``{"session_id": 1}`` — the session ID.
    - ``token``: ``{"token": "…"}`` — a text fragment of the answer.
    - ``sources``: ``{"sources": […]}`` — the source chunks used.
    - ``error``: ``{"message": "…"}`` — on failure.
    - ``done``: ``{}`` — signals stream completion.
    """
    if not body.query.strip():
        async def _empty() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'token', 'token': '请输入问题。'})}\n\n"
            yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(
            _empty(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    rag = RAGService(db_session=db)

    async def _stream() -> AsyncGenerator[str, None]:
        async for event in rag.answer_question_stream(
            query=body.query,
            user_id=current_user.id,
            session_id=body.session_id,
            doc_id=body.doc_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's conversation sessions.

    Results are ordered by most recently updated first.
    """
    stmt = (
        select(ConversationSession)
        .where(ConversationSession.user_id == current_user.id)
        .order_by(ConversationSession.updated_at.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return success_response(
        data={
            "items": [_session_to_item(s) for s in sessions],
            "total": len(sessions),
        },
    )


@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new conversation session."""
    session = ConversationSession(
        user_id=current_user.id,
        title=body.title,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return success_response(
        data=_session_to_item(session),
        message="Session created",
        status_code=201,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a conversation session (owner only)."""
    stmt = select(ConversationSession).where(
        ConversationSession.id == session_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise NotFoundException("Session not found")

    if session.user_id != current_user.id:
        raise ForbiddenException("You do not own this session")

    # Delete child messages first (FK constraint)
    from sqlalchemy import delete as sqla_delete

    await db.execute(
        sqla_delete(ConversationMessage).where(
            ConversationMessage.session_id == session_id
        )
    )
    await db.delete(session)
    await db.commit()

    return success_response(message="Session deleted")


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    body: UpdateSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a conversation session title (owner only)."""
    stmt = select(ConversationSession).where(
        ConversationSession.id == session_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise NotFoundException("Session not found")

    if session.user_id != current_user.id:
        raise ForbiddenException("You do not own this session")

    session.title = body.title
    await db.commit()
    await db.refresh(session)

    return success_response(
        data=_session_to_item(session),
        message="Session updated",
    )


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all messages in a session, ordered by creation time ascending."""
    # Verify session ownership
    stmt = select(ConversationSession).where(
        ConversationSession.id == session_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise NotFoundException("Session not found")

    if session.user_id != current_user.id:
        raise ForbiddenException("You do not own this session")

    # Load messages with session relationship
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.session_id == session_id)
        .order_by(ConversationMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return success_response(
        data={
            "items": [_message_to_item(m) for m in messages],
            "total": len(messages),
        },
    )
