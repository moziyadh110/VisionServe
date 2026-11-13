import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import InferenceRequest, User
from app.db.session import get_session
from app.schemas.inference import RequestPage, RequestRecord
from app.schemas.users import TaskStats, UsageStats

router = APIRouter(prefix="/v1", tags=["requests"])


@router.get("/requests", response_model=RequestPage)
async def list_requests(
    cursor: int | None = Query(default=None, description="next_cursor from the previous page"),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RequestPage:
    """Newest first, with cursor (keyset) pagination.

    Instead of OFFSET (which makes Postgres walk and discard every earlier row),
    the cursor is the last id seen, so each page starts with an index seek.
    Fetching limit + 1 rows tells us whether another page exists.
    """
    query = (
        select(InferenceRequest)
        .where(InferenceRequest.user_id == user.id)
        .order_by(InferenceRequest.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        query = query.where(InferenceRequest.id < cursor)
    rows = list(await session.scalars(query))

    has_more = len(rows) > limit
    rows = rows[:limit]
    return RequestPage(
        items=[RequestRecord.model_validate(r) for r in rows],
        next_cursor=rows[-1].id if has_more else None,
    )


@router.get("/requests/{request_id}", response_model=RequestRecord)
async def get_request(
    request_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RequestRecord:
    # Filtering by user_id means another user's id looks exactly like a missing one (404),
    # so callers can't even learn which ids exist.
    row = await session.scalar(
        select(InferenceRequest).where(
            InferenceRequest.id == request_id, InferenceRequest.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(404, "Request not found")
    return RequestRecord.model_validate(row)


@router.get("/stats/me", response_model=UsageStats)
async def my_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageStats:
    mine = InferenceRequest.user_id == user.id
    now = datetime.now(UTC)

    total, hits, avg_latency = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((InferenceRequest.cache_hit, 1), else_=0)), 0),
                func.avg(InferenceRequest.latency_ms),
            ).where(mine)
        )
    ).one()

    last_24h = await session.scalar(
        select(func.count()).where(mine, InferenceRequest.created_at >= now - timedelta(hours=24))
    )

    by_task = (
        await session.execute(
            select(InferenceRequest.task, func.count())
            .where(mine)
            .group_by(InferenceRequest.task)
            .order_by(InferenceRequest.task)
        )
    ).all()

    # p95 by nearest rank: sort the last hour's latencies and take the value 95% of
    # the way up. (app/db/analytics.sql shows Postgres's percentile_cont version.)
    last_hour = (
        mine,
        InferenceRequest.created_at >= now - timedelta(hours=1),
        InferenceRequest.latency_ms.is_not(None),
    )
    n = await session.scalar(select(func.count()).where(*last_hour))
    p95 = None
    if n:
        p95 = await session.scalar(
            select(InferenceRequest.latency_ms)
            .where(*last_hour)
            .order_by(InferenceRequest.latency_ms)
            .offset(math.ceil(0.95 * n) - 1)
            .limit(1)
        )

    return UsageStats(
        total_requests=total,
        requests_last_24h=last_24h or 0,
        cache_hit_rate=round(hits / total, 3) if total else 0.0,
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency is not None else None,
        p95_latency_ms_last_hour=p95,
        by_task=[TaskStats(task=t, requests=c) for t, c in by_task],
    )
