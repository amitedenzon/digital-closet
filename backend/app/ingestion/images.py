from __future__ import annotations

import hashlib
import io
import logging
import re

from PIL import Image

logger = logging.getLogger(__name__)

_TRACKING_NAMES = re.compile(r"pixel|open|track|spacer|1x1|beacon", re.IGNORECASE)
_JUNK_PREFIXES = ("data:", "cid:")
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"


def is_junk_url(url: str) -> bool:
    for prefix in _JUNK_PREFIXES:
        if url.startswith(prefix):
            return True
    filename = url.split("?")[0].split("/")[-1]
    return bool(_TRACKING_NAMES.search(filename))


def _image_ext_from_bytes(content: bytes) -> str | None:
    if content[:3] == _MAGIC_JPEG:
        return "jpg"
    if content[:8] == _MAGIC_PNG:
        return "png"
    return None


def is_tiny_image(content: bytes, min_dimension: int = 100) -> bool:
    try:
        img = Image.open(io.BytesIO(content))
        w, h = img.size
        return w < min_dimension or h < min_dimension
    except Exception:
        return True


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
