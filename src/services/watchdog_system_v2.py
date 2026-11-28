"""Observe runtime progress and queue activity for stalls and report diagnosed violations."""

import importlib
import logging
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.services.queue_idle_report import QueueIdleReporter
from src.utils.contention_lock import held_locks
from src.utils.logger import LogContext, log_with_ctx
from src.utils.stack_sites import describe_stack

logger = logging.getLogger(__name__)

_NEVER_TRIGGERED = float("-inf")

#: Frames kept per sampled stack (innermost first), and distinct stacks reported per stall episode.
_STACK_DEPTH = 16
_STACKS_PER_EPISODE = 4
#: Other threads' sites reported for samples where the Tk thread showed only ``mainloop``.
_OTHER_THREADS = 32
#: A lock held at least this long while the Tk heartbeat is late is listed in the stall record.
_HELD_LOCK_S = 0.5


@dataclass
class _StackSample:
    frames: tuple[str, ...]
    samples: int = 0
    first_age_s: float = 0.0
    last_age_s: float = 0.0


@dataclass
class _UiStallEpisode:
    """The Tk-thread call sites sampled while one heartbeat gap lasted."""

    operation: str | None
    last_ui_action: str | None
    peak_age_s: float = 0.0
    sample_count: int = 0
    stacks: dict[tuple[str, ...], _StackSample] = field(default_factory=dict)
    started_at: float = 0.0
    #: ``(tk_thread_cpu_s, process_cpu_s)`` when sampling began.
    cpu_start: tuple[float, float] | None = None
    #: Other threads' call sites, counted only for samples with no Python frame above ``mainloop``.
    other_threads: dict[str, int] = field(default_factory=dict)
    #: ``(disk MB written, disk write ms, process MB written)`` when sampling began.
    io_start: tuple[float, float, float] | None = None
    #: Longest hold seen per ``(lock, thread, site)`` while the heartbeat was late.
    held_locks: dict[tuple[str, str, str], float] = field(default_factory=dict)


