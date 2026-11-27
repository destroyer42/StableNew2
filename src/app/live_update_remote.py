"""The phone side of a live update, on the PC (LAUNCH-UPDATE-2): the ``pc_status`` publish and ``admin_request``.

Design and owner decisions: ``docs/work_packages/LAUNCH-UPDATE_remote_restart.md`` (D2, D3). This module joins the
review gateway sync worker to the LAUNCH-UPDATE-1 service; it decides nothing about the checkout itself:

* :class:`CheckoutProbe` keeps the live checkout's ``HEAD``, the fetched ``origin/main`` and how many commits it is
  ahead. It fetches at most every 15 minutes, on its own worker thread, and never while the update service holds the
  Git lock, so the sync cycle never waits on the network.
* :class:`RemoteUpdate` is the ``AdminRequests`` handler the record applier calls for each ``admin_request``. The
  device's ``admin`` grant has already been checked against this PC's own ledger. It runs the request through
  :meth:`LiveUpdateService.update` with ``source="remote"`` (the owner's "Allow remote update" switch, the rate limit,
  the preflight with ``target_moved``, the drain, the hand-off and the receipt are all LAUNCH-UPDATE-1's), on a worker
  thread, because the drain can take an hour. Until the update has a receipt the record stays unanswered, and the
  gateway re-delivers it every cycle; after the restart the new app answers it from ``last_result.json``.
* :meth:`RemoteUpdate.status_payload` builds the ``pc_status`` the gateway shows to admin phones: commit ids and
  counts only (D3).

The only value taken from a request is ``expected_sha``, already validated as 40 lowercase hex characters by the
codec and checked by the preflight against the PC's own fetch; no ref, path, remote or option comes from the phone.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.app import live_update as lu
from src.app.live_update_service import LiveUpdateService, Outcome
from src.app.review_gateway_apply import Applied
from src.app.review_gateway_protocol import AdminRecord, ProtocolError, pc_status, update_receipt

log = logging.getLogger(__name__)

FETCH_INTERVAL_SECONDS = 900.0  # D3: origin is fetched at most every 15 minutes for the status
RETRY_INTERVAL_SECONDS = 120.0  # after a failed fetch
#: A request the PC first sees this long after the tap is refused: the owner asked for an update then, not now.
MAX_REQUEST_AGE_SECONDS = 3600.0
REQUEST_EXPIRED = "request_expired"
_MAX_ANSWERS = 50

Spawn = Callable[[Callable[[], None], str], None]


def _registry_spawn(target: Callable[[], None], name: str) -> None:
    from src.utils.thread_registry import get_thread_registry

    get_thread_registry().spawn(target=target, name=name, purpose=name)


@dataclass(frozen=True)
class CheckoutState:
    head_sha: str = ""
    origin_main_sha: str = ""
    commits_behind: int | None = None
    fetched_at: datetime | None = None


class CheckoutProbe:
    """The live checkout's commits for ``pc_status``; Git runs only on a worker thread, under the shared lock."""

    def __init__(
        self,
        git: lu.GitRunner,
        *,
        git_lock: threading.Lock,
        spawn: Spawn = _registry_spawn,
        clock: Callable[[], float] = time.time,
        fetch_interval: float = FETCH_INTERVAL_SECONDS,
        retry_interval: float = RETRY_INTERVAL_SECONDS,
    ) -> None:
        self._git = git
        self._git_lock = git_lock
        self._spawn = spawn
        self._clock = clock
        self._fetch_interval = fetch_interval
        self._retry_interval = retry_interval
        self._lock = threading.Lock()
        self._state = CheckoutState()
        self._next_at = 0.0
        self._refreshing = False

    def snapshot(self) -> CheckoutState:
        """The last known state; starts a background refresh when it is due. Never waits on Git."""

        with self._lock:
            due = not self._refreshing and self._clock() >= self._next_at
            if due:
                self._refreshing = True
            state = self._state
        if due:
            try:
                self._spawn(self._refresh, "Live update status")
            except Exception:  # noqa: BLE001 - a status that cannot refresh keeps its last value
                log.exception("Live update status: the refresh could not be started")
                with self._lock:
                    self._refreshing = False
                    self._next_at = self._clock() + self._retry_interval
        return state

    def invalidate(self) -> None:
        """Refresh on the next snapshot (after an update attempt, which fetched origin itself)."""

        with self._lock:
            self._next_at = 0.0

    def refresh(self) -> CheckoutState:
        """One refresh in the calling thread (the worker; public for tests)."""

        with self._lock:
            self._refreshing = True
        self._refresh()
        with self._lock:
            return self._state

    def _refresh(self) -> None:
        fetched = False
        try:
            if not self._git_lock.acquire(blocking=False):
                return  # an update is using Git; try again shortly
            try:
                state, fetched = self._read()
            finally:
                self._git_lock.release()
            with self._lock:
                self._state = state
        except Exception:  # noqa: BLE001 - the status must never stop the sync worker
            log.exception("Live update status: the checkout could not be read")
        finally:
            with self._lock:
                self._refreshing = False
                wait = self._fetch_interval if fetched else self._retry_interval
                self._next_at = self._clock() + wait

    def _read(self) -> tuple[CheckoutState, bool]:
        head = self._git(["rev-parse", "HEAD"])
        head_sha = head.out if head.code == 0 and lu.valid_sha(head.out) else ""
        previous = self._state
        fetch = self._git(["fetch", "--no-tags", "--quiet", "origin", "main"])
        fetched = fetch.code == 0
        remote = self._git(["rev-parse", "refs/remotes/origin/main"])
        origin_sha = remote.out if remote.code == 0 and lu.valid_sha(remote.out) else ""
        behind: int | None = None
        if head_sha and origin_sha:
            count = self._git(["rev-list", "--count", f"{head_sha}..{origin_sha}"])
            if count.code == 0 and count.out.isdigit():
                behind = int(count.out)
        fetched_at = datetime.fromtimestamp(self._clock(), UTC) if fetched else previous.fetched_at
        return CheckoutState(head_sha, origin_sha, behind, fetched_at), fetched


