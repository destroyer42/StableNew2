"""The running app's side of a live update (LAUNCH-UPDATE-1): switch, rate limit, drain, hand-off and receipt.

``update`` runs on a worker thread, never on Tk:

1. Refuse while another update is pending, when a remote request arrives with the owner's **Allow remote update**
   switch off (the default), or when a remote update ran less than 10 minutes ago.
2. :func:`src.app.live_update.preflight` (nothing changes on a refusal).
3. Hold queue dispatch in memory (``JobQueue.hold_dispatch_for_update``; never the persisted pause) and wait for the
   running job to finish. It is never cancelled. After ``max_wait_seconds`` the hold is released and the request is
   refused ``busy_timeout``.
4. Write the intent, start the detached updater and set :attr:`exit_requested`. The Tk control sees that and closes
   the app through the normal graceful exit, so queued jobs and ``auto_run_enabled`` come back after the restart as
   after any clean exit.

On the next start the app calls :meth:`mark_started` (the updater's health signal) and :meth:`collect_result`, which
turns the updater's result into the receipt kept in ``last_result.json`` (shown on the desktop; acknowledged to the
phone in LAUNCH-UPDATE-2). Every outcome, refusals included, becomes that receipt.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.app import live_update as lu

log = logging.getLogger(__name__)

SOURCES = frozenset({"desktop", "remote"})
HOLD_REASON = "live-update"
#: An intent with no updater result after this long is abandoned, so it cannot block every later update.
STALE_INTENT_SECONDS = 1800.0


class UpdateHoldQueue(Protocol):
    def hold_dispatch_for_update(self, *, reason: str) -> bool: ...

    def release_update_hold(self) -> bool: ...


@dataclass(frozen=True)
class Outcome:
    status: str  # "restarting" | "refused" | "already_current"
    reason: str = ""
    old_sha: str = ""
    target_sha: str = ""
    detail: str = ""


def _utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class LiveUpdateService:
    def __init__(
        self,
        *,
        store: lu.LiveUpdateStore,
        preflight: Callable[[str | None], lu.Preflight],
        queue: UpdateHoldQueue | None,
        busy: Callable[[], bool],
        launch_updater: Callable[[lu.UpdaterLaunch], None],
        repo_root: Path,
        pid: int,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        max_wait_seconds: float = 3600.0,
        rate_limit_seconds: float = 600.0,
        poll_seconds: float = 5.0,
        git_lock: threading.Lock | None = None,
    ) -> None:
        self.store = store
        self.repo_root = Path(repo_root)
        self._preflight = preflight
        self._queue = queue
        self._busy = busy
        self._launch = launch_updater
        self._pid = int(pid)
        self._clock = clock
        self._sleep = sleep
        self._max_wait = float(max_wait_seconds)
        self._rate_limit = float(rate_limit_seconds)
        self._poll = float(poll_seconds)
        self._lock = threading.Lock()
        #: Serializes Git on the live checkout with the phone status probe (LAUNCH-UPDATE-2), so two fetches never
        #: race for the same ref lock.
        self.git_lock = git_lock or threading.Lock()
        self._running = False
        self._exit_requested = threading.Event()
        self.phase = ""

    # -- owner switch -----------------------------------------------------------------------------------------------

    def allow_remote(self) -> bool:
        settings = self.store.read("settings.json") or {}
        return settings.get("allow_remote_update") is True

    def set_allow_remote(self, allowed: bool) -> None:
        settings = self.store.read("settings.json") or {}
        settings["allow_remote_update"] = bool(allowed)
        self.store.write("settings.json", settings)

    # -- state ------------------------------------------------------------------------------------------------------

    @property
    def exit_requested(self) -> bool:
        return self._exit_requested.is_set()

    @property
    def in_progress(self) -> bool:
        with self._lock:
            return self._running or self.store.read("intent.json") is not None

    def last_result(self) -> dict[str, Any] | None:
        return self.store.read("last_result.json")

    def check(self) -> lu.Preflight:
        """The preflight alone (fetches origin; changes nothing else)."""

        with self.git_lock:
            return self._preflight(None)

    # -- update -----------------------------------------------------------------------------------------------------

    def update(
        self, *, source: str, expected_sha: str | None, record_id: str | None = None
    ) -> Outcome:
        if source not in SOURCES:
            raise ValueError(source)
        if not self.exit_requested:
            self.collect_result()  # a finished or abandoned earlier update must not block this one
        with self._lock:
            if self._running or self.store.read("intent.json") is not None:
                return self._refused(source, record_id, lu.UPDATE_IN_PROGRESS, record=False)
            self._running = True
        restarting = False
        try:
            outcome = self._update(source, expected_sha, record_id)
            restarting = outcome.status == "restarting"
            return outcome
        finally:
            if not restarting:
                with self._lock:
                    self._running = False
                self.phase = ""

    def _update(self, source: str, expected_sha: str | None, record_id: str | None) -> Outcome:
        if source == "remote":
            if expected_sha is None:  # a phone approves the commit it was shown (D3)
                return self._refused(source, record_id, lu.INVALID_REQUEST)
            if not self.allow_remote():
                return self._refused(source, record_id, lu.REMOTE_UPDATE_DISABLED)
            last = self.store.read("last_result.json") or {}
            restart_at = last.get("restart_at")
            if (
                isinstance(restart_at, int | float)
                and self._clock() - restart_at < self._rate_limit
            ):
                return self._refused(source, record_id, lu.RATE_LIMITED)
        if self._queue is None:
            return self._refused(source, record_id, lu.QUEUE_UNAVAILABLE)
        self.phase = "checking"
        with self.git_lock:
            check = self._preflight(expected_sha)
        if check.reason == lu.ALREADY_CURRENT:
            self._record(
                source, record_id, "already_current", check.reason, check.old_sha, check.target_sha
            )
            return Outcome("already_current", check.reason, check.old_sha, check.target_sha)
        if not check.ok:
            return self._refused(
                source, record_id, check.reason, check.old_sha, check.target_sha, check.detail
            )

        self.phase = "waiting for the running job"
        self._queue.hold_dispatch_for_update(reason=HOLD_REASON)
        if not self._wait_idle():
            self._release()
            return self._refused(
                source, record_id, lu.BUSY_TIMEOUT, check.old_sha, check.target_sha
            )

        now = self._clock()
        intent = {
            "update_id": uuid.uuid4().hex,
            "source": source,
            "record_id": record_id,
            "old_sha": check.old_sha,
            "target_sha": check.target_sha,
            "commits_ahead": check.commits_ahead,
            "pid": self._pid,
            "requested_at": _utc(now),
            "restart_at": now,
        }
        self.phase = "starting the updater"
        try:
            self.store.write("intent.json", intent)
            self._launch(
                lu.UpdaterLaunch(
                    self.repo_root, self.store.directory, self._pid, check.old_sha, check.target_sha
                )
            )
        except (OSError, ValueError) as error:
            self.store.remove("intent.json")
            self._release()
            log.warning("Live update: the updater could not be started: %s", error)
            return self._refused(
                source, record_id, lu.UPDATER_FAILED, check.old_sha, check.target_sha, str(error)
            )
        log.info(
            "Live update: restarting to move %s -> %s", check.old_sha[:12], check.target_sha[:12]
        )
        self.phase = "restarting"
        self._exit_requested.set()
        return Outcome("restarting", "", check.old_sha, check.target_sha)

    def _wait_idle(self) -> bool:
        deadline = self._clock() + self._max_wait
        while self._busy():
            if self._clock() >= deadline:
                return False
            self._sleep(self._poll)
        return True

    def _release(self) -> None:
        if self._queue is not None:
            self._queue.release_update_hold()

    def _record(
        self,
        source: str,
        record_id: str | None,
        status: str,
        reason: str,
        old_sha: str = "",
        target_sha: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        receipt = {
            "source": source,
            "record_id": record_id,
            "status": status,
            "reason": reason,
            "old_sha": old_sha,
            "new_sha": old_sha,
            "target_sha": target_sha,
            "detail": detail,
            "finished_at": _utc(self._clock()),
        }
        previous = self.store.read("last_result.json") or {}
        if "restart_at" in previous:
            receipt["restart_at"] = previous["restart_at"]  # the rate limit counts restarts only
        try:
            self.store.write("last_result.json", receipt)
        except OSError as error:
            log.warning("Live update: the receipt could not be saved: %s", error)
        return receipt

    def _refused(
        self,
        source: str,
        record_id: str | None,
        reason: str,
        old_sha: str = "",
        target_sha: str = "",
        detail: str = "",
        *,
        record: bool = True,
    ) -> Outcome:
        if record:
            self._record(source, record_id, "refused", reason, old_sha, target_sha, detail)
        log.info("Live update refused: %s", reason)
        return Outcome("refused", reason, old_sha, target_sha, detail)

    # -- after a restart -------------------------------------------------------------------------------------------

    def mark_started(self, head_sha: str) -> None:
        """The updater's health signal: written only while an update is pending."""

        intent = self.store.read("intent.json")
        if intent is None:
            return
        self.store.write(
            "started.json",
            {"update_id": intent.get("update_id"), "head_sha": head_sha, "pid": self._pid},
        )

    def collect_result(self) -> dict[str, Any] | None:
        """The receipt once the updater has written its result for the pending intent; clears the pending files."""

        intent = self.store.read("intent.json")
        if intent is None:
            return None
        result = self.store.read("result.json")
        if result is None or result.get("update_id") != intent.get("update_id"):
            restart_at = intent.get("restart_at")
            if (
                not isinstance(restart_at, int | float)
                or self._clock() - restart_at < STALE_INTENT_SECONDS
            ):
                return None
            result = {
                "status": "refused",
                "reason": lu.UPDATER_LOST,
                "new_sha": "",
                "finished_at": _utc(self._clock()),
            }
        receipt = {**intent, **result}
        receipt.pop("pid", None)
        self.store.write("last_result.json", receipt)
        for name in ("result.json", "started.json", "intent.json"):
            self.store.remove(name)
        log.info(
            "Live update result: %s %s (%s -> %s)",
            receipt.get("status"),
            receipt.get("reason") or "",
            str(receipt.get("old_sha"))[:12],
            str(receipt.get("new_sha"))[:12],
        )
        return receipt
