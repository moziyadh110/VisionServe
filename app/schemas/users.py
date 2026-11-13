from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr


class UserCreated(BaseModel):
    user_id: int
    email: EmailStr
    plan: str
    # Shown exactly once. Only its prefix and hash are stored.
    api_key: str


class KeyRotated(BaseModel):
    api_key: str


class TaskStats(BaseModel):
    task: str
    requests: int


class UsageStats(BaseModel):
    total_requests: int
    requests_last_24h: int
    cache_hit_rate: float
    avg_latency_ms: float | None
    p95_latency_ms_last_hour: int | None
    by_task: list[TaskStats]
