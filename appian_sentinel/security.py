"""Secret redaction for messages that can reach logs or clients."""

from __future__ import annotations

import re
from collections.abc import Iterable

from appian_sentinel.config import settings

_SECRET_VALUE = re.compile(
    r"(?i)(?:"
    r"(authorization|api[_-]?key|ado[_-]?pat|access[_-]?token)"
    r"(['\"]?\s*[:=]\s*['\"]?)(?:bearer\s+|basic\s+)?"
    r"|"
    r"\b(sk-[A-Za-z0-9_-]{8,})"
    r")([^'\",\s}\]]*)"
)


def mask_secret(secret: str) -> str:
    """Mask a secret while retaining four trailing characters."""
    if len(secret) <= 4:
        return "*" * len(secret)
    return "*" * (len(secret) - 4) + secret[-4:]


def mask_secrets(value: str, secrets: Iterable[str] = ()) -> str:
    """Redact configured secrets and common credential representations."""
    masked = value
    configured = (settings.litellm_api_key, settings.ado_pat)
    for secret in (*configured, *secrets):
        if secret:
            masked = masked.replace(secret, mask_secret(secret))

    def replace(match: re.Match[str]) -> str:
        if match.group(3):
            return mask_secret(match.group(3))
        return f"{match.group(1)}{match.group(2)}****"

    return _SECRET_VALUE.sub(replace, masked)
