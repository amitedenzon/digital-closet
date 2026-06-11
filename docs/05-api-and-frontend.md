# 05 — API & Frontend

## FastAPI endpoints (`app/main.py`)

| method | path                     | purpose |
|--------|--------------------------|---------|
| POST   | `/sync/init`             | start backfill; body `{ "stop_year": 2023 }`; returns `{ job_id }` |
| POST   | `/sync/checkpoint`       | start incremental sync; returns `{ job_id }` |
| GET    | `/sync/status/{job_id}`  | `{ state, scanned, kept, skipped, errors, done }` |
| GET    | `/items`                 | list items; query: `vendor`, `brand`, `status`, `q`, paging |
| GET    | `/orders`                | list orders with nested items |
| GET    | `/images/{item_id}`      | serve stored image bytes |
| POST   | `/items/{item_id}/status`| manual override (e.g. mark returned) — optional |

- Sync runs are **background tasks** (FastAPI `BackgroundTasks` or a simple asyncio task
  registry). Long backfills must not block the request.
- Progress: simplest is polling `/sync/status`. Optional upgrade: Server-Sent Events at
  `/sync/stream/{job_id}`.
- Only one sync job at a time per account — reject a second with `409`.

## Auth bootstrap
First `/sync/init` with no `token.json` triggers the OAuth consent flow (desktop). For
the POC this can open the browser server-side once; document it in SETUP. Don't build a
full web OAuth handshake yet.

## Frontend (`frontend/`, Vite + React)

Keep it small — one page:

- **Header:** two buttons — `Initialize closet` (asks for stop year, default 2023) and
  `Sync since last check`. While a job runs, show a progress bar fed by `/sync/status`
  polling (scanned / kept / skipped / errors).
- **Closet grid:** cards from `GET /items` — image (`/images/{id}`), name, brand, size,
  color, price, vendor, purchase date. Returned/cancelled items shown dimmed with a badge.
- **Filters:** vendor, brand, status, free-text search. Client-side is fine for the POC.
- **Empty state:** prompt to run Initialize.

Plain `fetch` to the FastAPI base URL (configurable via `.env`/Vite env). No state library
needed; `useState`/`useEffect` is enough. CORS enabled on the backend for the Vite origin.

## Phase-04 cleanup (do this on the way)

While implementing phase 05, remove the unused `session` parameter from
`download_order_images` in `backend/app/ingestion/images.py`. The function mutates
`item.image_path` in-place; SQLAlchemy dirty-tracking + the caller's `session.commit()`
handles persistence — no session methods are called inside the function.

Changes required:
- `backend/app/ingestion/images.py`: remove `session: AsyncSession` parameter and its
  import (`from sqlalchemy.ext.asyncio import AsyncSession`)
- `backend/app/ingestion/pipeline.py`: drop `session` from the `download_order_images`
  call (line ~177)
- `backend/tests/test_images.py`: drop `session = MagicMock()` and the `session`
  argument from all six `download_order_images` test calls

## Definition of done
`Initialize` kicks off a backfill, the progress bar advances, and the grid fills with real
purchased items (with images) once done. `Sync since last check` adds only newer purchases.
