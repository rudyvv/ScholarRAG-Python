"""change_user_role_enum_to_lowercase

Revision ID: 54b716791675
Revises: a7942b34e5dd
Create Date: 2026-06-12 22:46:21.197136
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54b716791675'
down_revision: Union[str, None] = 'a7942b34e5dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL ENUM is case-insensitive — 'USER' and 'user' are the same value.
    # First convert all data to lowercase, then change the ENUM definition.
    op.execute("UPDATE users SET role = LOWER(role)")
    op.execute(
        "ALTER TABLE users MODIFY COLUMN role "
        "ENUM('user','admin') NOT NULL DEFAULT 'user'"
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = UPPER(role)")
    op.execute(
        "ALTER TABLE users MODIFY COLUMN role "
        "ENUM('USER','ADMIN') NOT NULL DEFAULT 'USER'"
    )
