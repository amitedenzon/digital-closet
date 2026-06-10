# CLAUDE.md — Digital Closet

Guidance for Claude Code working in this repo. Read this first, then the relevant
file under `docs/specs/` before implementing a phase.

## What this is

A "digital closet": scrape my email for **clothing purchases I actually made**,
extract structured items (name, brand, size, color, price, image), store them, and
show them in a simple web UI. POC scope; built so the hard parts can be swapped out
later (other mail providers, cloud LLMs, generative image processing).

## Stack (locked for the POC)

- **Backend:** Python 3.11+, `asyncio`, FastAPI, SQLAlchemy 2.0, Pydantic v2.
- **DB:** SQLite for the POC, schema written so migration to PostgreSQL is trivial.
- **Mail:** Gmail API (`google-api-python-client`) behind a generic `MailProvider`.
- **Extraction LLM:** local **Ollama** running `qwen2.5:7b`, behind a generic `Extractor`.
- **Frontend:** React + Vite (small). Talks to the FastAPI JSON API only.
- **Tooling:** `ruff` + `black`, `pytest`, `uv` or `pip`.

## Golden rules (do not violate)

1. **Read-only mail.** Never send, modify, label, or delete mail. Gmail scope is
   `gmail.readonly` only.
2. **Provider-agnostic mail.** All mail access goes through the `MailProvider`
   interface. The Gmail SDK may only be imported inside `providers/gmail.py`. No
   Gmail-specific types leak out of that file.
3. **LLM-agnostic extraction.** All model calls go through the `Extractor` interface.
   Ollama may only be imported inside `extraction/ollama_extractor.py`.
4. **Never LLM every email.** A cheap heuristic prefilter runs first
   (sender domain + subject regex + Gmail purchase category). The LLM only sees
   survivors. This is the main cost lever — do not bypass it.
5. **Dedup natural key = `(vendor_domain, merchant_order_id)`.** The internal primary
   key is a generated UUID — never use it for dedup. Writes are **UPSERT**: a second
   email for the same order (e.g. shipping notice) updates the order, it never
   duplicates items.
6. **Idempotent runs.** Every processed `message_id` is recorded. Already-processed
   messages are skipped on re-run.
7. **Purchases only.** Hard-exclude promo mail (`now available`, `new collection`,
   `sale`, `back in stock`, ...). The LLM must also return
   `is_valid_apparel_purchase` as a final gate; if false, store nothing.
8. **Store images at ingest.** Download product images locally when processing the
   mail. Never rely on the email's `src` URL staying alive.
9. **Defensive LLM handling.** Validate every model response against the Pydantic
   schema. On parse failure, retry once with a stricter instruction. On second
   failure, mark the message `error` and continue — never crash the whole run.
10. **Secrets + privacy.** All secrets in `.env` (gitignored). Never log full email
    bodies or PII. Never commit `credentials.json` or `token.json`.

## Repo layout (target)

```
digital-closet/
├── CLAUDE.md
├── README.md
├── .env.example
├── docs/
│   ├── SETUP.md
│   └── specs/                 # build phases — implement in order
│       ├── 00-architecture.md
│       ├── 01-data-model.md
│       ├── 02-ingestion.md
│       ├── 03-extraction.md
│       ├── 04-images.md
│       ├── 05-api-and-frontend.md
│       └── 06-edge-cases.md
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + routes
│   │   ├── config.py          # settings from .env
│   │   ├── db.py              # engine/session
│   │   ├── models.py          # SQLAlchemy tables
│   │   ├── schemas.py         # Pydantic (API + LLM output)
│   │   ├── providers/
│   │   │   ├── base.py        # MailProvider interface
│   │   │   └── gmail.py       # Gmail implementation
│   │   ├── extraction/
│   │   │   ├── base.py        # Extractor interface
│   │   │   ├── ollama_extractor.py
│   │   │   └── prompt.py
│   │   ├── ingestion/
│   │   │   ├── prefilter.py   # heuristic candidate filter
│   │   │   ├── pipeline.py    # orchestrates the two modes
│   │   │   └── images.py      # download/store + pixel filter
│   │   └── store/
│   │       └── repo.py        # UPSERT + checkpoint logic
│   └── tests/
└── frontend/                  # Vite + React
```

## Build order

Implement one phase at a time, in order. Each phase doc has a "Definition of done".

1. `01-data-model` → models + migrations + repo skeleton
2. `02-ingestion` → `MailProvider`, Gmail impl, prefilter, pipeline modes
3. `03-extraction` → `Extractor`, Ollama impl, schema, validation
4. `04-images` → download/store, pixel filter
5. `05-api-and-frontend` → FastAPI endpoints + React UI
6. `06-edge-cases` → returns, marketplace, partial shipments, hardening

## Conventions

- Full type hints; `async def` for all I/O (mail, http, db where supported).
- Pydantic v2 for the LLM output schema **and** API responses.
- No business logic in route handlers — keep it in `ingestion/` and `store/`.
- Log structured events (`message_id`, decision, duration), never raw bodies.

## Verification (before claiming a phase is done)

Per `verification-before-completion`: run the checks and paste the real output before
saying anything works.

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Do not say a phase is complete, fixed, or passing without showing command output.
