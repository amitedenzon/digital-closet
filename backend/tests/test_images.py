from __future__ import annotations

import io

from PIL import Image

from app.ingestion.images import (
    _image_ext_from_bytes,
    content_hash,
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
