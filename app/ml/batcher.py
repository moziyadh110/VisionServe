"""Dynamic batching.

Requests arrive one at a time, but the GPU is far more efficient on a batch. Each
request puts (image, task, future) on a queue and awaits its future. One background
loop takes the first waiting item, then keeps collecting until it has max_batch
items or max_wait has passed since that first item, whichever comes first. It runs
one forward pass per task and resolves every future.

The tradeoff: a request may wait up to max_wait for companions (worse latency when
traffic is light) in exchange for many more images per second under load.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass

import structlog
from PIL import Image

from app.core.metrics import BATCH_SIZE
from app.schemas.inference import Task

log = structlog.get_logger()

PredictBatch = Callable[[list[Image.Image], Task], list[str]]


class QueueFull(Exception):
    """Raised instead of queueing when we're already too far behind (backpressure)."""


@dataclass
class BatchResult:
    text: str
    batch_size: int


@dataclass
class _Item:
    image: Image.Image
    task: Task
    future: asyncio.Future


class Batcher:
    def __init__(
        self,
        predict_batch: PredictBatch,
        executor: Executor,
        max_batch: int,
        max_wait_ms: float,
        max_queue: int,
    ):
        self.predict_batch = predict_batch
        self.executor = executor
        self.max_batch = max_batch
        self.max_wait_s = max_wait_ms / 1000
        self.max_queue = max_queue
        self.queue: asyncio.Queue[_Item] = asyncio.Queue()

    @property
    def depth(self) -> int:
        return self.queue.qsize()

    async def submit(self, image: Image.Image, task: Task) -> BatchResult:
        """Queue one image and wait for its result.

        If the queue is already full we fail fast with QueueFull (-> 503). Waiting
        would only make every queued request slower and eventually time out anyway;
        rejecting lets the client retry or go elsewhere.
        """
        if self.queue.qsize() >= self.max_queue:
            raise QueueFull()
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait(_Item(image, task, future))
        return await future

    async def _collect(self) -> list[_Item]:
        """Wait for one item, then gather more until the batch is full or max_wait passes."""
        loop = asyncio.get_running_loop()
        batch = [await self.queue.get()]
        deadline = loop.time() + self.max_wait_s
        while len(batch) < self.max_batch:
            try:
                batch.append(self.queue.get_nowait())  # take what's already waiting
                continue
            except asyncio.QueueEmpty:
                pass
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self.queue.get(), remaining))
            except TimeoutError:
                break
        return batch

    async def _run_group(self, task: Task, items: list[_Item]) -> None:
        # Skip requests whose caller already gave up (timed out / disconnected).
        items = [i for i in items if not i.future.done()]
        if not items:
            return
        BATCH_SIZE.observe(len(items))
        loop = asyncio.get_running_loop()
        try:
            texts = await loop.run_in_executor(
                self.executor, self.predict_batch, [i.image for i in items], task
            )
        except Exception as exc:
            log.exception("batch_failed", task=task.value, batch_size=len(items))
            for item in items:
                if not item.future.done():
                    item.future.set_exception(exc)
            return
        for item, text in zip(items, texts, strict=True):
            if not item.future.done():
                item.future.set_result(BatchResult(text=text, batch_size=len(items)))

    async def run(self) -> None:
        """Background loop, started once at app startup. Never exits on its own."""
        while True:
            batch = await self._collect()
            # One prompt per forward pass, so split a mixed batch by task.
            groups: dict[Task, list[_Item]] = defaultdict(list)
            for item in batch:
                groups[item.task].append(item)
            for task, items in groups.items():
                await self._run_group(task, items)
