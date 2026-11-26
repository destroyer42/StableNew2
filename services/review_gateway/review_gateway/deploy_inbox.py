"""DEPLOY-2: hand the PC's deploy request to the root deployer, and report what it did.

This service never deploys anything. It writes one small file, ``inbox/request.json``, which a root ``systemd`` path
unit hands to ``review-gateway-deploy from-request``. That command trusts nothing in the file: it checks the commit with
GitHub itself and re-reads the console switch. The service refuses while the switch is off, so a switched-off gateway
also says so to the PC. The status is read from the deployer's own ``last.json`` and passed on field by field after
checking each one.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .contract import SCHEMA_VERSION
from .errors import GatewayError

REQUEST_NAME = "request.json"
_SWITCH_LIMIT = 64
_LAST_LIMIT = 64 * 1024
_COMMIT = re.compile(r"[0-9a-f]{40}")
_OUTCOME = re.compile(r"[a-z_]{1,40}")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def _small_text(path: Path, limit: int) -> str | None:
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except OSError:
        return None
    if len(data) > limit:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _commit(value: object) -> str | None:
    return value if isinstance(value, str) and _COMMIT.fullmatch(value) else None


def _request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return value if str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


class DeployInbox:
    def __init__(self, switch_file: Path, deploy_dir: Path, release_dir: Path) -> None:
        self.switch_file = switch_file
        self.inbox = deploy_dir / "inbox"
        self.last_file = deploy_dir / "last.json"
        self.release_dir = release_dir

    @property
    def enabled(self) -> bool:
        return (_small_text(self.switch_file, _SWITCH_LIMIT) or "").strip() == "enabled"

    def _pending(self) -> dict[str, str] | None:
        text = _small_text(self.inbox / REQUEST_NAME, 1024)
        if text is None:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        request_id, target = _request_id(value.get("request_id")), _commit(value.get("target_sha"))
        return {"request_id": request_id, "target_sha": target} if request_id and target else None

    def submit(self, request: dict[str, Any]) -> str:
        """Write the request for the root deployer; ``request`` has passed the ``deploy_request`` schema."""

        if not self.enabled:
            raise GatewayError(409, "remote_deploy_disabled")
        target = self.inbox / REQUEST_NAME
        pending = self._pending()
        if pending is not None or target.exists():
            if pending is not None and pending["request_id"] == request["request_id"]:
                return "accepted"
            raise GatewayError(409, "deploy_pending")
        document = {
            "request_id": request["request_id"],
            "target_sha": request["target_sha"],
            "requested_at": request["requested_at"],
        }
        temporary = self.inbox / f".request-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as out:
                out.write(json.dumps(document, sort_keys=True))
            # Renamed into place whole, so the path unit never sees a half-written file.
            os.replace(temporary, target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise GatewayError(503, "deploy_inbox_unavailable") from error
        return "accepted"

    def _last(self) -> dict[str, Any] | None:
        text = _small_text(self.last_file, _LAST_LIMIT)
        if text is None:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        outcome = value.get("outcome")
        finished = value.get("finished_at")
        action = value.get("action")
        return {
            "action": action if action in ("deploy", "rollback") else None,
            "request_id": _request_id(value.get("request_id")),
            "target": _commit(value.get("target")),
            "old_commit": _commit(value.get("old_commit")),
            "new_commit": _commit(value.get("new_commit")),
            "outcome": outcome
            if isinstance(outcome, str) and _OUTCOME.fullmatch(outcome)
            else None,
            "schema_changed": value.get("schema_changed") is True,
            "finished_at": finished
            if isinstance(finished, str) and _STAMP.fullmatch(finished)
            else None,
        }

    def status(self) -> dict[str, Any]:
        source = _small_text(self.release_dir / "source.json", 4096)
        try:
            deployed = _commit(json.loads(source).get("commit")) if source else None
        except (ValueError, AttributeError):
            deployed = None
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "deploy_status",
            "remote_deploy": "enabled" if self.enabled else "disabled",
            "deployed_commit": deployed,
            "pending": self._pending(),
            "last": self._last(),
        }
