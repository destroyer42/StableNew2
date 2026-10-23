"""Toolkit-neutral session and row projection for the read-only asset readiness view (PR-ASSET-130).

The session owns no scheduler, cache or watcher. Each explicit request starts one unit of off-thread work through the
injected ``BackgroundWorkRunner`` and its outcome is delivered on the UI thread only while it is still the latest
request of a view that has not been closed; an older (superseded) hash stream is asked to cancel. Nothing runs at
construction, on paint, on a timer or at start-up.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.gui.view_contracts.video_experiment_contract import BackgroundWorkRunner, WorkOutcome

#: Plain-language labels; the status words themselves are the report's own vocabulary.
STATUS_LABELS = {
    "verified": "Verified",
    "present_unverified": "Present, not verified",
    "missing": "Missing",
    "mismatch": "Wrong file (hash mismatch)",
    "ambiguous": "Ambiguous (conflicting copies)",
    "unsupported": "Not usable",
    "needs_integration": "Not supported yet",
    "incomplete": "Unknown (not refreshed)",
}


@dataclass(frozen=True)
class ReadinessRow:
    resource_id: str
    title: str
    status: str
    status_label: str
    detail: str
    steps: tuple[str, ...]


def project_rows(report: dict[str, Any]) -> tuple[ReadinessRow, ...]:
    rows = []
    for entry in report["resources"]:
        parts = [f"Source: {entry['source']['url']}"]
        if entry["missing_roles"]:
            parts.append("missing: " + ", ".join(entry["missing_roles"]))
        if entry["reason_codes"]:
            parts.append(", ".join(entry["reason_codes"]))
        license_ = entry["source"]["license"]
        parts.append("license: " + (license_["spdx"] or "unknown") + f" ({license_['status']})")
        rows.append(
            ReadinessRow(
                entry["id"],
                entry["title"],
                entry["status"],
                STATUS_LABELS.get(entry["status"], entry["status"]),
                "; ".join(parts),
                tuple(entry["acquisition"]["steps"]),
            )
        )
    return tuple(rows)


def headline(report: dict[str, Any]) -> str:
    evidence = report["evidence"]
    if evidence["complete"]:
        return "Refreshed: files were hashed; this is current evidence. Nothing is downloaded or installed."
    return (
        "Not refreshed or incomplete ("
        + str(evidence["incomplete_reason"])
        + "): absence cannot be shown. Use Refresh to hash the ControlNet and auxiliary folders."
    )


class ReadinessSession:
    """Latest-wins, close-safe coordination of one readiness view."""

    def __init__(
        self,
        runner: BackgroundWorkRunner,
        produce_report: Callable[[bool, Callable[[], bool]], dict[str, Any]],
        on_report: Callable[[dict[str, Any]], None],
        on_error: Callable[[str], None],
        on_busy: Callable[[bool], None] = lambda _busy: None,
    ) -> None:
        self._runner = runner
        self._produce = produce_report
        self._on_report = on_report
        self._on_error = on_error
        self._on_busy = on_busy
        self._generation = 0
        self._closed = False
        self._pending = False

    @property
    def busy(self) -> bool:
        return self._pending

    def request(self, *, refresh: bool) -> None:
        """Start one explicit check (``refresh`` streams SHA-256); supersedes any earlier request."""

        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        self._pending = True
        self._on_busy(True)

        def stale() -> bool:
            return self._closed or generation != self._generation

        def work() -> WorkOutcome:
            return WorkOutcome(self._produce(refresh, stale))

        def done(outcome: WorkOutcome) -> None:
            if stale():
                return  # an older selection or a closed view never updates the live UI
            self._pending = False
            self._on_busy(False)
            if outcome.error:
                self._on_error(outcome.error)
            else:
                self._on_report(outcome.value)

        self._runner.start("AssetReadiness", work, done)

    def close(self) -> None:
        self._closed = True
