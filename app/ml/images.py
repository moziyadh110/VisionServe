import io
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass
class DecodedImage:
    image: Image.Image
    data: bytes


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
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(415, f"Unsupported image format {fmt}; use JPEG, PNG or WebP")
    return DecodedImage(image=image.convert("RGB"), data=data)
