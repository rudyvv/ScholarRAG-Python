"""init: all 8 tables

Revision ID: ba079b373774
Revises:
Create Date: 2026-06-12 15:35:32.609022
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ba079b373774"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("USER", "ADMIN", name="userrole"),
            nullable=False,
            server_default="USER",
        ),
        sa.Column("org_tags", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # --- invite_codes ---
    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "used_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invite_codes_code", "invite_codes", ["code"], unique=True
    )

    # --- organization_tags ---
    op.create_table(
        "organization_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tag_name", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_tags_tag_name",
        "organization_tags",
        ["tag_name"],
        unique=True,
    )

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_md5", sa.String(32), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(255), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column(
            "doc_status",
            sa.Enum(
                "uploading", "processing", "ready", "failed", name="docstatus"
            ),
            nullable=False,
            server_default="uploading",
        ),
        sa.Column("org_tag", sa.String(50), nullable=True),
        sa.Column(
            "chunk_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_md5", "user_id", name="uk_md5_user"),
    )
    op.create_index("idx_doc_user_id", "documents", ["user_id"])
    op.create_index("idx_doc_org_tag", "documents", ["org_tag"])

    # --- document_chunks ---
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("embedding_id", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uk_doc_id_chunk_index"
        ),
    )

    # --- conversation_sessions ---
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("org_tag", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- conversation_messages ---
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("conversation_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", "system", name="messagerole"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_msg_session_id", "conversation_messages", ["session_id"]
    )

    # --- model_provider_configs ---
    op.create_table(
        "model_provider_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column("api_base_url", sa.String(512), nullable=False),
        sa.Column("api_key_ciphertext", sa.String(2048), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("org_tag", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_provider_config_provider_name",
        "model_provider_configs",
        ["provider_name"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order (children before parents).
    op.drop_table("model_provider_configs")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_sessions")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.drop_table("organization_tags")
    op.drop_table("invite_codes")
    op.drop_table("users")
