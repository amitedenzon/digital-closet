from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from PIL import Image

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

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


async def download_order_images(
    session: "Session",
    items: list,
    image_urls: list[str | None],
    vendor_domain: str,
    order_id: str,
    *,
    store_dir: Path,
    client: httpx.AsyncClient,
    min_dimension: int = 100,
) -> None:
    seen_hashes: dict[str, str] = {}

    for item, url in zip(items, image_urls):
        if not url or is_junk_url(url):
            continue
        try:
            downloaded = await _download_image(url, vendor_domain, client)
            if downloaded is None:
                continue

            content, content_type = downloaded

            ext = _image_ext_from_bytes(content)
            if ext is None:
                if "png" in content_type:
                    ext = "png"
                elif "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpg"
                else:
                    logger.warning(
                        "image:unknown_type item_id=%s url=%s ct=%s",
                        item.id,
                        url,
                        content_type,
                    )
                    continue

            if is_tiny_image(content, min_dimension):
                logger.debug("image:too_small item_id=%s url=%s", item.id, url)
                continue

            h = content_hash(content)
            if h in seen_hashes:
                item.image_path = seen_hashes[h]
                logger.debug("image:dedup item_id=%s path=%s", item.id, item.image_path)
                continue

            dest = store_dir / vendor_domain / order_id / f"{item.id}.{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

            item.image_path = str(dest)
            seen_hashes[h] = item.image_path
            logger.info("image:saved item_id=%s path=%s", item.id, item.image_path)

        except Exception as exc:
            logger.warning("image:error item_id=%s url=%s exc=%s", item.id, url, exc)
