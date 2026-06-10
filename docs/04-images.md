# 04 — Images

Product images in emails are CDN links that expire or block hotlinking. Download and
store them **at ingest**, while the mail is fresh.

## Storage layout (POC)
```
data/images/{vendor_domain}/{order_id}/{item_id}.{ext}
```
Store the local path on `items.image_path`; keep the original URL on `items.image_url_src`
for provenance. (Later: swap the local dir for S3 behind a tiny `Storage` interface.)

## Selecting the real product image
The LLM returns a candidate `image_url` per item, but emails are full of junk images.
Before/while downloading, filter:

- Drop `data:` URIs and `cid:` inline refs.
- Drop tracking pixels: URL/markup width or height `<= 2`, or filenames like
  `pixel`, `open`, `track`, `spacer`, `1x1`, `beacon`.
- Drop tiny logos/icons: after download, reject images smaller than ~`100x100`.
- Prefer URLs/`alt` text containing product cues (`product`, `/p/`, item name tokens).
- De-dup identical images (hash bytes) so repeated header logos aren't stored per item.

If no good image is found, leave `image_path` null — that's fine, the item still exists.

## Downloading
- `httpx.AsyncClient`, modest concurrency (e.g. 5), timeout + one retry.
- Send a normal `User-Agent` and the vendor as `Referer` (some CDNs require it).
- Validate it's actually an image (content-type / magic bytes), normalize to `.jpg`/`.png`.
- Never block the pipeline on image failures — log and move on.

## Future hook (not in POC)
This is where the Python ML work plugs in later: background-removal and white-background
product shots, and 3D model generation. Keep it a separate, queued step keyed on
`item_id` so it never slows ingestion. Add a `processed_image_path` column when that lands.

## Definition of done
For a sample order email, the genuine product image is downloaded to `data/images/...`,
tracking pixels and header logos are rejected, and `items.image_path` is populated.
