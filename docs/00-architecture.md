# 00 — Architecture

## Goal

Turn purchase emails into a structured, deduplicated, image-backed closet, using a
local LLM, with both a full historical backfill and incremental sync.

## Data flow

```
                 ┌─────────────────────────────────────────────┐
   Gmail API ───▶│  MailProvider (interface)                    │
  (readonly)     │    GmailProvider — only place Gmail is known │
                 └───────────────┬─────────────────────────────┘
                                 │ raw messages (id, headers, body, image srcs)
                                 ▼
                    ┌────────────────────────┐   reject promo/non-apparel
                    │  prefilter (heuristic)  │ ─────────────────────────▶ skip
                    └───────────┬────────────┘   (no LLM cost)
                                │ candidates only
                                ▼
                 ┌─────────────────────────────────────────────┐
   Ollama   ◀───▶│  Extractor (interface)                       │
 qwen2.5:7b      │    OllamaExtractor — structured JSON output  │
                 └───────────────┬─────────────────────────────┘
                                 │ validated Order + Items (or is_valid=false)
                                 ▼
                    ┌────────────────────────┐
                    │  image fetch + store    │  download product images now
                    └───────────┬────────────┘
                                ▼
                    ┌────────────────────────┐
                    │  repo: UPSERT + dedup   │  (vendor_domain, merchant_order_id)
                    │  record processed msg   │  + advance checkpoint cursor
                    └───────────┬────────────┘
                                ▼
                          SQLite (POC)
                                ▲
                    FastAPI  ───┘  ◀── React UI (grid, sync buttons, filters)
```

## The two interfaces (the whole design hinges on these)

### `MailProvider`
Everything provider-specific (Gmail/Outlook/IMAP) hides here. The pipeline only knows
this interface, so adding Outlook later = one new file, zero pipeline changes.

```python
class MailProvider(Protocol):
    async def search(self, *, query: ProviderQuery, cursor: str | None) -> Page:
        """Return a page of lightweight message refs + a next cursor."""
    async def fetch(self, message_id: str) -> RawMessage:
        """Full message: headers, plain text, html, list of image src URLs."""
```

- `ProviderQuery` is a *neutral* description (date range, subject keywords, category,
  sender hints). Each provider translates it to its own dialect (Gmail search string,
  IMAP SEARCH, Graph filter).
- `cursor` is an **opaque, provider-defined string** (Gmail: `internalDate` of last
  processed message or a page token; IMAP: last UID). The pipeline never parses it.

### `Extractor`
```python
class Extractor(Protocol):
    async def extract(self, msg: CleanedMessage) -> ExtractionResult:
        """Return validated structured purchase data (see 03-extraction)."""
```
Swapping `qwen2.5:7b` → Claude/OpenAI later = one new implementation.

## Two operational modes (see 02-ingestion for detail)

- **Initialize (backfill):** walk history from now backwards, **hard stop at a
  configurable year** (default 2023-01-01). Idempotent, resumable.
- **Sync since checkpoint:** start from the stored cursor, process up to `now`, then
  advance the cursor. This is what the "Sync" button calls.

Both modes share one pipeline; they differ only in the `ProviderQuery` date bound and
which cursor they start from.

## Definition of done
Diagram and interfaces above are reflected in `providers/base.py` and
`extraction/base.py` as typed `Protocol`s with docstrings. No implementation yet.
