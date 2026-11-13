from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Task(StrEnum):
    caption = "caption"
    detailed_caption = "detailed_caption"
    ocr = "ocr"


class InferenceResult(BaseModel):
    text: str


class InferenceResponse(BaseModel):
    request_id: int
    task: Task
    result: InferenceResult
    cache_hit: bool
    batch_size: int
    latency_ms: int


class RequestRecord(BaseModel):
    """One past inference, as stored in inference_requests."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    image_id: int
    task: Task
    status: str
    cache_hit: bool
    batch_size: int | None
    latency_ms: int | None
    result: dict | None
    error: str | None
    created_at: datetime


class RequestPage(BaseModel):
    items: list[RequestRecord]
    # Pass this back as ?cursor= to get the next page; null means no more pages.
    next_cursor: int | None
