import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ml.batcher import Batcher, QueueFull
from app.schemas.inference import Task


class Recorder:
    def __init__(self, delay_s: float = 0.0, fail: bool = False):
        self.batches: list[tuple[Task, int]] = []
        self.delay_s = delay_s
        self.fail = fail

    def __call__(self, images, task):
        self.batches.append((task, len(images)))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("boom")
        return [f"{task.value}-{img}" for img in images]


@pytest.fixture
def executor():
    with ThreadPoolExecutor(max_workers=1) as ex:
        yield ex


@pytest.fixture
async def make_batcher(executor):
    tasks = []

    def make(predict, max_batch=8, max_wait_ms=20, max_queue=64):
        b = Batcher(predict, executor, max_batch, max_wait_ms, max_queue)
        tasks.append(asyncio.create_task(b.run()))
        return b

    yield make
    for t in tasks:
        t.cancel()


async def test_single_request(make_batcher):
    predict = Recorder()
    b = make_batcher(predict)
    result = await b.submit("img0", Task.caption)
    assert result.text == "caption-img0"
    assert result.batch_size == 1


async def test_concurrent_requests_are_batched(make_batcher):
    predict = Recorder()
    b = make_batcher(predict, max_batch=8, max_wait_ms=50)
    results = await asyncio.gather(*(b.submit(f"img{i}", Task.caption) for i in range(5)))
    assert predict.batches == [(Task.caption, 5)]
    assert [r.text for r in results] == [f"caption-img{i}" for i in range(5)]


async def test_respects_max_batch_size(make_batcher):
    predict = Recorder()
    b = make_batcher(predict, max_batch=4, max_wait_ms=50)
    await asyncio.gather(*(b.submit(f"img{i}", Task.caption) for i in range(10)))
    assert [n for _, n in predict.batches] == [4, 4, 2]


async def test_groups_mixed_tasks(make_batcher):
    predict = Recorder()
    b = make_batcher(predict, max_wait_ms=50)
    tasks = [Task.caption, Task.ocr, Task.caption, Task.ocr, Task.caption]
    results = await asyncio.gather(*(b.submit(f"i{n}", t) for n, t in enumerate(tasks)))
    assert sorted(predict.batches) == [(Task.caption, 3), (Task.ocr, 2)]
    assert results[1].text == "ocr-i1"


async def test_max_wait_bounds_latency(make_batcher):
    """A lone request shouldn't wait much longer than max_wait for companions."""
    b = make_batcher(Recorder(), max_batch=8, max_wait_ms=30)
    start = time.perf_counter()
    await b.submit("img", Task.caption)
    assert time.perf_counter() - start < 0.5


async def test_queue_full_raises(make_batcher):
    b = make_batcher(Recorder(), max_queue=0)
    with pytest.raises(QueueFull):
        await b.submit("img", Task.caption)


async def test_model_error_reaches_every_caller(make_batcher):
    b = make_batcher(Recorder(fail=True), max_wait_ms=50)
    results = await asyncio.gather(
        *(b.submit(f"img{i}", Task.caption) for i in range(3)), return_exceptions=True
    )
    assert all(isinstance(r, RuntimeError) for r in results)


async def test_loop_survives_errors(make_batcher):
    predict = Recorder(fail=True)
    b = make_batcher(predict)
    with pytest.raises(RuntimeError):
        await b.submit("img", Task.caption)
    predict.fail = False
    assert (await b.submit("img", Task.caption)).text == "caption-img"


async def test_cancelled_requests_are_skipped(make_batcher):
    """A caller that timed out shouldn't cost GPU time."""
    predict = Recorder(delay_s=0.2)
    b = make_batcher(predict, max_batch=1, max_wait_ms=0)
    first = asyncio.create_task(b.submit("first", Task.caption))
    await asyncio.sleep(0.05)  # first is now running on the "GPU"
    second = asyncio.create_task(b.submit("second", Task.caption))
    await asyncio.sleep(0)
    second.cancel()
    await first
    await asyncio.sleep(0.05)
    assert predict.batches == [(Task.caption, 1)]
