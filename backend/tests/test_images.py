from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from PIL import Image

from app.ingestion.images import (
    _download_image,
    _image_ext_from_bytes,
    content_hash,
    download_order_images,
    is_junk_url,
    is_tiny_image,
)


def _make_png(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# --- is_junk_url ---


def test_junk_data_uri():
    assert is_junk_url("data:image/png;base64,abc123") is True


def test_junk_cid_ref():
    assert is_junk_url("cid:image001.jpg@01D5ABC") is True


def test_junk_pixel_filename():
    assert is_junk_url("https://example.com/pixel.gif") is True


def test_junk_tracking_open():
    assert is_junk_url("https://track.example.com/open.aspx?id=123") is True


def test_junk_spacer():
    assert is_junk_url("https://cdn.example.com/spacer.png") is True


def test_junk_1x1():
    assert is_junk_url("https://img.example.com/1x1.gif") is True


def test_junk_beacon():
    assert is_junk_url("https://mail.example.com/beacon?u=abc") is True


def test_not_junk_normal_product_url():
    assert is_junk_url("https://cdn.zara.com/img/products/12345.jpg") is False


def test_not_junk_https_with_query():
    assert is_junk_url("https://example.com/images/shoe.jpg?w=800") is False


# --- _image_ext_from_bytes ---


def test_ext_jpeg():
    content = _make_jpeg(10, 10)
    assert _image_ext_from_bytes(content) == "jpg"


def test_ext_png():
    content = _make_png(10, 10)
    assert _image_ext_from_bytes(content) == "png"


def test_ext_unknown():
    assert _image_ext_from_bytes(b"not an image at all") is None


# --- is_tiny_image ---


def test_not_tiny_200x200():
    assert is_tiny_image(_make_png(200, 200), min_dimension=100) is False


def test_tiny_1x1():
    assert is_tiny_image(_make_png(1, 1), min_dimension=100) is True


def test_tiny_width_only():
    assert is_tiny_image(_make_png(50, 200), min_dimension=100) is True


def test_tiny_height_only():
    assert is_tiny_image(_make_png(200, 50), min_dimension=100) is True


def test_tiny_on_garbage_bytes():
    assert is_tiny_image(b"garbage", min_dimension=100) is True


def test_exactly_at_boundary_is_not_tiny():
    assert is_tiny_image(_make_png(100, 100), min_dimension=100) is False


# --- content_hash ---


def test_content_hash_is_deterministic():
    b = b"hello world"
    assert content_hash(b) == content_hash(b)


def test_content_hash_differs_for_different_content():
    assert content_hash(b"aaa") != content_hash(b"bbb")


def test_content_hash_is_64_hex_chars():
    h = content_hash(b"test")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# --- _download_image ---


@pytest.mark.asyncio
async def test_download_image_success():
    jpeg_bytes = _make_jpeg(200, 200)
    mock_resp = MagicMock()
    mock_resp.content = jpeg_bytes
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is not None
    content, ct = result
    assert content == jpeg_bytes
    assert "jpeg" in ct
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_download_image_sends_user_agent_and_referer():
    mock_resp = MagicMock()
    mock_resp.content = _make_jpeg(200, 200)
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    await _download_image("https://example.com/shoe.jpg", "example.com", mock_client)

    call_kwargs = mock_client.get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs.args[1]
    assert "User-Agent" in headers
    assert headers["Referer"] == "https://example.com/"


@pytest.mark.asyncio
async def test_download_image_retries_once_on_failure():
    jpeg_bytes = _make_jpeg(200, 200)

    mock_fail = MagicMock()
    mock_fail.raise_for_status.side_effect = Exception("HTTP 500")

    mock_ok = MagicMock()
    mock_ok.content = jpeg_bytes
    mock_ok.headers = {"content-type": "image/jpeg"}
    mock_ok.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [mock_fail, mock_ok]

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is not None
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_download_image_returns_none_after_two_failures():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is None
    assert mock_client.get.call_count == 2


# --- download_order_images ---


def _mock_item(item_id: str) -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.image_path = None
    return item


def _mock_client_with_content(content: bytes, ct: str = "image/png") -> AsyncMock:
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.headers = {"content-type": ct}
    mock_resp.raise_for_status = MagicMock()
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = mock_resp
    return client


@pytest.mark.asyncio
async def test_download_order_images_saves_image(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item = _mock_item("item-abc")

    await download_order_images(
        items=[item],
        image_urls=["https://example.com/shoe.png"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    expected = tmp_path / "example.com" / "order-xyz" / "item-abc.png"
    assert expected.exists()
    assert expected.read_bytes() == png_bytes
    assert item.image_path == str(expected)


@pytest.mark.asyncio
async def test_download_order_images_skips_junk_url(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    item = _mock_item("item-1")

    await download_order_images(
        items=[item],
        image_urls=["data:image/png;base64,abc"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    client.get.assert_not_called()
    assert item.image_path is None


@pytest.mark.asyncio
async def test_download_order_images_skips_none_url(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    item = _mock_item("item-1")

    await download_order_images(
        items=[item],
        image_urls=[None],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    client.get.assert_not_called()
    assert item.image_path is None


@pytest.mark.asyncio
async def test_download_order_images_skips_tiny_image(tmp_path):
    tiny_bytes = _make_png(1, 1)
    client = _mock_client_with_content(tiny_bytes)
    item = _mock_item("item-1")

    await download_order_images(
        items=[item],
        image_urls=["https://example.com/logo.png"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item.image_path is None
    assert not any(tmp_path.rglob("*.png"))


@pytest.mark.asyncio
async def test_download_order_images_dedup_identical_bytes(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item1 = _mock_item("item-1")
    item2 = _mock_item("item-2")

    await download_order_images(
        items=[item1, item2],
        image_urls=[
            "https://example.com/img.png",
            "https://example.com/img.png",
        ],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item1.image_path is not None
    assert item2.image_path == item1.image_path
    saved = list(tmp_path.rglob("*.png"))
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_download_order_images_continues_on_download_failure(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = Exception("network error")
    item = _mock_item("item-1")

    await download_order_images(
        items=[item],
        image_urls=["https://example.com/shoe.jpg"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item.image_path is None
