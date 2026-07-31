"""Bounded HTTP transport for configured AI providers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import requests


DEFAULT_MAX_PROVIDER_BYTES = 2_000_000
PROVIDER_STREAM_CHUNK_SIZE = 64 * 1024


class ProviderResponseTooLarge(ValueError):
    """Raised when a provider response exceeds its byte budget."""


class ProviderResponseInvalid(ValueError):
    """Raised when a provider returns invalid JSON."""


@dataclass(frozen=True)
class BoundedJsonResponse:
    status_code: int
    data: object
    text: str


def post_json_bounded(
    url: str,
    *,
    headers: dict,
    payload: dict,
    proxies: dict | None,
    max_bytes: int = DEFAULT_MAX_PROVIDER_BYTES,
    session: requests.Session | None = None,
) -> BoundedJsonResponse:
    """POST JSON and parse only after a bounded streaming read completes."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    client = session or requests.Session()
    owns_session = session is None
    try:
        response = client.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            stream=True,
            timeout=(5, 30),
        )
        try:
            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    parsed_length = int(declared_length)
                except ValueError:
                    parsed_length = None
                if parsed_length is not None and parsed_length > max_bytes:
                    raise ProviderResponseTooLarge("Provider response is too large")

            body = bytearray()
            for chunk in response.iter_content(chunk_size=PROVIDER_STREAM_CHUNK_SIZE):
                if not chunk:
                    continue
                if len(body) + len(chunk) > max_bytes:
                    raise ProviderResponseTooLarge("Provider response is too large")
                body.extend(chunk)

            text = bytes(body).decode("utf-8", errors="replace")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ProviderResponseInvalid("Provider returned invalid JSON") from exc
            return BoundedJsonResponse(
                status_code=response.status_code,
                data=data,
                text=text,
            )
        finally:
            response.close()
    finally:
        if owns_session:
            client.close()


async def async_post_json_bounded(
    url: str,
    *,
    headers: dict,
    payload: dict,
    proxies: dict | None,
    max_bytes: int = DEFAULT_MAX_PROVIDER_BYTES,
    total_timeout: float = 75.0,
    session: requests.Session | None = None,
) -> BoundedJsonResponse:
    """Run the bounded provider request off the event loop with a deadline."""
    operation = asyncio.to_thread(
        post_json_bounded,
        url,
        headers=headers,
        payload=payload,
        proxies=proxies,
        max_bytes=max_bytes,
        session=session,
    )
    return await asyncio.wait_for(operation, timeout=total_timeout)
