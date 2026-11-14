"""Real-model smoke test. Local only: uv sync --extra ml && uv run pytest -m gpu"""

import pytest
from PIL import Image, ImageDraw

from app.config import Settings
from app.schemas.inference import Task

pytestmark = pytest.mark.gpu


@pytest.fixture(scope="module")
def model():
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("no CUDA GPU")
    from app.ml.model import Florence2Model

    s = Settings(_env_file=None)
    return Florence2Model.load(s.model_id, "cuda", s.max_new_tokens)


def sample_image() -> Image.Image:
    img = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(img).text((40, 80), "HELLO VISIONSERVE", fill="black")
    return img


def test_caption_is_not_empty(model):
    [text] = model.predict_batch([sample_image()], Task.caption)
    assert text


def test_batch_returns_one_result_per_image(model):
    texts = model.predict_batch([sample_image()] * 4, Task.ocr)
    assert len(texts) == 4
    assert all(texts)


def test_model_fits_in_6gb(model):
    import torch

    assert torch.cuda.max_memory_allocated() < 5 * 1024**3
