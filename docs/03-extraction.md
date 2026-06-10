# 03 — Extraction

Replaces brittle HTML parsing with semantic extraction by a **local** model.

## `Extractor` interface (`extraction/base.py`)

```python
@dataclass
class CleanedMessage:
    message_id: str
    from_addr: str
    vendor_domain: str       # derived from from_addr
    subject: str
    date: datetime
    body_text: str           # html stripped to text, truncated
    image_srcs: list[str]

class Extractor(Protocol):
    async def extract(self, msg: CleanedMessage) -> ExtractionResult: ...
```

## Output schema (`schemas.py`, Pydantic v2)

```python
class ExtractedItem(BaseModel):
    item_name: str
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    price: float | None = None
    image_url: str | None = None   # must be one of msg.image_srcs

class ExtractionResult(BaseModel):
    is_valid_apparel_purchase: bool   # FINAL GATE — false ⇒ store nothing
    is_refund_or_cancellation: bool = False
    vendor_name: str | None = None
    merchant_order_id: str | None = None
    purchase_date: datetime | None = None
    currency: str | None = None
    total_price: float | None = None
    items: list[ExtractedItem] = []
    confidence: float | None = None   # 0..1
```

## Ollama implementation (`extraction/ollama_extractor.py`)

- Endpoint: `POST http://localhost:11434/api/chat`, model `qwen2.5:7b`,
  `stream=false`, `options={"temperature": 0}`.
- **Structured output:** pass `format=ExtractionResult.model_json_schema()` so Ollama
  constrains output to the schema. Still validate the result — constrained ≠ guaranteed.
- Keep the schema flat and small; 7B models degrade with deep/nested schemas.

### Prompt (`extraction/prompt.py`)
System prompt, in English, rules:
- You extract data **only** about clothing/footwear/accessories the user **purchased**
  in this email.
- Set `is_valid_apparel_purchase=false` for promos, newsletters, "back in stock",
  wishlist, shipping-only notices with no items, or non-apparel orders.
- Extract **only what is literally present**. Missing field → `null`, never guess.
- `image_url` must be copied verbatim from the provided candidate image list, or null.
- Per-item `brand` may differ from `vendor_name` on marketplaces (ASOS, Farfetch).
- If it's a refund/cancellation, set `is_refund_or_cancellation=true` and still return
  the order id + affected items.

User message = vendor_domain, subject, date, body_text (truncated to model context),
and the candidate `image_srcs` as a numbered list.

### Validation + retry
```python
raw = await call_ollama(...)
try:
    result = ExtractionResult.model_validate_json(raw)
except ValidationError:
    raw = await call_ollama(..., extra="Return ONLY valid JSON matching the schema.")
    result = ExtractionResult.model_validate_json(raw)  # may raise → caller marks error
```
On final failure, caller records `processed_messages.result = 'error'` and continues.

## Notes for a local 7B model
- **Context limit:** truncate `body_text` (e.g. ~6k chars) — strip nav/footer boilerplate
  first. Promo emails are long; real receipts are short.
- **Multilingual:** mailboxes here include Hebrew. qwen2.5 handles it but is weaker; keep
  the schema/instructions in English and let it read non-English bodies. Low confidence
  or null-heavy results are expected — the `Extractor` interface exists precisely so a
  cloud model can be swapped in for tricky vendors later.
- **Determinism:** `temperature=0`, no sampling, for reproducible runs.

## Definition of done
Feed 3 saved sample emails (a real order, a shipping notice, a promo) through the
extractor: order returns full structured items, shipping returns valid-but-no-items or
matches the order, promo returns `is_valid_apparel_purchase=false`. All outputs pass
Pydantic validation.
