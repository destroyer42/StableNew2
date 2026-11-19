"""Idempotent edits carried by the existing Site rating transports."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.app.site_media_files import SiteOutputError

IDENTIFIER = re.compile(r"[a-f0-9]{32}")
ROOT_ID = re.compile(r"[a-f0-9]{64}")


def root_identity(root: Path) -> str:
    """Identify the approved directory across grants without returning a local path."""
    info = root.stat()
    identity = (os.path.normcase(str(root)), info.st_dev, info.st_ino)
    return fingerprint(identity)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def edit_stamp(operation: object, actor_time: object, payload: object) -> dict[str, str]:
    if (
        not isinstance(operation, str)
        or not IDENTIFIER.fullmatch(operation)
        or not isinstance(actor_time, str)
        or not 20 <= len(actor_time) <= 35
    ):
        raise SiteOutputError("invalid_rating")
    try:
        timestamp = datetime.fromisoformat(actor_time)
        if timestamp.utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise SiteOutputError("invalid_rating") from exc
    return {
        "digest": fingerprint((actor_time, payload)),
        "actor_time": actor_time,
        "source": "operator_site",
    }


def was_applied(receipts: dict[str, Any], operation: str, stamp: dict[str, str]) -> bool:
    if operation not in receipts:
        return False
    if receipts[operation] != stamp:
        raise SiteOutputError("rating_operation_reused")
    return True


def field_conflicts(
    current: dict[str, Any], base: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    return {
        field: current[field]
        for field, value in patch.items()
        if current[field] != base[field] and current[field] != value
    }
