import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import ImageRecord, User
from app.db.session import get_session
from app.schemas.inference import ImageUrl

router = APIRouter(prefix="/v1", tags=["images"])


@router.get("/images/{image_id}/url", response_model=ImageUrl)
async def image_url(
    image_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ImageUrl:
    """Return a short-lived pre-signed URL so the client downloads straight from storage.

    The image bytes never pass through this API, and the bucket stays private.
    """
    row = await session.scalar(
        select(ImageRecord).where(ImageRecord.id == image_id, ImageRecord.user_id == user.id)
    )
    if row is None:
        raise HTTPException(404, "Image not found")
    ttl = request.app.state.settings.presigned_url_ttl_s
    url = await asyncio.to_thread(request.app.state.storage.presigned_url, row.s3_key, ttl)
    return ImageUrl(image_id=row.id, url=url, expires_in_s=ttl)
