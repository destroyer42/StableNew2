"""RG-160: what the phone may choose while this PC is away, as names only.

The gateway keeps the latest catalog so the phone can offer the same checkpoints, ratios and Make Video workflow it
offers with the PC there, and can show the warnings the picker showed. Nothing is decided from it: when a request
arrives, the PC compiles it against what is true then and refuses a choice that has gone.

No path crosses (RG-100 invariant 3): a checkpoint is its file name and a hashed id, and warning text is scrubbed like
every action summary. The size limits are transport bounds, not quotas.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import PureWindowsPath
from typing import Any

from src.app.review_gateway_actions import ASPECT_RATIOS, model_choice_id
from src.app.review_gateway_protocol import (
    SCHEMA_VERSION,
    encode_json,
    parse_timestamp,
    scrub_text,
    utc_now,
    utc_text,
)
from src.app.review_gateway_store import SyncLedger
from src.pipeline.policy_warnings import PolicyWarning

log = logging.getLogger(__name__)

MAX_MODELS = 200
MAX_WARNINGS = 20
#: Under the gateway's 64 KiB JSON body limit.
MAX_BYTES = 60 * 1024
_META = "catalog_models"
#: The remembered list's time is rewritten no more often than this while the list is unchanged.
_REMEMBER_EVERY = timedelta(minutes=10)
_NOT_IN_A_LABEL = re.compile(r"[\\/\x00-\x1f\x7f]+")
_NOT_IN_A_NOTE = re.compile(r"[\\\x00-\x1f\x7f]+")
_WARNING_CODE = re.compile(r"[a-z0-9_]{1,64}")


def _label(value: str, fallback: str) -> str:
    return _NOT_IN_A_LABEL.sub(" ", scrub_text(value, 120)).strip() or fallback


def _warning(item: PolicyWarning) -> dict[str, str]:
    code = item.code if _WARNING_CODE.fullmatch(item.code) else "policy_warning"
    body = {"code": code}
    for key in ("title", "why", "fix"):
        text = _NOT_IN_A_NOTE.sub(" ", scrub_text(getattr(item, key), 300)).strip()
        if text:
            body[key] = text
    body.setdefault("title", code)
    return body


class ChoiceCatalog:
    """Builds the ``choice_catalog`` payload from the running application's own lists."""

    def __init__(
        self,
        ledger: SyncLedger,
        *,
        models: Callable[[], Sequence[str]],
        warning_of: Callable[[str], PolicyWarning | None],
        video: Callable[[], str],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._ledger = ledger
        self._models = models
        self._warning_of = warning_of
        self._video = video
        self._clock = clock

    def _model_names(self) -> tuple[list[str], str, bool]:
        """``(names, when they were listed, whether the image backend lists them now)``.

        A session whose backend has not listed any (not started, or busy) keeps the last list, never an empty one
        over a good one.
        """

        try:
            names = [str(name) for name in self._models() if str(name).strip()]
        except Exception as error:  # noqa: BLE001 - a busy or closing app lists nothing this time
            log.debug("The model list was not read for the phone (%s)", type(error).__name__)
            names = []
        try:
            stored = json.loads(self._ledger.get_meta(_META) or "{}")
        except ValueError:
            stored = {}
        if not names:
            return list(stored.get("names") or []), str(stored.get("at") or ""), False
        now = self._clock()
        if stored.get("names") != names or parse_timestamp(stored["at"]) + _REMEMBER_EVERY < now:
            self._ledger.set_meta({_META: json.dumps({"names": names, "at": utc_text(now)})})
        return names, utc_text(now), True

    def _video_label(self) -> str:
        try:
            label = self._video()
        except Exception as error:  # noqa: BLE001 - an unreadable registry means no Make Video to offer
            log.debug("The video workflow was not read for the phone (%s)", type(error).__name__)
            return ""
        return _label(label, "") if label else ""

    def payload(self) -> dict[str, Any]:
        names, as_of, ready = self._model_names()
        ordered = sorted(names, key=str.casefold)
        truncated = len(ordered) > MAX_MODELS
        warnings: list[dict[str, str]] = []
        models: list[dict[str, Any]] = []
        for name in ordered[:MAX_MODELS]:
            choice = model_choice_id(name)
            found: list[int] = []
            item = self._warning_of(name)
            if item is not None:
                warning = _warning(item)
                if warning not in warnings and len(warnings) < MAX_WARNINGS:
                    warnings.append(warning)
                if warning in warnings:
                    found.append(warnings.index(warning))
                else:
                    truncated = True
            models.append(
                {
                    "id": choice,
                    "label": _label(PureWindowsPath(name).name, choice),
                    "warnings": found,
                }
            )
        video = self._video_label()
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "type": "choice_catalog",
            "published_at": utc_text(self._clock()),
            "models": models,
            "warnings": warnings,
            "ratios": [{"id": key, "label": label} for key, label, _w, _h in ASPECT_RATIOS],
            "video": {"available": True, "label": video} if video else {"available": False},
            "image_backend_ready": ready,
            "truncated": truncated,
        }
        if names and as_of:
            body["models_as_of"] = as_of
        return _fitted(body)


def _fitted(body: dict[str, Any]) -> dict[str, Any]:
    """Within the transport limit: the warnings' explanations go first, then models from the end."""

    if len(encode_json(body)) <= MAX_BYTES:
        return body
    body["truncated"] = True
    body["warnings"] = [
        {key: value for key, value in warning.items() if key in ("code", "title")}
        for warning in body["warnings"]
    ]
    while body["models"] and len(encode_json(body)) > MAX_BYTES:
        body["models"].pop()
    return body
