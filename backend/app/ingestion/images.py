from __future__ import annotations

import hashlib
import io
import logging
import re

import httpx
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


async def _download_image(
    url: str,
    vendor_domain: str,
    client: httpx.AsyncClient,
    timeout: float = 10.0,
) -> tuple[bytes, str] | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; digital-closet/1.0)",
        "Referer": f"https://{vendor_domain}/",
    }
    for attempt in range(2):
        try:
            resp = await client.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "")
        except Exception as exc:
            if attempt == 0:
                logger.debug("image:download_retry url=%s", url)
            else:
                logger.warning("image:download_failed url=%s exc=%s", url, exc)
    return None
