# Digital Closet

Turn your email into a visual wardrobe. Digital Closet scans your inbox for clothing
**purchases you actually made**, extracts each item (name, brand, size, color, price,
image) with a local LLM, deduplicates by order, and shows everything in a simple web UI.

Built POC-first, but with the hard parts behind interfaces so they can be swapped out:
other mail providers, cloud LLMs, and generative image processing later.

## Features
- **Two sync modes:** full historical backfill (stops at a configurable year, default
  2023) and incremental "sync since last check".
- **Purchases only:** heuristic prefilter + an LLM validity gate reject newsletters,
  "new collection", and "back in stock" mail before anything is stored.
- **Smart dedup:** multiple emails for one order (confirmation, shipping, refund) collapse
  to a single order — no duplicate items.
- **Local & private:** Gmail read-only access; extraction runs on a **local** model
  (`qwen2.5:7b` via Ollama); images stored on disk.
- **Returns-aware:** refunds/cancellations flip item status instead of leaving ghosts.
- **Swappable by design:** `MailProvider` and `Extractor` interfaces mean Outlook/IMAP
  or a cloud model is one new file, not a rewrite.

## Architecture (at a glance)
```
Gmail (readonly) → MailProvider → heuristic prefilter → Extractor (Ollama qwen2.5:7b)
   → image fetch+store → UPSERT/dedup (SQLite) → FastAPI → React UI
```
Dedup natural key: `(vendor_domain, merchant_order_id)`. Internal PK: UUID.
Full diagram in [docs/specs/00-architecture.md](docs/specs/00-architecture.md).

## Stack
Python 3.11 · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · SQLite (→ Postgres) · Gmail API ·
Ollama (`qwen2.5:7b`) · React + Vite.

## Quick start
See **[docs/SETUP.md](docs/SETUP.md)**. Short version:
```bash
ollama pull qwen2.5:7b
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```
Then open the UI and click **Initialize closet**.

## Documentation
- [Setup](docs/SETUP.md) — Gmail OAuth, Ollama, env, run commands
- [Architecture](docs/specs/00-architecture.md)
- [Data model](docs/specs/01-data-model.md)
- [Ingestion](docs/specs/02-ingestion.md) — providers, prefilter, the two modes
- [Extraction](docs/specs/03-extraction.md) — local LLM, schema, validation
- [Images](docs/specs/04-images.md)
- [API & frontend](docs/specs/05-api-and-frontend.md)
- [Edge cases](docs/specs/06-edge-cases.md)
- [CLAUDE.md](CLAUDE.md) — build rules & conventions for Claude Code

## Roadmap (post-POC)
- Other mail providers (Outlook/Graph, generic IMAP) via `MailProvider`.
- Cloud LLM fallback per-vendor via `Extractor`.
- Generative image processing: background removal → white-bg product shots → 3D models.
- Postgres + S3, multi-account.

## License
MIT.
