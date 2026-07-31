"""Bounded outbound HTTP helpers for untrusted public RSS URLs."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import requests


REDIRECT_STATUSES = {301, 302, 303, 307, 308}
STREAM_CHUNK_SIZE = 64 * 1024


class PublicUrlError(ValueError):
    """Raised when an outbound URL is not an allowed public HTTP target."""


class ResponseTooLargeError(ValueError):
    """Raised when a remote response exceeds its configured byte budget."""


def _is_public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return parsed.is_global


def validate_public_http_url(
    url: str,
    *,
    resolver: Callable = socket.getaddrinfo,
) -> str:
    """Validate scheme, authority, and every resolved address for an URL."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise PublicUrlError("RSS URL is not allowed") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PublicUrlError("RSS URL is not allowed")

    target_port = port or (443 if parsed.scheme == "https" else 80)
    try:
        literal_address = ipaddress.ip_address(parsed.hostname.split("%", 1)[0])
    except ValueError:
        literal_address = None

    if literal_address is not None:
        addresses = {str(literal_address)}
    else:
        try:
            resolved = resolver(parsed.hostname, target_port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise PublicUrlError("RSS URL could not be resolved") from exc
        addresses = {item[4][0] for item in resolved if item[4]}
    if not addresses or not all(_is_public_address(address) for address in addresses):
        raise PublicUrlError("RSS URL is not allowed")

    return url


def fetch_public_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: tuple[float, float],
    max_redirects: int = 3,
    session: requests.Session | None = None,
    resolver: Callable = socket.getaddrinfo,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Fetch a public URL with manual redirects and a strict byte ceiling."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")

    client = session or requests.Session()
    owns_session = session is None
    current_url = url

    try:
        for redirect_count in range(max_redirects + 1):
            validate_public_http_url(current_url, resolver=resolver)
            response = client.get(
                current_url,
                headers=headers,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
            try:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("Location")
                    if not location or redirect_count >= max_redirects:
                        raise PublicUrlError("RSS redirect is not allowed")
                    next_url = urljoin(current_url, location)
                    validate_public_http_url(next_url, resolver=resolver)
                    current_url = next_url
                    continue

                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = None
                    if declared_length is not None and declared_length > max_bytes:
                        raise ResponseTooLargeError("Remote response is too large")

                body = bytearray()
                for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
                    if not chunk:
                        continue
                    if len(body) + len(chunk) > max_bytes:
                        raise ResponseTooLargeError("Remote response is too large")
                    body.extend(chunk)
                return bytes(body)
            finally:
                response.close()
    finally:
        if owns_session:
            client.close()

    raise PublicUrlError("RSS redirect is not allowed")


async def async_fetch_public_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: tuple[float, float],
    total_timeout: float,
    max_redirects: int = 3,
    session: requests.Session | None = None,
    resolver: Callable = socket.getaddrinfo,
    headers: dict[str, str] | None = None,
) -> bytes:
    """Run bounded blocking HTTP outside the event loop with a total deadline."""
    operation = asyncio.to_thread(
        fetch_public_bytes,
        url,
        max_bytes=max_bytes,
        timeout=timeout,
        max_redirects=max_redirects,
        session=session,
        resolver=resolver,
        headers=headers,
    )
    return await asyncio.wait_for(operation, timeout=total_timeout)
