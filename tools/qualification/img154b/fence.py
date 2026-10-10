"""D2 (154B): the atomic, durable, no-retry dispatch fence.

This is an EXTENSION of the PR-154A dispatch ledger (``DispatchLedger`` records, ``FileLedgerStore`` validation and the
fsync-per-record ``DurableJsonlWriter``), not a queue or a history authority. It adds only three things:

* a stable, workspace-independent location for one case's record (so changing the qualification workspace cannot re-enable
  a consumed case),
* an atomic cross-process claim (``O_EXCL`` creation of the case's ledger file: exactly one process can ever create it), and
* ownership verification on every stage record (a lost, replaced or torn ledger stops progression and stays ambiguous).

The one-attempt identity is the owner-authorized ``case_id`` digest of the manifest. It does not depend on policy revisions,
request wording, the repository revision or the qualification workspace. A case that has been claimed is consumed for ever:
a failed preflight is not a claim, but a start failure, a transport failure, a crash, a restart, a torn record or a
vanished ledger are all ambiguous, and a ``terminal_evidence`` record does not re-open anything either.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.img154.evidence import (
    LEDGER_STAGES,
    DispatchLedger,
    FileLedgerStore,
    LedgerRefusal,
)
from tools.qualification.img154.manifest import QualificationManifest

__all__ = [
    "CaseFence",
    "ExclusiveFileLedgerStore",
    "FenceRefusal",
    "FenceState",
    "LEDGER_STAGES",
    "case_record_path",
    "stable_record_root",
    "workspace_ledger_state",
]

RECORD_ROOT_PARTS = ("StableNew", "Qualification", "IMG154_CASE_RECORDS")

CASE_ALREADY_CLAIMED = "CASE_ALREADY_CLAIMED"
RECORD_LOCATION_REFUSED = "RECORD_LOCATION_REFUSED"
RECORD_INACCESSIBLE = "RECORD_INACCESSIBLE"
OWNERSHIP_LOST = "OWNERSHIP_LOST"
STAGE_REFUSED = "STAGE_REFUSED"
NOT_CLAIMED = "NOT_CLAIMED"


class FenceRefusal(RuntimeError):
    """A claim or stage record was refused. ``code`` is machine-readable; progression must stop."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def stable_record_root(env: Mapping[str, str] | None = None) -> Path:
    """The per-user location of every case record. Resolved on call, never at import, and never derived from a workspace."""

    source = os.environ if env is None else env
    base = source.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base).joinpath(*RECORD_ROOT_PARTS)


def case_record_path(record_root: Path | str, manifest: QualificationManifest) -> Path:
    """One ledger file per owner-authorized case identity (a 64-hex digest: no path component can be injected)."""

    return Path(record_root) / f"{manifest.attempt_identity()}.ledger.jsonl"


class ExclusiveFileLedgerStore(FileLedgerStore):
    """A ``FileLedgerStore`` whose attempt record can only ever CREATE the file (atomic across processes)."""

    def claim(self, record: dict[str, Any]) -> None:
        self._writer.append_exclusive(record)


def workspace_ledger_state(path: Path | str, manifest: QualificationManifest) -> str:
    """``none`` | ``ambiguous`` | ``dispatched`` | ``unknown`` of the PR-154A workspace ledger (read only).

    A case that appears there is consumed as well: the stable record and the workspace ledger must both be clean.
    """

    try:
        return DispatchLedger(FileLedgerStore(path)).preflight_state(manifest)
    except OSError:
        return "unknown"


@dataclass(frozen=True)
class FenceState:
    """``status``: ``none`` (never claimed) | ``open`` (claimed, no terminal record: ambiguous) | ``terminal`` |
    ``unknown`` (unreadable, torn, misfiled or discontinuous: ambiguous, never repaired)."""

    status: str
    stages: tuple[str, ...] = ()
    reason: str = ""
    #: ``inaccessible`` | ``torn`` | ``misfiled`` | ``""``: why an ``unknown`` state is unknown.
    code: str = ""

    @property
    def consumed(self) -> bool:
        return self.status != "none"

    @property
    def ambiguous(self) -> bool:
        return self.status in ("open", "unknown")

    def preflight_state(self) -> str:
        """The value ``PreflightInputs.ledger_state`` expects: only a never-claimed case is ``none``."""

        return {"none": "none", "terminal": "dispatched", "open": "ambiguous"}.get(
            self.status, "unknown"
        )


def _inside(child: Path, parent: Path) -> bool:
    """Case-insensitive containment after resolving links, junctions and short names where they exist."""

    child_parts = [
        part.lower() for part in os.path.realpath(child).replace("\\", "/").split("/") if part
    ]
    parent_parts = [
        part.lower() for part in os.path.realpath(parent).replace("\\", "/").split("/") if part
    ]
    return bool(parent_parts) and child_parts[: len(parent_parts)] == parent_parts


