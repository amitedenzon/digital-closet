"""
Gmail implementation of MailProvider.

All google-api-python-client imports are confined to this file.
The rest of the app uses only app.providers.base types.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from app.providers.base import MessageRef, Page, ProviderQuery, RawMessage

logger = logging.getLogger(__name__)


def _with_backoff(fn, max_retries: int = 4):
    """Run fn() with exponential backoff on Gmail rate-limit errors (429/403)."""
    from googleapiclient.errors import HttpError

    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as exc:
            code = int(exc.resp.status)
            if code not in (429, 403) or attempt >= max_retries - 1:
                raise
            delay = (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "gmail:rate_limit status=%s attempt=%d retry_in=%.2f",
                code,
                attempt,
                delay,
            )
            time.sleep(delay)


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_query_string(query: ProviderQuery) -> str:
    parts: list[str] = []

    if query.after:
        parts.append(f"after:{query.after.strftime('%Y/%m/%d')}")
    if query.before:
        parts.append(f"before:{query.before.strftime('%Y/%m/%d')}")

    or_clauses: list[str] = []
    if query.category_purchases:
        or_clauses.append("category:purchases")
    if query.subject_any:
        kws = " OR ".join(query.subject_any)
        or_clauses.append(f"subject:({kws})")
    if or_clauses:
        parts.append(f"({' OR '.join(or_clauses)})")

    if query.sender_domains:
        senders = " OR ".join(f"from:{d}" for d in query.sender_domains)
        parts.append(f"({senders})")

    return " ".join(parts)


def _decode_b64(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recursively walk a MIME payload tree, return (text/plain, text/html)."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return _decode_b64(body_data), None
    if mime_type == "text/html" and body_data:
        return None, _decode_b64(body_data)

    text: str | None = None
    html: str | None = None
    for part in payload.get("parts", []):
        t, h = _walk_parts(part)
        text = text or t
        html = html or h
    return text, html


def _extract_image_srcs(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    return [img["src"] for img in soup.find_all("img") if img.get("src")]


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _build_service(credentials_file: str, token_file: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds: Credentials | None = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


class GmailProvider:
    """
    MailProvider backed by the Gmail API.

    The underlying google-api-python-client calls are synchronous;
    they are dispatched to the default ThreadPoolExecutor so the event
    loop is never blocked.
    """

    def __init__(self, service: Any, account: str) -> None:
        self._service = service
        self._account = account

    @classmethod
    def from_credentials_files(
        cls, credentials_file: str, token_file: str, account: str
    ) -> "GmailProvider":
        service = _build_service(credentials_file, token_file)
        return cls(service, account)

    async def search(self, query: ProviderQuery, cursor: str | None) -> Page:
        q_str = _build_query_string(query)
        loop = asyncio.get_running_loop()

        def _list() -> dict:
            kwargs: dict[str, Any] = {
                "userId": "me",
                "q": q_str,
                "maxResults": 500,
            }
            if cursor:
                kwargs["pageToken"] = cursor
            return self._service.users().messages().list(**kwargs).execute()

        raw = await loop.run_in_executor(None, lambda: _with_backoff(_list))
        messages = raw.get("messages", [])
        next_cursor: str | None = raw.get("nextPageToken")

        refs: list[MessageRef] = [
            MessageRef(
                message_id=m["id"],
                # internalDate not returned by messages.list; populated in fetch()
                internal_date=datetime.fromtimestamp(0, tz=timezone.utc),
            )
            for m in messages
        ]

        return Page(refs=refs, next_cursor=next_cursor)

    async def fetch(self, message_id: str) -> RawMessage:
        loop = asyncio.get_running_loop()

        def _get() -> dict:
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

        raw = await loop.run_in_executor(None, lambda: _with_backoff(_get))
        payload = raw.get("payload", {})
        headers = payload.get("headers", [])
        internal_ms = int(raw.get("internalDate", "0"))

        text, html = _walk_parts(payload)
        image_srcs = _extract_image_srcs(html) if html else []

        return RawMessage(
            message_id=message_id,
            account=self._account,
            from_addr=_get_header(headers, "From"),
            subject=_get_header(headers, "Subject"),
            date=datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc),
            text=text,
            html=html,
            image_srcs=image_srcs,
        )
