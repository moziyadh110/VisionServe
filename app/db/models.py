"""SQLAlchemy models for the four tables in the design doc.

Postgres is the real target. The `with_variant` types let the same models run on
SQLite in tests: SQLite only auto-increments a column typed exactly INTEGER, and
has no JSONB.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

BigIntPK = BigInteger().with_variant(Integer, "sqlite")
JsonB = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    plan: Mapped[str] = mapped_column(Text, default="free", server_default="free")
    created_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    key_prefix: Mapped[str] = mapped_column(Text, index=True)
    key_hash: Mapped[str] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class ImageRecord(Base):
    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("user_id", "sha256"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    sha256: Mapped[str] = mapped_column(Text)
    s3_key: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class InferenceRequest(Base):
    __tablename__ = "inference_requests"
    __table_args__ = (
        # Serves "my requests, newest first" and the per-user analytics queries.
        Index("ix_inference_requests_user_id_created_at", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id"))
    task: Mapped[str] = mapped_column(Text)  # caption | detailed_caption | ocr | tags
    status: Mapped[str] = mapped_column(Text)  # ok | error | timeout
    cache_hit: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    batch_size: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JsonB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
