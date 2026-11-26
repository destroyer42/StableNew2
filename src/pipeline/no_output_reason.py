"""Operator-readable reasons a stage produced no output (N11).

A stage that cannot produce an image returns nothing rather than raising, so before N11 the runner could only report
"No images were generated successfully" (483 such jobs in the owner's History). The executor now records the first
concrete reason here and the runner reports it. Reasons are one bounded line with prompt text and secrets scrubbed,
because they are shown in History and may be synced to the phone.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.utils.diagnostic_redaction import redact_text

GENERIC_NO_OUTPUT = "No images were generated successfully"
MAX_REASON_CHARS = 500
_DETAIL_KEYS = ("error", "errors", "detail", "message")


def operator_reason(text: object) -> str:
    """One line, at most ``MAX_REASON_CHARS``, prompt text and secrets scrubbed."""

    line = redact_text(" ".join(str(text).split()))
    return line if len(line) <= MAX_REASON_CHARS else line[: MAX_REASON_CHARS - 3].rstrip() + "..."


def exception_reason(exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def empty_response_reason(response: Any) -> str:
    """Why a generation answer holds no image, with whatever the backend said about it."""

    if not response:
        return "the backend returned no response"
    detail = backend_detail(response)
    return (
        f"the backend returned no images ({detail})" if detail else "the backend returned no images"
    )


def backend_detail(response: Any) -> str:
    """The backend's own error words from a response (top level or its ``info``), never its echoed request body."""

    if not isinstance(response, Mapping):
        return ""
    sources: list[Mapping[str, Any]] = [response]
    info = response.get("info")
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except ValueError:
            info = None
    if isinstance(info, Mapping):
        sources.append(info)
    found: list[str] = []
    for source in sources:
        for key in _DETAIL_KEYS:
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                value = "; ".join(
                    str(item) for item in value if isinstance(item, (str, int, float))
                )
            if (
                isinstance(value, (str, int, float))
                and str(value).strip()
                and str(value) not in found
            ):
                found.append(str(value))
    return "; ".join(found)


def fallback_reason(stage_name: str | None) -> str:
    stage = stage_name or "pipeline"
    return f"{GENERIC_NO_OUTPUT}: the {stage} stage produced no output and reported no reason"