class CaseFence:
    """The claim and ordered stage records of ONE case. One instance is one claimant (it holds an unguessable token)."""

    def __init__(
        self,
        manifest: QualificationManifest,
        record_root: Path | str,
        *,
        workspace_root: Path | str | None = None,
        sync: Callable[[int], None] = os.fsync,
        now_utc: Callable[[], str] | None = None,
        mono: Callable[[], float] | None = None,
    ) -> None:
        self.manifest = manifest
        self.record_root = Path(record_root)
        self.path = case_record_path(self.record_root, manifest)
        if workspace_root is not None and _inside(self.record_root, Path(workspace_root)):
            raise FenceRefusal(
                RECORD_LOCATION_REFUSED,
                "the case record must live outside the qualification workspace so a new workspace cannot re-enable the case",
            )
        self._store = ExclusiveFileLedgerStore(self.path, sync=sync)
        self._ledger = DispatchLedger(self._store)
        self._token = secrets.token_hex(16)
        self._claimed = False
        self._now_utc = now_utc or (lambda: datetime.now(UTC).isoformat())
        self._mono = mono

    # ------------------------------------------------------------------------------------------------------ reading
    def state(self) -> FenceState:
        """Read-only. A record that exists but cannot be fully validated is ``unknown``, which is as consumed as ``open``."""

        try:
            exists = self.path.exists()
            if not exists and self.record_root.exists():
                if not self.record_root.is_dir() or not os.access(
                    self.record_root, os.R_OK | os.W_OK
                ):
                    return FenceState(
                        "unknown", (), "record directory is not usable", "inaccessible"
                    )
        except OSError as exc:
            return FenceState(
                "unknown",
                (),
                f"record location not accessible ({type(exc).__name__})",
                "inaccessible",
            )
        if not exists:
            return FenceState("none")
        ledger_state = self._ledger.state(self.manifest)
        if ledger_state == "none":
            return FenceState(
                "unknown",
                (),
                "record exists but holds no attempt for this case identity",
                "misfiled",
            )
        if ledger_state == "unknown":
            return FenceState(
                "unknown",
                (),
                "ledger is torn, corrupt, misordered or discontinuous; not repaired",
                "torn",
            )
        history = self._ledger.stage_history(self.manifest) or ()
        if ledger_state == "completed":
            return FenceState("terminal", history)
        return FenceState("open", history)

    def stage_history(self) -> tuple[str, ...]:
        return self.state().stages

    def _owns_record(self) -> bool:
        if not self._claimed:
            return False
        try:
            records = self._store.read()
        except OSError:
            return False
        first = records[0] if records else {}
        claimant = first.get("claimant") if isinstance(first, dict) else None
        return (
            isinstance(claimant, dict)
            and claimant.get("token") == self._token
            and first.get("attempt_identity") == self.manifest.attempt_identity()
        )

    # ------------------------------------------------------------------------------------------------------ writing
    def claim(self, *, provenance: Mapping[str, Any] | None = None) -> None:
        """Atomically consume the case. Raises ``FenceRefusal``; on success the ``claimed`` record is durable."""

        if self._claimed:
            raise FenceRefusal(STAGE_REFUSED, "this fence has already claimed the case")
        state = self.state()
        if state.consumed:
            code = RECORD_INACCESSIBLE if state.code == "inaccessible" else CASE_ALREADY_CLAIMED
            raise FenceRefusal(
                code, f"ledger state is {state.status!r}; there is no retry or replay"
            )
        claimant = {
            "token": self._token,
            "pid": os.getpid(),
            "claimed_utc": self._now_utc(),
            "provenance": dict(provenance or {}),
        }
        try:
            self._ledger.record_attempt(self.manifest, claimant=claimant)
        except LedgerRefusal as exc:
            raise FenceRefusal(CASE_ALREADY_CLAIMED, str(exc)) from exc
        except OSError as exc:
            raise FenceRefusal(RECORD_INACCESSIBLE, type(exc).__name__) from exc
        self._claimed = True

    def record_stage(self, stage: str, **facts: Any) -> None:
        """Make ``stage`` durable. Raises ``FenceRefusal`` (the caller must then NOT perform the announced action)."""

        if not self._claimed:
            raise FenceRefusal(
                NOT_CLAIMED,
                "this fence holds no claim; a stage can only be recorded by the claimant",
            )
        if not self._owns_record():
            raise FenceRefusal(
                OWNERSHIP_LOST, "the case record is missing, replaced, torn or not ours"
            )
        payload = dict(facts)
        payload["utc"] = self._now_utc()
        if self._mono is not None:
            payload["mono_s"] = self._mono()
        try:
            self._ledger.record_stage(self.manifest, stage, payload)
        except LedgerRefusal as exc:
            raise FenceRefusal(STAGE_REFUSED, str(exc)) from exc

    def finish(self, outcome: str, **facts: Any) -> None:
        """Record ``terminal_evidence`` and close the attempt with its outcome class. Never re-opens the case."""

        self.record_stage("terminal_evidence", proposed_outcome=outcome, **facts)
        try:
            self._ledger.record_outcome(self.manifest, outcome)
        except (LedgerRefusal, OSError, StopIteration, KeyError, ValueError, TypeError) as exc:
            # anything that prevents the outcome record leaves the case open (ambiguous), reported as a refusal
            raise FenceRefusal(STAGE_REFUSED, f"{type(exc).__name__}: {exc}") from exc