class SystemWatchdogV2:
    # Tune these as needed
    # UI heartbeat must come from the Tk main loop only. Background progress work
    # can update runner activity, but it must not mask a frozen GUI.
    UI_STALL_S = 10.0
    # The WebUI executor independently interrupts no-progress generations at
    # 90 seconds. Runner diagnostics use the same bounded baseline instead of
    # treating a short backend call as evidence of a queue stall.
    RUNNER_STALL_S = 90.0
    _SVD_STAGE_DETAIL_STALL_S = {
        "loading_model": 300.0,
        "preprocess": 120.0,
        "inference": 300.0,
        "postprocess": 120.0,
        "encoding": 120.0,
    }
    LOOP_PERIOD_S = 0.5
    # A heartbeat gap this long starts attributing the Tk thread's call site (UI_STALL_S only decides when a
    # diagnostics ZIP is worth writing). Ordinary gaps below this are Tk doing its work.
    UI_SAMPLE_AFTER_S = 1.0
    # The watchdog thread itself waking this much later than its period means the process, not one Tk callback, was
    # held up: a call that keeps the GIL, or a suspended process. The heartbeat check cannot see that (the Tk thread
    # may well beat first when the GIL comes back), so it is reported on its own.
    LOOP_STARVED_AFTER_S = 1.5

    # Cooldowns prevent spam while a condition remains true
    COOLDOWN_S = {
        "ui_heartbeat_stall": 120.0,
        "queue_runner_stall": 90.0,
    }
    _ACTIVE_LOCK = threading.Lock()
    _ACTIVE_THREAD: threading.Thread | None = None

    def __init__(
        self,
        app_controller,
        diagnostics_service,
        *,
        check_interval_s: float | None = None,
        ui_thread_ident: int | None = None,
    ):
        self.app = app_controller
        self.diagnostics = diagnostics_service
        # The thread that owns Tk. Captured at construction (the controller attaches the watchdog from the Tk
        # thread); tests inject a stand-in.
        self._ui_thread_ident = (
            ui_thread_ident if ui_thread_ident is not None else threading.main_thread().ident
        )
        self._ui_episode: _UiStallEpisode | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._lock = threading.Lock()
        # "Never triggered" is -inf, not 0.0: time.monotonic() is host uptime, so a 0.0 default
        # would suppress a first trigger for one cooldown after boot.
        self._last_trigger_ts: dict[str, float] = defaultdict(lambda: _NEVER_TRIGGERED)
        self._in_flight: dict[str, bool] = defaultdict(lambda: False)
        self._runner_stall_episode_active = False
        self._queue_idle = QueueIdleReporter()
        self._observed_runner_job_id: str | None = None
        self._last_runtime_progress_signature: tuple[object, ...] | None = None
        self._last_runtime_progress_ts: float | None = None
        self._loop_period = (
            float(check_interval_s) if check_interval_s is not None else float(self.LOOP_PERIOD_S)
        )

    def start(self) -> None:
        """Start the watchdog monitoring thread.

        PR-WATCHDOG-001: Changed to non-daemon for clean shutdown.
        """
        with self._ACTIVE_LOCK:
            if self._thread and self._thread.is_alive():
                return
            if self.__class__._ACTIVE_THREAD and self.__class__._ACTIVE_THREAD.is_alive():
                return
        # PR-WATCHDOG-001: Changed from daemon=True to daemon=False
        t = threading.Thread(
            target=self._loop,
            daemon=False,  # Changed for clean shutdown
            name="SystemWatchdogV2",
        )
        t.start()
        self._thread = t
        with self._ACTIVE_LOCK:
            self.__class__._ACTIVE_THREAD = t

    def begin_shutdown(self) -> None:
        self._stop.set()

    def stop(self, timeout: float = 10.0) -> bool:
        """Stop monitoring within the given budget. Its diagnostics workers are tracked separately."""
        self.begin_shutdown()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                return False
        with self._ACTIVE_LOCK:
            if self.__class__._ACTIVE_THREAD is thread:
                self.__class__._ACTIVE_THREAD = None
        return True

    def _loop(self) -> None:
        """Main watchdog loop - monitors system health.

        PR-WATCHDOG-001: Added shutdown check to prevent diagnostics during shutdown.
        """
        woke_at = time.monotonic()
        while not self._stop.is_set():
            try:
                self._note_loop_gap(time.monotonic() - woke_at)
                woke_at = time.monotonic()
                # PR-WATCHDOG-001: Skip checks if shutdown requested
                if hasattr(self.app, "_is_shutting_down") and self.app._is_shutting_down:
                    break
                if not threading.main_thread().is_alive():
                    break
                self._check()
            except Exception:
                # watchdog must never crash the app
                pass
            time.sleep(self._loop_period)

    def _check(self) -> None:
        now = time.monotonic()
        self._queue_idle.observe(
            now,
            getattr(self.app, "job_service", None),
            getattr(getattr(self.app, "pipeline_controller", None), "_job_controller", None),
        )
        heartbeat_ts = getattr(self.app, "last_ui_heartbeat_ts", None)
        if heartbeat_ts:
            ui_age = now - float(heartbeat_ts)
            self._observe_ui_stall(ui_age)
            if ui_age > self.UI_STALL_S:
                self._trigger("ui_heartbeat_stall", now)

        if self._queue_running_but_stalled(now):
            if not self._runner_stall_episode_active:
                self._runner_stall_episode_active = True
                self._trigger("queue_runner_stall", now)
        else:
            if self._runner_stall_episode_active:
                self._last_trigger_ts["queue_runner_stall"] = _NEVER_TRIGGERED
            self._runner_stall_episode_active = False

    def _note_loop_gap(self, gap_s: float) -> bool:
        """Report one watchdog iteration that started much later than ``_loop_period`` allows."""

        late_by = gap_s - self._loop_period
        if late_by < self.LOOP_STARVED_AFTER_S:
            return False
        heartbeat_ts = getattr(self.app, "last_ui_heartbeat_ts", None)
        try:
            frames = sys._current_frames()  # one consistent snapshot of every thread
            thread_sites = {
                thread.name: (
                    describe_stack(
                        frames.get(thread.ident) if thread.ident is not None else None, depth=3
                    )
                    or ("<no frame>",)
                )
                for thread in threading.enumerate()
            }
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            thread_sites = {}
        log_with_ctx(
            logger,
            logging.WARNING,
            "Watchdog thread starved",
            ctx=LogContext(subsystem="watchdog", stage="watchdog_starved"),
            extra_fields={
                "late_by_s": round(late_by, 2),
                "ended_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "ui_heartbeat_age_s": (
                    round(time.monotonic() - float(heartbeat_ts), 2) if heartbeat_ts else None
                ),
                "thread_sites": {
                    name: " <- ".join(frames) for name, frames in thread_sites.items()
                },
                "system": self._system_context(),
            },
        )
        return True

    @staticmethod
    def _system_context() -> dict[str, object]:
        """Machine-level context that tells a GIL stall from a whole-machine one (CPU, memory, disk since boot)."""

        try:
            # Imported by name: the optional dependency has no stubs in every environment.
            psutil = importlib.import_module("psutil")

            memory = psutil.virtual_memory()
            disk = psutil.disk_io_counters()
            process = psutil.Process()
            return {
                # A 0.1 s sample (this runs only on a starvation event, on the watchdog thread).
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "available_memory_mb": int(memory.available / (1024 * 1024)),
                "process_cpu_seconds": round(sum(process.cpu_times()[:2]), 1),
                "process_threads": process.num_threads(),
                "disk_read_mb": int(disk.read_bytes / (1024 * 1024)) if disk else None,
                "disk_write_mb": int(disk.write_bytes / (1024 * 1024)) if disk else None,
            }
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            return {}

    def _capture_ui_stack(self) -> tuple[str, ...]:
        """The Tk thread's current stack, innermost first; empty when the thread is gone."""

        ident = self._ui_thread_ident
        if ident is None:
            return ()
        try:
            frame = sys._current_frames().get(ident)
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            return ()
        return describe_stack(frame, depth=_STACK_DEPTH)

    def _observe_ui_stall(self, ui_age: float) -> None:
        """Attribute a stalled heartbeat to the Tk-thread call site, one episode at a time.

        While the heartbeat is older than ``UI_SAMPLE_AFTER_S`` every check samples the Tk thread's stack (cheap and
        read-only). When the heartbeat resumes, the episode is reported as ONE structured record naming the distinct
        call sites sampled, most frequent first. Nothing is written for a gap that never reached the threshold.
        """

        if ui_age >= self.UI_SAMPLE_AFTER_S:
            episode = self._ui_episode
            if episode is None:
                episode = self._ui_episode = _UiStallEpisode(
                    operation=getattr(self.app, "current_operation_label", None),
                    last_ui_action=getattr(self.app, "last_ui_action", None),
                    started_at=time.monotonic(),
                    cpu_start=self._cpu_times(),
                    io_start=self._io_counters(),
                )
            episode.peak_age_s = max(episode.peak_age_s, ui_age)
            episode.sample_count += 1
            for hold in held_locks(_HELD_LOCK_S):
                key = (str(hold["lock"]), str(hold["thread"]), str(hold["site"]))
                episode.held_locks[key] = max(
                    episode.held_locks.get(key, 0.0), float(hold["held_s"])
                )
            frames = self._capture_ui_stack()
            if frames:
                sample = episode.stacks.get(frames)
                if sample is None:
                    sample = episode.stacks[frames] = _StackSample(frames, first_age_s=ui_age)
                sample.samples += 1
                sample.last_age_s = ui_age
                if frames[0].endswith(" in mainloop"):
                    for site in self._other_thread_sites():
                        episode.other_threads[site] = episode.other_threads.get(site, 0) + 1
            return
        episode, self._ui_episode = self._ui_episode, None
        if episode is not None:
            self._report_ui_stall(episode, self._cpu_times(), self._io_counters())

    def _cpu_times(self) -> tuple[float, float] | None:
        """``(Tk thread CPU seconds, process CPU seconds)``; ``None`` when they cannot be read."""

        try:
            psutil = importlib.import_module("psutil")
            native = next(
                t.native_id for t in threading.enumerate() if t.ident == self._ui_thread_ident
            )
            process = psutil.Process()
            thread = next(t for t in process.threads() if t.id == native)
            return (
                float(thread.user_time + thread.system_time),
                float(sum(process.cpu_times()[:2])),
            )
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            return None

    def _io_counters(self) -> tuple[float, float, float] | None:
        """``(disk MB written, disk write ms, process MB written)``; ``None`` when they cannot be read."""

        try:
            psutil = importlib.import_module("psutil")
            disk = psutil.disk_io_counters()
            process = psutil.Process().io_counters()
            return (
                disk.write_bytes / (1024 * 1024),
                float(disk.write_time),
                process.write_bytes / (1024 * 1024),
            )
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            return None

    def _other_thread_sites(self) -> list[str]:
        """``thread name: innermost frames`` for every thread but the Tk thread and this watchdog."""

        try:
            frames = sys._current_frames()
            skip = {self._ui_thread_ident, threading.get_ident()}
            return [
                f"{thread.name}: " + " <- ".join(describe_stack(frames.get(thread.ident), depth=3))
                for thread in threading.enumerate()
                if thread.ident is not None and thread.ident not in skip and thread.ident in frames
            ]
        except Exception:  # noqa: BLE001 - diagnostics must never break the watchdog
            return []

    @staticmethod
    def _report_ui_stall(
        episode: _UiStallEpisode,
        cpu_end: tuple[float, float] | None,
        io_end: tuple[float, float, float] | None = None,
    ) -> None:
        ranked = sorted(episode.stacks.values(), key=lambda item: item.samples, reverse=True)
        stacks = [
            {
                "samples": item.samples,
                "first_age_s": round(item.first_age_s, 2),
                "last_age_s": round(item.last_age_s, 2),
                # The innermost frame is usually stdlib (a lock wait, ``realpath``, ``fetchall``); ``site`` is the
                # innermost frame inside StableNew, i.e. the call site to fix.
                "site": next((f for f in item.frames if f.startswith("src/")), item.frames[0]),
                "innermost": item.frames[0],
                "stack": list(item.frames),
            }
            for item in ranked[:_STACKS_PER_EPISODE]
        ]
        # CPU used while sampling: Tk CPU near ``observed_s`` means Tcl was busy; near zero means it was waiting
        # (another thread holding the GIL, a Windows move/menu loop or a paused process).
        tk_cpu = process_cpu = None
        if episode.cpu_start is not None and cpu_end is not None:
            tk_cpu = round(cpu_end[0] - episode.cpu_start[0], 2)
            process_cpu = round(cpu_end[1] - episode.cpu_start[1], 2)
        others = sorted(episode.other_threads.items(), key=lambda item: item[1], reverse=True)
        # Disk activity while sampling: a stall with little CPU and a busy disk is a wait on storage.
        io = None
        if episode.io_start is not None and io_end is not None:
            written, busy_ms, own = (
                end - start for start, end in zip(episode.io_start, io_end, strict=True)
            )
            io = {
                "disk_write_mb": round(written, 1),
                "disk_write_ms": round(busy_ms, 1),
                "process_write_mb": round(own, 1),
            }
        holds = sorted(episode.held_locks.items(), key=lambda item: item[1], reverse=True)
        log_with_ctx(
            logger,
            logging.WARNING,
            "UI thread stalled",
            ctx=LogContext(subsystem="watchdog", stage="ui_stall"),
            extra_fields={
                "stall_s": round(episode.peak_age_s, 2),
                "ended_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "samples": episode.sample_count,
                "operation": episode.operation,
                "last_ui_action": episode.last_ui_action,
                "stacks": stacks,
                "observed_s": round(time.monotonic() - episode.started_at, 2),
                "tk_cpu_s": tk_cpu,
                "process_cpu_s": process_cpu,
                "other_threads": [
                    {"samples": count, "site": site} for site, count in others[:_OTHER_THREADS]
                ],
                "held_locks": [
                    {"lock": lock, "thread": thread, "site": site, "held_s": held}
                    for (lock, thread, site), held in holds[:_STACKS_PER_EPISODE]
                ],
                "io": io,
            },
        )

    def _queue_running_but_stalled(self, now: float) -> bool:
        runner_ts = getattr(self.app, "last_runner_activity_ts", None)
        if not runner_ts:
            return False
        if not (hasattr(self.app, "has_running_jobs") and bool(self.app.has_running_jobs())):
            self._observed_runner_job_id = None
            self._last_runtime_progress_signature = None
            self._last_runtime_progress_ts = None
            return False

        owner_job_id, _owner_job = self._execution_owner()
        runtime_status, runtime_progress_ts = self._observe_runtime_progress(
            now,
            owner_job_id,
        )
        activity_ts = float(runner_ts)
        if runtime_progress_ts is not None:
            activity_ts = max(activity_ts, runtime_progress_ts)
        threshold = self._runner_stall_threshold(runtime_status)
        return (now - activity_ts) > threshold

    def _execution_owner(self) -> tuple[str | None, object | None]:
        """Return the exact job currently owned by SingleNodeJobRunner."""

        service = getattr(self.app, "job_service", None)
        runner = getattr(service, "runner", None)
        job = getattr(runner, "current_job", None)
        job_id = getattr(job, "job_id", None)
        return (str(job_id) if job_id else None, job)

    def _latest_runtime_status(self):
        getter = getattr(self.app, "_get_latest_runtime_status", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
        return getattr(self.app, "_last_runtime_status", None)

    def _observe_runtime_progress(
        self,
        now: float,
        owner_job_id: str | None,
    ) -> tuple[object | None, float | None]:
        """Track only meaningful updates for the job the runner actually owns."""

        if owner_job_id is None:
            self._observed_runner_job_id = None
            self._last_runtime_progress_signature = None
            self._last_runtime_progress_ts = None
            return None, None

        status = self._latest_runtime_status()
        status_job_id = getattr(status, "job_id", None)
        if str(status_job_id or "") != owner_job_id:
            if self._observed_runner_job_id != owner_job_id:
                self._observed_runner_job_id = owner_job_id
                self._last_runtime_progress_signature = None
                self._last_runtime_progress_ts = None
            return None, self._last_runtime_progress_ts

        signature = (
            owner_job_id,
            getattr(status, "current_stage", None),
            getattr(status, "stage_detail", None),
            getattr(status, "current_step", None),
            getattr(status, "total_steps", None),
            getattr(status, "progress", None),
        )
        if self._observed_runner_job_id != owner_job_id:
            self._observed_runner_job_id = owner_job_id
            self._last_runtime_progress_signature = signature
            self._last_runtime_progress_ts = now
        elif signature != self._last_runtime_progress_signature:
            self._last_runtime_progress_signature = signature
            self._last_runtime_progress_ts = now
        return status, self._last_runtime_progress_ts

    def _runner_stall_threshold(self, runtime_status: object | None) -> float:
        if runtime_status is None:
            return self.RUNNER_STALL_S
        stage = str(getattr(runtime_status, "current_stage", "") or "").strip().lower()
        detail = str(getattr(runtime_status, "stage_detail", "") or "").strip().lower()
        if stage == "svd_native":
            return self._SVD_STAGE_DETAIL_STALL_S.get(detail, self.RUNNER_STALL_S)
        return self.RUNNER_STALL_S

    def _trigger(self, reason: str, now: float) -> None:
        if not threading.main_thread().is_alive():
            return
        if hasattr(self.app, "_is_shutting_down") and self.app._is_shutting_down:
            return
        cooldown = float(self.COOLDOWN_S.get(reason, 30.0))

        with self._lock:
            if self._in_flight[reason]:
                return
            if (now - self._last_trigger_ts[reason]) < cooldown:
                return

            self._in_flight[reason] = True
            self._last_trigger_ts[reason] = now

        # PR-HB-003: Enhanced context for heartbeat stall diagnostics
        ui_heartbeat_ts = float(getattr(self.app, "last_ui_heartbeat_ts", 0) or 0)
        ui_age_s = now - ui_heartbeat_ts if ui_heartbeat_ts else None

        context = {
            "ui_age_s": ui_age_s,  # PR-HB-003: Explicit ui_age_s field
            "ui_heartbeat_age_s": ui_age_s,  # Keep for compatibility
            "queue_activity_age_s": now - float(getattr(self.app, "last_queue_activity_ts", 0) or 0)
            if hasattr(self.app, "last_queue_activity_ts")
            else None,
            "runner_activity_age_s": now
            - float(getattr(self.app, "last_runner_activity_ts", 0) or 0),
            "queue_state": getattr(self.app, "get_queue_state", lambda: None)(),
            "watchdog_reason": reason,
            # PR-HB-003: Add operation tracking and thresholds
            "current_operation_label": getattr(self.app, "current_operation_label", None),
            "last_ui_action": getattr(self.app, "last_ui_action", None),
            "ui_stall_threshold_s": self.UI_STALL_S,
            "last_ui_heartbeat_ts": ui_heartbeat_ts,
            "watchdog_now_ts": now,
            "shutdown_in_progress": bool(getattr(self.app, "_is_shutting_down", False)),
            "main_thread_alive": bool(threading.main_thread().is_alive()),
            # Where the Tk thread is blocked right now (innermost frame first).
            "main_thread_stack": "\n".join(self._capture_ui_stack()),
        }
        context.update(self._runner_activity_context())

        def _done_callback():
            with self._lock:
                self._in_flight[reason] = False

        diagnostics = getattr(self, "diagnostics", None)
        if diagnostics is None:
            _done_callback()
            return

        # Prefer async build (don't block watchdog loop)
        try:
            # If your diagnostics_service has build_async, use it.
            if hasattr(diagnostics, "build_async"):
                webui_tail = None
                try:
                    from src.api.webui_process_manager import get_global_webui_process_manager

                    manager = get_global_webui_process_manager()
                    if manager is not None:
                        webui_tail = manager.get_recent_output_tail(max_lines=200)
                except Exception:
                    webui_tail = None
                # Call with on_done if supported; fall back if not accepted by signature.
                try:
                    diagnostics.build_async(
                        reason=reason,
                        context=context,
                        on_done=_done_callback,
                        include_process_state=True,
                        webui_tail=webui_tail,
                        cooldown_s=cooldown,
                    )  # type: ignore[arg-type]
                except TypeError:
                    # Older API: call without on_done and clear in-flight in a spawned thread
                    def _fallback_worker():
                        try:
                            diagnostics.build(reason=reason, context=context)
                        finally:
                            _done_callback()

                    # PR-THREAD-001: Use ThreadRegistry for fallback worker
                    from src.utils.thread_registry import get_thread_registry

                    registry = get_thread_registry()
                    registry.spawn(
                        target=_fallback_worker,
                        name=f"DiagTrigger-{reason}",
                        daemon=False,
                        purpose=f"Fallback diagnostics trigger for {reason}",
                    )
            else:
                # Fall back to spawning a thread here.
                def _worker():
                    try:
                        diagnostics.build(reason=reason, context=context)
                    finally:
                        _done_callback()

                # PR-THREAD-001: Use ThreadRegistry for worker
                from src.utils.thread_registry import get_thread_registry

                registry = get_thread_registry()
                registry.spawn(
                    target=_worker,
                    name=f"DiagTrigger-{reason}",
                    daemon=False,
                    purpose=f"Diagnostics trigger for {reason}",
                )
        except Exception:
            _done_callback()

    def _runner_activity_context(self) -> dict[str, object]:
        """Collect cheap current-run fields without creating another state store."""
        owner_job_id, owner_job = self._execution_owner()
        runtime_status = self._latest_runtime_status()
        runtime_job_id = getattr(runtime_status, "job_id", None)
        running_job = getattr(getattr(self.app, "app_state", None), "running_job", None)
        if owner_job_id:
            matches_owner = str(runtime_job_id or "") == owner_job_id
            return {
                "job_id": owner_job_id,
                "current_stage": (
                    getattr(runtime_status, "current_stage", None)
                    if matches_owner
                    else getattr(owner_job, "current_stage", None)
                ),
                "latest_progress": (
                    getattr(runtime_status, "progress", None) if matches_owner else None
                ),
                "execution_owner_job_id": owner_job_id,
                "runner_stall_threshold_s": self._runner_stall_threshold(
                    runtime_status if matches_owner else None
                ),
            }
        return {
            "job_id": getattr(runtime_status, "job_id", None)
            or getattr(running_job, "job_id", None),
            "current_stage": getattr(runtime_status, "current_stage", None)
            or getattr(running_job, "current_stage", None),
            "latest_progress": getattr(runtime_status, "progress", None)
            if runtime_status is not None
            else getattr(running_job, "progress", None),
        }
