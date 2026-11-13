import asyncio
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.models import InferenceRequest, User
from app.db.queries import get_or_create_image
from app.db.session import get_session
from app.ml.images import read_upload
from app.schemas.inference import InferenceResponse, InferenceResult, Task

router = APIRouter(prefix="/v1", tags=["inference"])


@router.post("/infer/{task}", response_model=InferenceResponse)
async def infer(
    task: Task,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InferenceResponse:
    state = request.app.state
    if state.model is None:
        raise HTTPException(503, "Model is still loading")

    # Copy plain values now: a rollback inside get_or_create_image expires ORM objects,
    # and touching an expired attribute in async code would try a hidden DB call.
    user_id = user.id
    upload = await read_upload(file, state.settings.max_upload_bytes)
    image = await get_or_create_image(session, user_id, upload)
    image_id = image.id

    # model.predict blocks for tens of milliseconds. Calling it directly here would
    # freeze the event loop, and every other request (even /healthz) would wait.
    # Instead it runs on the single GPU thread while this coroutine awaits.
    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    try:
        text = await loop.run_in_executor(
            state.gpu_executor, state.model.predict, upload.image, task
        )
    except Exception as exc:
        session.add(
            InferenceRequest(
                user_id=user_id,
                image_id=image_id,
                task=task.value,
                status="error",
                latency_ms=int((time.perf_counter() - start) * 1000),
                error=str(exc)[:500],
            )
        )
        await session.commit()
        raise HTTPException(500, "Inference failed") from exc
    latency_ms = int((time.perf_counter() - start) * 1000)

    row = InferenceRequest(
        user_id=user_id,
        image_id=image_id,
        task=task.value,
        status="ok",
        cache_hit=False,
        batch_size=1,
        latency_ms=latency_ms,
        result={"text": text},
    )
    session.add(row)
    await session.commit()

    return InferenceResponse(
        request_id=row.id,
        task=task,
        result=InferenceResult(text=text),
        cache_hit=False,
        batch_size=1,
        latency_ms=latency_ms,
    )
