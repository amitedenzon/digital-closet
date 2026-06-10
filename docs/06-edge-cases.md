# 06 — Edge Cases & Hardening

Handle these explicitly; most are where naive versions break.

## Multi-email orders (the core dedup case)
A confirmation, a shipping notice, and maybe a delivery mail all share one
`merchant_order_id`. The first creates the order + items; later ones **UPSERT** the same
order (update status/tracking) and must **not** re-insert items. Guard item insertion by
`(order_id, item_name, size, color)`.

## Multi-item orders
One receipt → many items. One-to-many `orders → items`. Don't collapse to a single row.

## Marketplace vendors
ASOS, Farfetch, Zalando sell many brands. `vendor_domain` is the seller; per-item `brand`
comes from the line item, set by the LLM. Never default item `brand` to the vendor.

## Returns & cancellations
A refund/cancellation mail (`is_refund_or_cancellation=true`) references an existing
order. Match by `(vendor_domain, merchant_order_id)`; set affected items to
`returned`/`cancelled`; recompute order status (`returned` if all items, else
`partially_returned`). If the original order isn't in the DB yet (refund seen first),
store the refund intent and reconcile when the order appears — or just create the order
in returned state. Never hard-delete; keep history.

## Partial shipments / split parcels
Multiple shipping mails for one order, each covering some items. Don't duplicate items;
optionally track per-item shipped state. For the POC, order-level `shipped` is enough.

## Missing `merchant_order_id`
Fallback dedup key per `01-data-model`:
`(vendor_domain, purchase_date::date, total_price)`, else `message_id`. Log which fired.

## Tracking pixels & junk images
Covered in `04-images` — filter by size/filename, prefer product cues, de-dup by hash.

## Idempotency / resumability
Every message recorded in `processed_messages` before moving on. A crashed backfill
re-runs safely. Re-running `init` after completion is a no-op.

## Rate limits & cost
- Gmail: batch `get`, exponential backoff on `429/403 rateLimitExceeded`.
- Ollama: it's local and serial-ish — cap concurrency (e.g. 2–3) so the M2 stays
  responsive. Prefilter keeps LLM volume low.

## Local-model fragility
qwen2.5:7b will sometimes return null-heavy or low-confidence results, especially on
Hebrew or unusual layouts. Don't treat that as failure — store what's valid, flag
`confidence`. The `Extractor` interface lets a cloud model be swapped in per-vendor later
without touching the pipeline.

## Privacy
Read-only scope, secrets in `.env`, never log raw bodies/PII, `credentials.json` and
`token.json` gitignored, images stored locally only.

## Definition of done
Tests cover: duplicate order across two emails (no dup items), marketplace per-item
brand, a refund flipping item status, and a missing-order-id fallback key.
