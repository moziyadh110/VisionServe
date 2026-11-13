import asyncio

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImageRecord
from app.ml.images import DecodedImage
from app.storage.s3 import ObjectStore


def image_s3_key(user_id: int, sha256: str) -> str:
    return f"users/{user_id}/{sha256}"


async def get_or_create_image(
    session: AsyncSession, storage: ObjectStore, user_id: int, upload: DecodedImage
) -> ImageRecord:
    """Store each distinct image once per user, keyed by its SHA-256 (dedupe).

    Order matters: upload the object first, then insert the row. If the insert
    fails, we're left with an object nobody points to (harmless, and the same key
    is reused next time) rather than a row pointing to a missing object.

    The UNIQUE (user_id, sha256) constraint is the real guarantee: if two identical
    uploads race, one INSERT fails and we read back the row the other one created.
    Both wrote the same bytes to the same key, so the object is fine either way.
    """
    query = select(ImageRecord).where(
        ImageRecord.user_id == user_id, ImageRecord.sha256 == upload.sha256
    )
    existing = await session.scalar(query)
    if existing:
        return existing

    key = image_s3_key(user_id, upload.sha256)
    await asyncio.to_thread(storage.put, key, upload.data, upload.content_type)

    row = ImageRecord(
        user_id=user_id,
        sha256=upload.sha256,
        s3_key=key,
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
