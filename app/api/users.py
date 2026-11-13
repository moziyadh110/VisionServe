import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_key
from app.core.security import generate_api_key
from app.db.models import ApiKey, User
from app.db.session import get_session
from app.schemas.users import KeyRotated, UserCreate, UserCreated

router = APIRouter(prefix="/v1", tags=["users"])


def _new_key(user_id: int) -> tuple[str, ApiKey]:
    key, prefix, key_hash = generate_api_key()
    return key, ApiKey(user_id=user_id, key_prefix=prefix, key_hash=key_hash)


@router.post("/users", status_code=201, response_model=UserCreated)
async def create_user(
    body: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    x_admin_token: str | None = Header(default=None),
) -> UserCreated:
    """Create a user and return their API key. This is the only time the key is visible."""
    expected = request.app.state.settings.admin_token
    if expected and not (x_admin_token and hmac.compare_digest(x_admin_token, expected)):
        raise HTTPException(401, "Admin token required")

    user = User(email=body.email.lower())
    session.add(user)
    try:
        await session.flush()  # sends the INSERT now so we get user.id (or a conflict)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "A user with this email already exists") from None

    key, key_row = _new_key(user.id)
    session.add(key_row)
    await session.commit()
    return UserCreated(user_id=user.id, email=user.email, plan=user.plan, api_key=key)


@router.post("/keys/rotate", response_model=KeyRotated)
async def rotate_key(
    current: ApiKey = Depends(get_current_key),
    session: AsyncSession = Depends(get_session),
) -> KeyRotated:
    """Revoke the key used for this call and issue a new one, in one transaction."""
    current.revoked_at = datetime.now(UTC)
    key, key_row = _new_key(current.user_id)
    session.add(key_row)
    await session.commit()
    return KeyRotated(api_key=key)
