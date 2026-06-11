"""
Definition-of-Done tests for phase 03.

These use mocked Ollama responses to verify the full extraction path for the three
required scenarios: real order, shipping notice, promo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.base import CleanedMessage
from app.extraction.ollama_extractor import OllamaExtractor
from app.schemas import ExtractionResult


def _make_msg(
    subject: str,
    body_text: str,
    vendor_domain: str = "zara.com",
    image_srcs: list[str] | None = None,
) -> CleanedMessage:
    return CleanedMessage(
        message_id="dod-test",
        from_addr=f"noreply@{vendor_domain}",
        vendor_domain=vendor_domain,
        subject=subject,
        date=datetime(2024, 3, 10, tzinfo=timezone.utc),
        body_text=body_text,
        image_srcs=image_srcs or [],
    )


def _extractor(ollama_response: dict) -> OllamaExtractor:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(ollama_response)}}
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post.return_value = resp
    return OllamaExtractor(client=client)


@pytest.mark.asyncio
async def test_dod_real_order_returns_structured_items():
    msg = _make_msg(
        subject="Order Confirmation #ZR-20240310",
        body_text="Thank you for your order. Zara Slim Fit Jeans, size 32, €49.99.",
        image_srcs=["https://zara.com/img/jeans.jpg"],
    )
    ollama_resp = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Zara",
        "merchant_order_id": "ZR-20240310",
        "purchase_date": "2024-03-10T00:00:00",
        "currency": "EUR",
        "total_price": 49.99,
        "items": [
            {
                "item_name": "Slim Fit Jeans",
                "brand": "Zara",
                "size": "32",
                "price": 49.99,
                "image_url": "https://zara.com/img/jeans.jpg",
            }
        ],
        "confidence": 0.92,
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert len(result.items) == 1
    assert result.items[0].item_name == "Slim Fit Jeans"
    assert result.items[0].size == "32"
    assert result.items[0].image_url == "https://zara.com/img/jeans.jpg"
    assert result.merchant_order_id == "ZR-20240310"
    assert result.vendor_domain == "zara.com"
    # Pydantic validation passed (result is an ExtractionResult instance)
    assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_dod_shipping_notice_no_items():
    msg = _make_msg(
        subject="Your Zara order is on its way!",
        body_text="Your order #ZR-20240310 has been dispatched. Expected delivery: March 13.",
    )
    ollama_resp = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Zara",
        "merchant_order_id": "ZR-20240310",
        "purchase_date": None,
        "items": [],
        "confidence": 0.7,
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert result.merchant_order_id == "ZR-20240310"
    assert result.items == []
    assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_dod_promo_returns_invalid():
    msg = _make_msg(
        subject="New collection just dropped — up to 50% off",
        body_text="Shop now. Sale ends midnight. New arrivals in stock.",
    )
    ollama_resp = {
        "is_valid_apparel_purchase": False,
        "items": [],
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is False
    assert result.items == []
    assert isinstance(result, ExtractionResult)
