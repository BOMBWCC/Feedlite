"""Security-sensitive environment validation and comparison helpers."""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping


PUBLIC_VALUES = {
    "ADMIN_PASSWORD": {"admin", "change-this-password"},
    "JWT_SECRET": {
        "replace-with-a-unique-random-secret",
        "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
    },
    "RAG_API_KEY": {"replace-with-private-rag-api-key"},
}

MIN_LENGTHS = {
    "ADMIN_PASSWORD": 16,
    "JWT_SECRET": 32,
    "RAG_API_KEY": 32,
}


def _validate_secret(name: str, value: str, *, required: bool) -> None:
    if not value:
        if required:
            raise ValueError(f"{name} must be configured")
        return

    if value in PUBLIC_VALUES.get(name, set()):
        raise ValueError(f"{name} must not use a public default or placeholder")

    minimum_length = MIN_LENGTHS[name]
    if len(value) < minimum_length:
        raise ValueError(f"{name} must be at least {minimum_length} characters")


def validate_security_config(environ: Mapping[str, str] | None = None) -> None:
    """Fail closed when required credentials are missing or publicly known."""
    values = os.environ if environ is None else environ
    _validate_secret("ADMIN_PASSWORD", values.get("ADMIN_PASSWORD", ""), required=True)
    _validate_secret("JWT_SECRET", values.get("JWT_SECRET", ""), required=True)
    _validate_secret("RAG_API_KEY", values.get("RAG_API_KEY", ""), required=False)


def configured_secret(name: str) -> str:
    """Return a configured secret without providing a repository fallback."""
    value = os.getenv(name, "")
    if not value:
        raise ValueError(f"{name} must be configured")
    return value


def credentials_match(provided: str, expected: str) -> bool:
    """Compare credential values without data-dependent early exit."""
    return hmac.compare_digest(
        str(provided).encode("utf-8"),
        str(expected).encode("utf-8"),
    )
