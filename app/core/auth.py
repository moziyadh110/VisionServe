import hmac

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_key, parse_prefix
from app.db.models import ApiKey, User
from app.db.session import get_session

# auto_error=False so we return our own 401 instead of FastAPI's default 403.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Missing or invalid API key")


async def get_current_key(
    api_key: str | None = Security(api_key_header),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    """Resolve the X-API-Key header to an active key row.

    Lookup is by the indexed prefix, then the hash is checked with
    hmac.compare_digest, which takes the same time whether the first or the last
    character differs, so response timing can't leak how close a guess was.
    """
    prefix = parse_prefix(api_key) if api_key else None
    if prefix is None:
        raise _unauthorized()

    candidates = await session.scalars(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.revoked_at.is_(None))
    )
    presented = hash_key(api_key)
    for candidate in candidates:
        if hmac.compare_digest(candidate.key_hash, presented):
            return candidate
    raise _unauthorized()


async def get_current_user(
    key: ApiKey = Depends(get_current_key),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, key.user_id)
    if user is None:
        raise _unauthorized()
    return user