def _queue_view(queue_state: Callable[[], tuple[str, int]]) -> tuple[str, int]:
    try:
        state, queued = queue_state()
    except Exception:  # noqa: BLE001 - shown as unknown rather than failing the status
        return "unknown", 0
    return state, max(0, int(queued))


_PHASES = {
    "checking": "checking",
    "waiting for the running job": "waiting_for_job",
    "starting the updater": "restarting",
    "restarting": "restarting",
}


class RemoteUpdate:
    """``AdminRequests`` for the record applier, and the source of the ``pc_status`` publish."""

    def __init__(
        self,
        service: LiveUpdateService,
        *,
        checkout: CheckoutProbe,
        queue_state: Callable[[], tuple[str, int]],
        spawn: Spawn = _registry_spawn,
        clock: Callable[[], float] = time.time,
        max_request_age: float = MAX_REQUEST_AGE_SECONDS,
    ) -> None:
        self.service = service
        self.checkout = checkout
        self._queue_state = queue_state
        self._spawn = spawn
        self._clock = clock
        self._max_age = float(max_request_age)
        self._lock = threading.Lock()
        self._running: dict[str, str] = {}  # record id -> expected sha
        self._answers: OrderedDict[str, Applied] = OrderedDict()

    # -- admin_request -----------------------------------------------------------------------------------------------

    def handle(self, record: AdminRecord) -> Applied | None:
        """The final answer for ``record``, or ``None`` while its update is under way (it is asked again later)."""

        record_id = record.record_id
        last = self.service.last_result() or {}
        if last.get("record_id") == record_id:
            return self._answer(record_id, last)
        with self._lock:
            if record_id in self._answers:
                return self._answers[record_id]
            if record_id in self._running:
                return None
        intent = self.service.store.read("intent.json") or {}
        if intent.get("record_id") == record_id:
            return None  # the restart for this request is under way; the next app answers it
        if self._clock() - record.created_at.timestamp() > self._max_age:
            log.info("Live update: a remote request was refused as expired")
            return Applied(
                record_id,
                "refused",
                REQUEST_EXPIRED,
                {
                    "update": {
                        "status": "refused",
                        "reason_code": REQUEST_EXPIRED,
                        "source": "remote",
                    }
                },
            )
        with self._lock:
            self._running[record_id] = record.expected_sha
        try:
            self._spawn(lambda: self._run(record), "Live update (remote)")
        except Exception:  # noqa: BLE001
            log.exception("Live update: the remote request could not be started")
            with self._lock:
                self._running.pop(record_id, None)
            return Applied(
                record_id,
                "refused",
                lu.UPDATER_FAILED,
                {"update": {"status": "refused", "reason_code": lu.UPDATER_FAILED}},
            )
        return None

    def _run(self, record: AdminRecord) -> None:
        record_id = record.record_id
        try:
            outcome = self.service.update(
                source="remote", expected_sha=record.expected_sha, record_id=record_id
            )
        except Exception:  # noqa: BLE001 - answered as a failure instead of leaving the phone waiting forever
            log.exception("Live update: the remote update failed")
            outcome = Outcome("refused", lu.UPDATER_FAILED)
        finally:
            self.checkout.invalidate()
        with self._lock:
            self._running.pop(record_id, None)
            if outcome.status == "restarting":
                return  # the app is closing; the next start answers from last_result.json
        last = self.service.last_result() or {}
        if last.get("record_id") == record_id:
            answer = self._answer(record_id, last)
        else:  # refused without a receipt of its own (another update was already in progress)
            answer = self._answer(
                record_id,
                {
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "source": "remote",
                    "old_sha": outcome.old_sha,
                    "new_sha": outcome.old_sha,
                    "target_sha": outcome.target_sha,
                },
            )
        with self._lock:
            self._answers[record_id] = answer
            while len(self._answers) > _MAX_ANSWERS:
                self._answers.popitem(last=False)

    @staticmethod
    def _answer(record_id: str, receipt: Mapping[str, Any]) -> Applied:
        try:
            update = update_receipt(receipt)
        except ProtocolError:
            log.warning("Live update: a receipt outside the closed lists was answered as lost")
            update = {"status": "refused", "reason_code": lu.UPDATER_LOST}
        if update["status"] == "applied":
            return Applied(record_id, "applied", receipt={"update": update})
        return Applied(record_id, "refused", update["reason_code"], {"update": update})

    # -- pc_status ---------------------------------------------------------------------------------------------------

    def status_payload(self) -> dict[str, Any] | None:
        """The ``pc_status`` to publish now; ``None`` when it cannot be built (it is then simply not sent)."""

        try:
            state = self.checkout.snapshot()
            queue_state, queued = _queue_view(self._queue_state)
            intent = self.service.store.read("intent.json") or {}
            with self._lock:
                running = next(iter(self._running), "")
            record_id = running or str(intent.get("record_id") or "")
            in_progress = bool(running) or self.service.in_progress
            phase = _PHASES.get(self.service.phase, "")
            if in_progress and not phase and intent:
                phase = "restarting"
            return pc_status(
                head_sha=state.head_sha,
                origin_main_sha=state.origin_main_sha,
                commits_behind=state.commits_behind,
                fetched_at=state.fetched_at,
                queue_state=queue_state,
                queued=queued,
                remote_update_enabled=self.service.allow_remote(),
                update_state="in_progress" if in_progress else "idle",
                update_phase=phase if in_progress else "",
                update_record_id=record_id if in_progress else "",
                last_result=self.service.last_result(),
            )
        except (ProtocolError, OSError, ValueError):
            log.warning("Live update: the PC status could not be built", exc_info=True)
            return None
