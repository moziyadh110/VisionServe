import hashlib
import io
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@dataclass
class DecodedImage:
    image: Image.Image
    data: bytes
    format: str
    sha256: str

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self.format]


async def read_upload(upload: UploadFile, max_bytes: int) -> DecodedImage:
    """Validate an uploaded image: size first, then its real format.

    Reads max_bytes + 1 so an oversized file is rejected without reading all of it.
    The format comes from the file's bytes (Pillow), not the client's Content-Type
    header, because clients can send any header they like.
    """
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"Image larger than {max_bytes} bytes")
    if not data:
        raise HTTPException(400, "Empty upload")
    try:
        image = Image.open(io.BytesIO(data))
        fmt = image.format
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(415, "Unsupported or corrupt image; use JPEG, PNG or WebP") from exc
    if fmt not in CONTENT_TYPES:
        raise HTTPException(415, f"Unsupported image format {fmt}; use JPEG, PNG or WebP")
    return DecodedImage(
        image=image.convert("RGB"),
        data=data,
        format=fmt,
        sha256=hashlib.sha256(data).hexdigest(),
    )
