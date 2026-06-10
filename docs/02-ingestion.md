# 02 — Ingestion

## `MailProvider` interface (`providers/base.py`)

```python
@dataclass
class ProviderQuery:
    after: datetime | None          # inclusive lower bound
    before: datetime | None         # exclusive upper bound
    subject_any: list[str]          # OR-ed subject keywords
    category_purchases: bool        # provider hint if supported
    sender_domains: list[str] | None  # optional allowlist

@dataclass
class MessageRef:
    message_id: str
    internal_date: datetime

@dataclass
class Page:
    refs: list[MessageRef]
    next_cursor: str | None         # None = no more pages

@dataclass
class RawMessage:
    message_id: str
    account: str
    from_addr: str
    subject: str
    date: datetime
    text: str | None
    html: str | None
    image_srcs: list[str]           # extracted <img src> from html

class MailProvider(Protocol):
    async def search(self, query: ProviderQuery, cursor: str | None) -> Page: ...
    async def fetch(self, message_id: str) -> RawMessage: ...
```

## Gmail implementation (`providers/gmail.py`)

- Auth: OAuth desktop flow, scope **`https://www.googleapis.com/auth/gmail.readonly`**.
  `credentials.json` → `token.json` (both gitignored). See `docs/SETUP.md`.
- `search()` builds a Gmail query string from `ProviderQuery`, e.g.:
  ```
  after:2023/01/01 before:2026/06/11
  (category:purchases OR subject:(order OR receipt OR invoice OR "order confirmation"
   OR shipped OR shipping))
  ```
  Use `users.messages.list` (paged via `pageToken`) → return `pageToken` as `next_cursor`.
- `fetch()` uses `users.messages.get(format='full')`, walk MIME parts for `text/plain`
  and `text/html`, decode base64url, pull `<img src>` from the HTML.
- **Batch** `get` calls (Gmail batch endpoint) and respect rate limits with backoff.
- Cursor for checkpoint mode = `internal_date` of the newest processed message (store as
  epoch ms string). Convert to a Gmail `after:` bound on the next run. (Page tokens are
  only valid within a single backfill run; the durable checkpoint is the date.)

> **Note:** keeping Gmail-isms (query strings, page tokens, MIME walking) entirely inside
> this file is the whole point — the pipeline must stay provider-neutral.

## Prefilter (`ingestion/prefilter.py`) — runs before any LLM

Cheap, deterministic, returns `keep | drop`. Order of checks:

1. **Already processed?** `message_id` in `processed_messages` → drop (skip).
2. **Hard promo exclusion** (subject or first ~200 chars, case-insensitive):
   `now available`, `new collection`, `back in stock`, `sale`, `% off`, `last chance`,
   `wishlist`, `you left`, `recommended for you`, `drop`. → drop.
3. **Positive transactional signal** — keep if subject matches any:
   `order`, `receipt`, `invoice`, `confirmation`, `shipped`, `dispatched`,
   `on its way`, `delivered`, `refund`, `return`. (Localize later — see edge cases:
   Hebrew variants like `הזמנה`, `קבלה`, `חשבונית`.)
4. **Sender hint (soft):** maintain `data/vendor_domains.txt` (Zara, ASOS, Nike,
   Farfetch, ...). A known apparel sender boosts keep; unknown senders still pass if (3)
   matched — the LLM gate is the real filter, the allowlist just saves cost on obvious
   non-apparel like Uber/utilities.

Keep the keyword lists in a small config module so they're easy to extend.

## Pipeline (`ingestion/pipeline.py`) — the two modes

```python
async def run_initialize(stop_year: int = 2023) -> JobResult:
    query = ProviderQuery(after=datetime(stop_year,1,1), before=now(), ...)
    await _drain(query, start_cursor=None, advance_checkpoint=True)

async def run_since_checkpoint() -> JobResult:
    cursor_date = sync_state.cursor_as_date()  # None → behave like init from stop_year
    query = ProviderQuery(after=cursor_date or default_start, before=now(), ...)
    await _drain(query, start_cursor=None, advance_checkpoint=True)
```

`_drain`:
1. Page through `provider.search(query, cursor)`.
2. For each ref: prefilter → fetch → clean (html→text, collect image srcs) → extract →
   if `is_valid_apparel_purchase`: fetch+store images → repo.upsert.
3. Record `processed_messages` for **every** message (kept or skipped) for idempotency.
4. Track the max `internal_date` seen; after a successful drain, write it to
   `sync_state.cursor`.
5. Emit progress events (count scanned / kept / skipped / errors) for the UI.

Runs as a background task (see 05) because backfill is long. Must be resumable: if it
dies, re-running skips already-processed messages.

## Definition of done
- `run_initialize(2023)` walks real Gmail, populates orders/items, and a **second run is
  a no-op** (everything already in `processed_messages`).
- `run_since_checkpoint()` after init only processes mail newer than the stored cursor.
