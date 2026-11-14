"""Per-user rate limiting in Redis.

Two algorithms, picked with RATE_LIMIT_ALGORITHM:

- fixed_window: INCR a counter named after the current minute. Simple, but a user
  can send `limit` requests at 12:00:59 and `limit` more at 12:01:00: double the
  rate across the boundary.
- token_bucket: each user has a bucket of `limit` tokens refilling continuously at
  limit/60 per second; a request spends one. Smooth, and allows short bursts up to
  the bucket size. Read-refill-spend must be atomic or two concurrent requests could
  both spend the last token, so it runs as a Lua script: Redis executes a script
  start to finish with no other command in between.

Redis is shared by every API process, so limits hold across all of them.
"""

import math
import time
from dataclasses import dataclass

import structlog
from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.auth import get_current_user
from app.db.models import User

log = structlog.get_logger()

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_s = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

-- Refill for the time since the last request, never above capacity.
tokens = math.min(capacity, tokens + math.max(0, now - ts) * refill_per_s)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = (1 - tokens) / refill_per_s
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
-- A full bucket is the same as no key, so let idle users' keys disappear.
redis.call('EXPIRE', key, math.ceil(capacity / refill_per_s) + 1)
-- Lua numbers become integers on the way out; send fractions as strings.
return {allowed, tostring(retry_after)}
"""


@dataclass
class Decision:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter:
    def __init__(self, redis: Redis, algorithm: str):
        self.redis = redis
        self.algorithm = algorithm
        self._token_bucket = redis.register_script(TOKEN_BUCKET_LUA)

    async def fixed_window(self, user_id: int, limit: int, now: float) -> Decision:
        window = int(now // 60)
        key = f"rl:{user_id}:{window}"
        async with self.redis.pipeline(transaction=True) as pipe:
            count, _ = await pipe.incr(key).expire(key, 60).execute()
        if count > limit:
            return Decision(False, retry_after_s=60 - int(now % 60))
        return Decision(True)

    async def token_bucket(self, user_id: int, limit: int, now: float) -> Decision:
        allowed, retry_after = await self._token_bucket(
            keys=[f"tb:{user_id}"], args=[limit, limit / 60, now]
        )
        if int(allowed) == 1:
            return Decision(True)
        return Decision(False, retry_after_s=max(1, math.ceil(float(retry_after))))

    async def check(self, user_id: int, limit: int, now: float | None = None) -> Decision:
        """Fails open: if Redis is down, allow the request rather than block everyone."""
        now = time.time() if now is None else now
        try:
            if self.algorithm == "fixed_window":
                return await self.fixed_window(user_id, limit, now)
            return await self.token_bucket(user_id, limit, now)
        except RedisError as exc:
            log.warning("rate_limit_unavailable", error=str(exc))
            return Decision(True)


async def rate_limited_user(request: Request, user: User = Depends(get_current_user)) -> User:
    """Dependency: authenticate, then spend one unit of the user's rate limit."""
    settings = request.app.state.settings
    limits = {"free": settings.rate_limit_free_per_min, "pro": settings.rate_limit_pro_per_min}
    limit = limits.get(user.plan, settings.rate_limit_free_per_min)
    decision = await request.app.state.rate_limiter.check(user.id, limit)
    if not decision.allowed:
        raise HTTPException(
            429,
            f"{limit} requests per minute exceeded",
            headers={"Retry-After": str(decision.retry_after_s)},
        )
    return user
