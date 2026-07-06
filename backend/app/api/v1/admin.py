"""Admin-only API endpoints.

Endpoints in this router require the caller to be authenticated
as a user with the ``ADMIN`` role.
"""

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_admin, get_db
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.response import paginated_response, success_response
from app.models.conversation import ConversationSession
from app.models.document import Document, DocStatus
from app.models.user import User, UserRole
from app.services.invite_code_service import (
    create_invite_code,
    list_invite_codes,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UpdateUserRequest(BaseModel):
    """Request body for updating a user."""

    username: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    org_tags: str | None = None


router = APIRouter(
    dependencies=[Depends(get_current_active_admin)],
)


@router.post("/invite-codes", status_code=201)
async def create_invite_code_endpoint(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """Create a new invite code.

    Request body should contain a ``code`` field with the invite code string.
    """
    code: str | None = body.get("code")
    if not code or not isinstance(code, str) or not code.strip():
        raise BadRequestException("Field 'code' is required and must be a non-empty string")

    try:
        invite = await create_invite_code(db, code=code.strip())
    except ValueError as e:
        raise BadRequestException(str(e)) from e

    return success_response(
        data={"code": invite.code, "is_used": invite.is_used, "created_at": invite.created_at.isoformat()},
        message="Invite code created",
        status_code=201,
    )


@router.get("/invite-codes")
async def list_invite_codes_endpoint(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """List all invite codes with pagination."""
    items, total = await list_invite_codes(db, page=page, size=size)

    return paginated_response(
        items=[
            {
                "id": c.id,
                "code": c.code,
                "is_used": c.is_used,
                "used_by": c.used_by,
                "created_at": c.created_at.isoformat(),
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            }
            for c in items
        ],
        total=total,
        page=page,
        page_size=size,
    )


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """List all registered users."""
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()

    return success_response(
        data={
            "items": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                    "is_active": u.is_active,
                    "org_tags": u.org_tags,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                    "updated_at": u.updated_at.isoformat() if u.updated_at else None,
                }
                for u in users
            ],
            "total": len(users),
        },
    )


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """Update a user's role and/or active status."""
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException("User not found")

    if body.username is not None:
        user.username = body.username
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role.upper()
    if body.is_active is not None:
        if user.role == UserRole.ADMIN and not body.is_active:
            raise BadRequestException("Cannot disable an admin account")
        user.is_active = body.is_active
    if body.org_tags is not None:
        user.org_tags = body.org_tags

    await db.commit()
    await db.refresh(user)

    return success_response(
        data={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "is_active": user.is_active,
            "org_tags": user.org_tags,
        },
        message="User updated",
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """Delete a user account and all associated data."""
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundException("User not found")

    # Delete dependent records in order: chunks → documents → messages → sessions → user
    from app.models.document import Document, DocumentChunk
    from app.models.conversation import ConversationSession, ConversationMessage

    # 1. Delete document chunks for all user's documents
    doc_stmt = select(Document.id).where(Document.user_id == user_id)
    doc_result = await db.execute(doc_stmt)
    doc_ids = [row[0] for row in doc_result.all()]
    if doc_ids:
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(doc_ids)))
    # 2. Delete all user's documents
    await db.execute(delete(Document).where(Document.user_id == user_id))
    # 3. Delete conversation messages for all user's sessions
    session_stmt = select(ConversationSession.id).where(ConversationSession.user_id == user_id)
    session_result = await db.execute(session_stmt)
    session_ids = [row[0] for row in session_result.all()]
    if session_ids:
        await db.execute(delete(ConversationMessage).where(ConversationMessage.session_id.in_(session_ids)))
    # 4. Delete all user's conversation sessions
    await db.execute(delete(ConversationSession).where(ConversationSession.user_id == user_id))
    # 5. Delete the user
    await db.delete(user)
    await db.commit()

    return success_response(message="User deleted")


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_active_admin),
):
    """Return aggregate platform statistics for the admin dashboard.

    Includes total users, documents, conversation sessions, and a
    breakdown of documents by processing status.
    """
    # Total users
    result = await db.execute(select(func.count()).select_from(User))
    total_users = result.scalar() or 0

    # Total documents
    result = await db.execute(select(func.count()).select_from(Document))
    total_documents = result.scalar() or 0

    # Total sessions
    result = await db.execute(select(func.count()).select_from(ConversationSession))
    total_sessions = result.scalar() or 0

    # Documents grouped by status
    stmt = select(Document.doc_status, func.count()).group_by(Document.doc_status)
    result = await db.execute(stmt)
    documents_by_status = {}
    for row in result:
        status_label = row[0].value if hasattr(row[0], "value") else str(row[0])
        documents_by_status[status_label] = row[1]

    return success_response(
        data={
            "total_users": total_users,
            "total_documents": total_documents,
            "total_sessions": total_sessions,
            "documents_by_status": documents_by_status,
        },
    )
