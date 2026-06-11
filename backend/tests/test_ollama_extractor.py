from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.extraction.base import CleanedMessage
from app.extraction.ollama_extractor import OllamaExtractor


@pytest.fixture
def msg() -> CleanedMessage:
    return CleanedMessage(
        message_id="msg1",
        from_addr="orders@nike.com",
        vendor_domain="nike.com",
        subject="Your Nike order #ORD-999",
        date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        body_text="Thank you for your order. Air Max 90, size 10, $120.",
        image_srcs=["https://example.com/airmax.jpg"],
    )


def _mock_client(content: str) -> AsyncMock:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": content}}
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post.return_value = resp
    return client


def _valid_json(overrides: dict | None = None) -> str:
    data = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Nike",
        "merchant_order_id": "ORD-999",
        "purchase_date": "2024-01-15T00:00:00",
        "currency": "USD",
        "total_price": 120.0,
        "items": [
            {
                "item_name": "Air Max 90",
                "size": "10",
                "price": 120.0,
                "image_url": "https://example.com/airmax.jpg",
            }
        ],
        "confidence": 0.95,
    }
    if overrides:
        data.update(overrides)
    return json.dumps(data)


@pytest.mark.asyncio
async def test_extract_valid_purchase(msg):
    client = _mock_client(_valid_json())
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert result.vendor_name == "Nike"
    assert result.vendor_domain == "nike.com"
    assert len(result.items) == 1
    assert result.items[0].item_name == "Air Max 90"
    assert result.items[0].image_url == "https://example.com/airmax.jpg"


@pytest.mark.asyncio
async def test_vendor_domain_set_from_msg_when_missing(msg):
    json_str = _valid_json({"vendor_domain": None})
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.vendor_domain == "nike.com"


@pytest.mark.asyncio
async def test_image_url_not_in_srcs_is_nulled(msg):
    json_str = _valid_json(
        {
            "items": [
                {"item_name": "Air Max 90", "image_url": "https://evil.com/fake.jpg"}
            ]
        }
    )
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.items[0].image_url is None


@pytest.mark.asyncio
async def test_promo_returns_invalid(msg):
    json_str = json.dumps({"is_valid_apparel_purchase": False, "items": []})
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.is_valid_apparel_purchase is False


@pytest.mark.asyncio
async def test_retry_on_first_parse_failure(msg):
    bad_json = "not valid json {"
    good_json = json.dumps({"is_valid_apparel_purchase": False, "items": []})

    bad_resp = MagicMock()
    bad_resp.json.return_value = {"message": {"content": bad_json}}
    bad_resp.raise_for_status = MagicMock()

    good_resp = MagicMock()
    good_resp.json.return_value = {"message": {"content": good_json}}
    good_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post.side_effect = [bad_resp, good_resp]

    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)

    assert result.is_valid_apparel_purchase is False
    assert client.post.call_count == 2


@pytest.mark.asyncio
async def test_raises_on_double_parse_failure(msg):
    bad_resp = MagicMock()
    bad_resp.json.return_value = {"message": {"content": "{"}}
    bad_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post.return_value = bad_resp

    extractor = OllamaExtractor(client=client)
    with pytest.raises(ValidationError):
        await extractor.extract(msg)


@pytest.mark.asyncio
async def test_ollama_called_with_correct_model_and_format(msg):
    client = _mock_client(_valid_json())
    extractor = OllamaExtractor(
        base_url="http://localhost:11434", model="qwen2.5:7b", client=client
    )
    await extractor.extract(msg)

    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert "format" in payload
