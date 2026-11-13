import fakeredis
import pytest

from app.cache.results import cache_key
from app.core.rate_limit import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(fakeredis.FakeAsyncRedis(decode_responses=True), "token_bucket")


async def test_token_bucket_allows_burst_then_blocks(limiter):
    now = 1_000_000.0
    for _ in range(10):
        assert (await limiter.token_bucket(1, limit=10, now=now)).allowed
    decision = await limiter.token_bucket(1, limit=10, now=now)
    assert not decision.allowed
    assert decision.retry_after_s == 6  # 10/min refills one token every 6 s


async def test_token_bucket_refills_over_time(limiter):
    now = 1_000_000.0
    for _ in range(10):
        await limiter.token_bucket(1, limit=10, now=now)
    assert not (await limiter.token_bucket(1, limit=10, now=now + 1)).allowed
    assert (await limiter.token_bucket(1, limit=10, now=now + 7)).allowed
    assert not (await limiter.token_bucket(1, limit=10, now=now + 7)).allowed


async def test_token_bucket_never_exceeds_capacity(limiter):
    now = 1_000_000.0
    await limiter.token_bucket(1, limit=3, now=now)
    later = now + 3600  # idle for an hour
    results = [(await limiter.token_bucket(1, limit=3, now=later)).allowed for _ in range(4)]
    assert results == [True, True, True, False]


async def test_users_have_separate_buckets(limiter):
    now = 1_000_000.0
    assert (await limiter.token_bucket(1, limit=1, now=now)).allowed
    assert not (await limiter.token_bucket(1, limit=1, now=now)).allowed
    assert (await limiter.token_bucket(2, limit=1, now=now)).allowed


async def test_fixed_window_resets_each_minute(limiter):
    start = 60 * 1000.0  # exactly on a minute boundary
    for _ in range(3):
        assert (await limiter.fixed_window(1, limit=3, now=start)).allowed
    blocked = await limiter.fixed_window(1, limit=3, now=start + 45)
    assert not blocked.allowed
    assert blocked.retry_after_s == 15
    assert (await limiter.fixed_window(1, limit=3, now=start + 60)).allowed


async def test_check_fails_open_when_redis_down():
    from redis.exceptions import ConnectionError

    class DeadRedis(fakeredis.FakeAsyncRedis):
        async def evalsha(self, *a, **k):
            raise ConnectionError("down")

        async def eval(self, *a, **k):
            raise ConnectionError("down")

    limiter = RateLimiter(DeadRedis(), "token_bucket")
    assert (await limiter.check(1, limit=1)).allowed


def test_cache_key_format():
    assert cache_key("ocr", "v2", "abc") == "infer:ocr:v2:abc"
