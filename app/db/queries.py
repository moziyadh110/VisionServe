import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImageRecord
from app.ml.images import DecodedImage


def image_s3_key(user_id: int, sha256: str) -> str:
    return f"{user_id}/{sha256}"


async def get_or_create_image(
    session: AsyncSession, user_id: int, upload: DecodedImage
) -> ImageRecord:
    """Store each distinct image once per user, keyed by its SHA-256.

    The UNIQUE (user_id, sha256) constraint is the real guarantee: if two identical
    uploads race, one INSERT fails and we read back the row the other one created.
    The object itself is written to MinIO in Milestone 3; s3_key is where it will live.
    """
    sha256 = hashlib.sha256(upload.data).hexdigest()
    query = select(ImageRecord).where(ImageRecord.user_id == user_id, ImageRecord.sha256 == sha256)
    existing = await session.scalar(query)
    if existing:
        return existing

    row = ImageRecord(
        user_id=user_id,
        sha256=sha256,
        s3_key=image_s3_key(user_id, sha256),
        width=upload.image.width,
        height=upload.image.height,
        bytes=len(upload.data),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return (await session.scalars(query)).one()
    return row
