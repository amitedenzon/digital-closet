import pytest
from pydantic import ValidationError

from app.schemas import ExtractedItem, ExtractionResult


def test_extracted_item_minimal():
    item = ExtractedItem(item_name="Air Max 90")
    assert item.item_name == "Air Max 90"
    assert item.brand is None
    assert item.quantity == 1
    assert item.image_url is None


def test_extraction_result_valid_purchase():
    result = ExtractionResult.model_validate(
        {
            "is_valid_apparel_purchase": True,
            "vendor_name": "Nike",
            "merchant_order_id": "12345",
            "items": [{"item_name": "Air Max 90", "size": "10", "price": 120.0}],
        }
    )
    assert result.is_valid_apparel_purchase is True
    assert len(result.items) == 1
    assert result.items[0].item_name == "Air Max 90"
    assert result.items[0].size == "10"


def test_extraction_result_promo_no_items():
    result = ExtractionResult.model_validate({"is_valid_apparel_purchase": False})
    assert result.is_valid_apparel_purchase is False
    assert result.items == []
    assert result.is_refund_or_cancellation is False


def test_extraction_result_json_roundtrip():
    original = ExtractionResult.model_validate(
        {
            "is_valid_apparel_purchase": True,
            "vendor_name": "ASOS",
            "total_price": 49.99,
            "items": [{"item_name": "Jeans", "brand": "Levi's", "color": "blue"}],
        }
    )
    json_str = original.model_dump_json()
    loaded = ExtractionResult.model_validate_json(json_str)
    assert loaded.vendor_name == "ASOS"
    assert loaded.items[0].brand == "Levi's"


def test_extraction_result_missing_required_field():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({})


def test_extraction_result_json_schema_is_serializable():
    import json

    schema = ExtractionResult.model_json_schema()
    serialized = json.dumps(schema)
    assert "is_valid_apparel_purchase" in serialized
