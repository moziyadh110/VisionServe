"""Locust load test: 70% new images (cache misses), 30% repeated images (cache hits).

Run headless (see loadtest/run_experiments.sh), or with the web UI:
    ADMIN_TOKEN=change-me uv run --group loadtest locust -f loadtest/locustfile.py \
        --host http://localhost:8000

Env vars:
    ADMIN_TOKEN       token for POST /v1/users (must match the server)
    LOADTEST_IMAGES   folder of real .jpg/.png/.webp photos (recommended: captions of
                      real photos take as long as production traffic; synthetic
                      images give shorter outputs and flattering numbers)
    LOADTEST_TASK     caption | detailed_caption | ocr (default caption)
    NEW_IMAGE_RATIO   share of requests with a never-seen image (default 0.7)

The server must allow enough requests per minute, e.g. RATE_LIMIT_FREE_PER_MIN=100000,
or the test measures the rate limiter instead of the GPU.
"""

import io
import os
import random
import uuid
from pathlib import Path

import requests
from locust import HttpUser, between, events, task
from PIL import Image, ImageDraw

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me")
TASK = os.environ.get("LOADTEST_TASK", "caption")
NEW_IMAGE_RATIO = float(os.environ.get("NEW_IMAGE_RATIO", "0.7"))
REPEATED_POOL_SIZE = 20

BASE_IMAGES: list[Image.Image] = []
REPEATED: list[bytes] = []


def _synthetic(seed: int) -> Image.Image:
    """Shapes plus text, so captioning and OCR both have something to work with."""
    rng = random.Random(seed)
    img = Image.new("RGB", (640, 480), tuple(rng.randint(0, 255) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(6):
        x, y = rng.randint(0, 560), rng.randint(0, 400)
        box = (x, y, x + rng.randint(40, 200), y + rng.randint(40, 200))
        draw.ellipse(box, fill=tuple(rng.randint(0, 255) for _ in range(3)))
    draw.text((20, 20), f"VisionServe test {seed}", fill=(0, 0, 0))
    return img


def _encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _new_image() -> bytes:
    """A real-looking image with one random pixel changed, so its SHA-256 is new.

    The content (and so the model's work) is the same as the base photo, but the
    cache has never seen these bytes: a guaranteed miss.
    """
    img = random.choice(BASE_IMAGES).copy()
    img.putpixel(
        (random.randrange(img.width), random.randrange(img.height)),
        tuple(random.randint(0, 255) for _ in range(3)),
    )
    return _encode(img)


@events.init.add_listener
def _load_images(environment, **kwargs):
    folder = os.environ.get("LOADTEST_IMAGES")
    if folder:
        for path in sorted(Path(folder).iterdir()):
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                img = Image.open(path).convert("RGB")
                img.thumbnail((1024, 1024))
                BASE_IMAGES.append(img)
    if not BASE_IMAGES:
        BASE_IMAGES.extend(_synthetic(i) for i in range(10))
    REPEATED.extend(_new_image() for _ in range(REPEATED_POOL_SIZE))


class ApiUser(HttpUser):
    # Closed-loop: each simulated user sends its next request right after the last.
    wait_time = between(0, 0.05)

    def on_start(self):
        email = f"load-{uuid.uuid4().hex[:12]}@example.com"
        # Plain `requests`, not self.client, so signups stay out of Locust's stats
        # and the "Aggregated" percentiles describe inference requests only.
        resp = requests.post(
            f"{self.host}/v1/users",
            json={"email": email},
            headers={"X-Admin-Token": ADMIN_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        self.headers = {"X-API-Key": resp.json()["api_key"]}

    @task
    def infer(self):
        if random.random() < NEW_IMAGE_RATIO:
            data, name = _new_image(), f"/v1/infer/{TASK} [new]"
        else:
            data, name = random.choice(REPEATED), f"/v1/infer/{TASK} [repeat]"
        self.client.post(
            f"/v1/infer/{TASK}",
            files={"file": ("img.jpg", data, "image/jpeg")},
            headers=self.headers,
            name=name,
        )
