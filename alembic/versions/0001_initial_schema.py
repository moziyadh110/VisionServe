"""Initial schema: users, api_keys, images, inference_requests.

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("plan", sa.Text, nullable=False, server_default="free"),
        _created_at(),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_prefix", sa.Text, nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    op.create_table(
        "images",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("bytes", sa.Integer),
        _created_at(),
        sa.UniqueConstraint("user_id", "sha256"),
    )

    op.create_table(
        "inference_requests",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("image_id", sa.BigInteger, sa.ForeignKey("images.id"), nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("batch_size", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("result", JSONB),
        sa.Column("error", sa.Text),
        _created_at(),
    )
    op.create_index(
        "ix_inference_requests_user_id_created_at",
        "inference_requests",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("inference_requests")
    op.drop_table("images")
    op.drop_table("api_keys")
    op.drop_table("users")
