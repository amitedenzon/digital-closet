from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from app.extraction.base import CleanedMessage
from app.extraction.prompt import SYSTEM_PROMPT, build_user_message
from app.schemas import ExtractionResult

logger = logging.getLogger(__name__)

_RETRY_INSTRUCTION = (
    "Your previous response was not valid JSON matching the schema. "
    "Return ONLY valid JSON. No explanation, no markdown."
)


class OllamaExtractor:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client or httpx.AsyncClient()

    async def extract(self, msg: CleanedMessage) -> ExtractionResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(msg)},
        ]

        raw = await self._call(messages)
        try:
            result = ExtractionResult.model_validate_json(raw)
        except ValidationError:
            logger.warning(
                "extraction:parse_failed:retry message_id=%s", msg.message_id
            )
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": _RETRY_INSTRUCTION})
            raw = await self._call(messages)
            result = ExtractionResult.model_validate_json(
                raw
            )  # raises on second failure

        if not result.vendor_domain:
            result.vendor_domain = msg.vendor_domain

        for item in result.items:
            if item.image_url and item.image_url not in msg.image_srcs:
                logger.debug(
                    "extraction:image_url_not_in_srcs message_id=%s url=%s",
                    msg.message_id,
                    item.image_url,
                )
                item.image_url = None

        return result

    async def _call(self, messages: list[dict]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
            "format": ExtractionResult.model_json_schema(),
        }
        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
