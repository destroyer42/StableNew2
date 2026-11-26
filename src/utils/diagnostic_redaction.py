"""Remove prompt text and secrets from values that leave the app as diagnostics (N11, RG-100 finding E1).

A diagnostics bundle is something the owner may attach to an issue in a public repository, so it must carry no
prompt (the creative content) and no credential. Keys are judged by their name: ``prompt``, ``negative_prompt`` and
``positive_preview`` are prompt text, while ``prompt_pack_id``, ``prompt_source`` and ``token_count`` describe one.
Free text is scrubbed for the shapes StableNew itself logs (``ORIGINAL POSITIVE: ...``, ``Enhanced: '...'``,
``final negative prompt='...'``, ``Negative prompt: ...``) and for ``key=value`` and bearer-token secrets.

Pure functions; no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "<redacted>"

_TEXT_WORDS = {"prompt", "prompts", "positive", "negative", "excerpt"}
# A key whose last word says it describes the prompt rather than holding it.
_DESCRIPTIVE_SUFFIXES = {
    "id",
    "ids",
    "pack",
    "source",
    "mode",
    "count",
    "counts",
    "len",
    "length",
    "chars",
    "chunks",
    "index",
    "row",
    "policy",
    "changed",
    "applied",
    "enabled",
    "kind",
    "type",
    "hash",
    "sha256",
    "fingerprint",
    "optimizer",
    "slot",
    "version",
    "schema",
}
_SECRET_WORDS = {
    "secret",
    "secrets",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "bearer",
}
_SECRET_KEY = re.compile(
    r"(^|_)(api_?key|access_?key|private_?key|auth_?key|token|tokens|access_token)$"
)

_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"((?:ORIGINAL|OPTIMIZED|FINAL)\s+(?:POSITIVE|NEGATIVE)\s*:\s*)[^\n]*", re.IGNORECASE
    ),
    re.compile(r"(final\s+(?:positive|negative)\s+prompt[^\n=:]*[=:]\s*)[^\n]*", re.IGNORECASE),
    re.compile(r"(Enhanced:\s*)[^\n]*"),
    re.compile(r"(\b(?:negative\s+|positive\s+)?prompts?\s*[=:]\s*)[^\n]*", re.IGNORECASE),
    re.compile(
        r"((?:api[_-]?key|access[_-]?token|token|secret|password|passwd)[\"']?\s*[=:]\s*[\"']?)[^\s,;&'\"]+",
        re.IGNORECASE,
    ),
    re.compile(r"(Authorization\s*[:=]\s*(?:Bearer\s+|Basic\s+)?)[^\s,;'\"]+", re.IGNORECASE),
    re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
)


def _words(key: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return [word for word in re.split(r"[^a-z0-9]+", spaced.lower()) if word]


def is_sensitive_key(key: object, extra_keys: Iterable[str] = ()) -> bool:
    """True when a mapping key names prompt text or a secret."""

    if not isinstance(key, str):
        return False
    if key in extra_keys or key.lower() in extra_keys:
        return True
    words = _words(key)
    if not words:
        return False
    if _SECRET_WORDS.intersection(words) or _SECRET_KEY.search("_".join(words)):
        return words[-1] not in {"count", "counts", "len", "length", "budget", "limit"}
    if _TEXT_WORDS.intersection(words) and (
        "prompt" in words or "prompts" in words or len(words) > 1
    ):
        return words[-1] not in _DESCRIPTIVE_SUFFIXES
    return False


def redact_text(text: str) -> str:
    """Scrub prompt text and inline secrets from one piece of free text (a log message, an output tail)."""

    for pattern in _TEXT_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + REDACTED, text)
    return text


def redact(value: Any, *, extra_keys: Iterable[str] = ()) -> Any:
    """A copy of a JSON-like value with prompt and secret values replaced by ``<redacted>``."""

    extra = frozenset(extra_keys)
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {key: _redact_item(key, item, extra) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, extra_keys=extra) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, extra_keys=extra) for item in value)
    return value


def _redact_item(key: object, item: Any, extra: frozenset[str]) -> Any:
    # A number or flag under a sensitive-looking key (``max_tokens``) is not text; empty values say nothing.
    if item is None or isinstance(item, (bool, int, float)) or item in ("", [], {}):
        return item
    if is_sensitive_key(key, extra):
        return REDACTED
    return redact(item, extra_keys=extra)
