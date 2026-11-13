import io

import pytest
from fastapi import HTTPException, UploadFile

from app.ml.images import read_upload
from tests.conftest import make_image


def upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="x")


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
async def test_accepts_allowed_formats(fmt):
    decoded = await read_upload(upload(make_image(fmt)), max_bytes=1_000_000)
    assert decoded.image.size == (32, 32)
    assert decoded.image.mode == "RGB"


async def test_rejects_gif_with_415():
    with pytest.raises(HTTPException) as exc:
        await read_upload(upload(make_image("GIF")), max_bytes=1_000_000)
    assert exc.value.status_code == 415


async def test_rejects_garbage_with_415():
    with pytest.raises(HTTPException) as exc:
        await read_upload(upload(b"not an image at all"), max_bytes=1_000_000)
    assert exc.value.status_code == 415


async def test_rejects_too_large_with_413():
    with pytest.raises(HTTPException) as exc:
        await read_upload(upload(make_image("PNG")), max_bytes=10)
    assert exc.value.status_code == 413


async def test_rejects_empty_with_400():
    with pytest.raises(HTTPException) as exc:
        await read_upload(upload(b""), max_bytes=10)
    assert exc.value.status_code == 400
