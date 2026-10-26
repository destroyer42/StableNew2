from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.api.webui_resource_service import build_empty_resource_map, normalize_resource_map
from src.contracts import CurrentConfig, JobDraft, JobDraftPart, PackJobEntry
from src.controller.ports.ui_dispatcher import UiDispatcher
from src.gui_v2.adapters.config_adapter_v26 import GuiConfigAdapterV26
from src.pipeline.job_models_v2 import (
    JobLifecycleLogEvent,
    NormalizedJobRecord,
    RuntimeJobStatus,
    UnifiedJobSummary,
)
from src.queue.job_history_store import JobHistoryEntry
from src.state.content_visibility import ContentVisibilityMode, normalize_content_visibility_mode
from src.utils.config import LoraRuntimeConfig
from src.utils.prompt_pack_utils import pack_json_path, same_pack_file

if TYPE_CHECKING:  # pragma: no cover
    from src.gui.prompt_workspace_state import PromptWorkspaceState

logger = logging.getLogger(__name__)

# Type aliases for listeners
Listener = Callable[[], None]
ResourceListener = Callable[[dict[str, list[Any]]], None]


@dataclass
class AppStateV2:
    """Central GUI-facing state container for the V2 application."""

    HOT_RUNTIME_KEYS: frozenset[str] = frozenset(
        {
            "runtime_status",
            "queue_status",
            "queue_items",
            "queue_jobs",
            "queue_dispatch_hold",
            "history_items",
            "preview_jobs",
            "operator_log",
        }
    )

    _listeners: dict[str, list[Listener]] = field(default_factory=dict)
    _invoker: UiDispatcher | None = None
    _notifications_enabled: bool = True
    _notification_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _batched_dirty_keys: set[str] = field(default_factory=set, init=False, repr=False)
    _batched_flush_scheduled: bool = field(default=False, init=False, repr=False)
    _batched_flush_delay_ms: int = field(default=75, init=False, repr=False)
    _batched_flush_callback: Callable[[], None] = field(init=False, repr=False)

    # Legacy prompt fields (deprecated - use PromptPack instead)
    prompt: str = ""  # DEPRECATED: Use selected_prompt_pack_id instead
    negative_prompt: str = ""  # DEPRECATED: Use selected_prompt_pack_id instead
    current_pack: str | None = None  # DEPRECATED: Use selected_prompt_pack_id instead

    # PR-CORE-D: PromptPack-Only tracking fields
    selected_prompt_pack_id: str | None = None
    selected_prompt_pack_name: str | None = None
    selected_config_snapshot_id: str | None = None
    last_unified_job_summary: UnifiedJobSummary | None = None

    is_running: bool = False
    controller: Any | None = None
    status_text: str = "Idle"
    last_error: str | None = None
    webui_state: str = "disconnected"
    learning_enabled: bool = True
    prompt_workspace_state: PromptWorkspaceState | None = None
    resources: dict[str, list[Any]] = field(default_factory=build_empty_resource_map)
    queue_items: list[str] = field(default_factory=list)
    queue_jobs: list[UnifiedJobSummary] = field(default_factory=list)
    queue_dispatch_hold: str = ""
    running_job: UnifiedJobSummary | None = None
    runtime_status: RuntimeJobStatus | None = None  # Dynamic execution state for running job
    queue_status: str = "idle"
    history_items: list[JobHistoryEntry] = field(default_factory=list)
    run_config: dict[str, Any] = field(default_factory=dict)
    intent_config: dict[str, Any] = field(default_factory=dict)
    execution_config: dict[str, Any] = field(default_factory=dict)
    backend_options: dict[str, Any] = field(default_factory=dict)
    current_config: CurrentConfig = field(default_factory=CurrentConfig)
    _resource_listeners: list[Callable[[dict[str, list[Any]]], None]] = field(default_factory=list)
    # Canonical PromptPack-first draft state used by controllers (CORE1-A1)
    job_draft: JobDraft = field(default_factory=JobDraft)
    preview_jobs: list[NormalizedJobRecord] = field(default_factory=list)
    preview_revision: int = 0
    preview_error: str | None = None
    #: Serializes the Preview lifecycle (invalidate / claim for admission / guarded publish) across the UI thread,
    #: background Preview builds and queue-submission workers.
    _preview_lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    log_events: list[JobLifecycleLogEvent] = field(default_factory=list)
    log_events_max: int = 500
    operator_log: list[str] = field(default_factory=list)
    operator_log_max: int = 500
    lora_strengths: list[LoraRuntimeConfig] = field(default_factory=list)
    adetailer_models: list[str] = field(default_factory=list)
    adetailer_detectors: list[str] = field(default_factory=list)
    adetailer_enabled: bool = True  # PR-DEFAULT-ADETAILER: Default to True for visibility
    adetailer_config: dict[str, Any] = field(default_factory=dict)
    collapse_states: dict[str, bool] = field(default_factory=dict)
    help_mode_enabled: bool = False
    content_visibility_mode: str = ContentVisibilityMode.NSFW.value

    # PR-111: Run Controls UX state flags
    is_run_in_progress: bool = False
    is_queue_paused: bool = False
    last_run_job_id: str | None = None
    last_error_message: str | None = None

    # PR-203: Auto-run queue flag
    auto_run_queue: bool = True

    # PR-CORE-E: Config Sweep state
    config_sweep_enabled: bool = False
    config_sweep_variants: list[dict[str, Any]] = field(default_factory=list)
    apply_global_negative_txt2img: bool = True
    apply_global_negative_img2img: bool = True
    apply_global_negative_upscale: bool = True
    apply_global_negative_adetailer: bool = True
    _config_adapter: GuiConfigAdapterV26 = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._config_adapter = GuiConfigAdapterV26(self)
        self._batched_flush_callback = self._flush_batched_notifications
        # Deliberately not dataclass fields: live presentation projections published by the Pipeline view for
        # controller reads. They are never persisted configuration and never execution authority.
        self._pipeline_stage_enabled = dict(self._PIPELINE_STAGE_DEFAULTS)
        self._pipeline_prompt_text = ""
        self._pipeline_upscale_params: tuple[float, str, int] = (2.0, "", 0)

    _PIPELINE_STAGE_DEFAULTS = {"txt2img": True, "img2img": False, "adetailer": False, "upscale": False}

    @property
    def config_adapter(self) -> GuiConfigAdapterV26:
        return self._config_adapter

    def set_invoker(self, invoker: UiDispatcher) -> None:
        """Set the toolkit-neutral dispatcher used to marshal notifications to the UI thread."""
        self._invoker = invoker

    @staticmethod
    def _queue_on(invoker: Any, fn: Callable[[], None]) -> None:
        """Queue ``fn`` through ``schedule``; older dispatchers only expose ``invoke``."""
        queue = getattr(invoker, "schedule", None) or invoker.invoke
        queue(fn)

    def get_pipeline_stage_flags(self, *, defaults: dict[str, bool] | None = None) -> dict[str, bool]:
        """Return the live Pipeline stage-toggle projection (``defaults`` fills stages never published)."""
        flags = dict(defaults if defaults is not None else self._PIPELINE_STAGE_DEFAULTS)
        flags.update(self._pipeline_stage_enabled)
        return {key: bool(value) for key, value in flags.items()}

    def set_pipeline_stage_enabled(self, stage: str, enabled: bool) -> bool:
        """Publish one Pipeline stage toggle; returns True when the projection changed."""
        name = str(stage or "").strip().lower()
        if name not in self._PIPELINE_STAGE_DEFAULTS:
            return False
        value = bool(enabled)
        if self._pipeline_stage_enabled.get(name) == value:
            return False
        self._pipeline_stage_enabled[name] = value
        self._notify_on_ui_thread("pipeline_stage_enabled")
        return True

    def set_pipeline_prompt_text(self, value: str) -> None:
        self._pipeline_prompt_text = str(value or "")

    def get_pipeline_prompt_text(self) -> str:
        return self._pipeline_prompt_text

    def set_pipeline_upscale_params(self, *, factor: float, model: str, tile_size: int) -> None:
        try:
            normalized_factor = float(factor)
        except (TypeError, ValueError):
            normalized_factor = 2.0
        try:
            normalized_tile = int(tile_size)
        except (TypeError, ValueError):
            normalized_tile = 0
        self._pipeline_upscale_params = (normalized_factor, str(model or "").strip(), normalized_tile)

    def get_pipeline_upscale_params(self) -> tuple[float, str, int]:
        return self._pipeline_upscale_params

    def _notify_on_ui_thread(self, key: str) -> None:
        """Deliver a presentation update inline on the UI thread (queued from other threads)."""
        if not self._notifications_enabled:
            return
        listeners = list(self._listeners.get(key, []))
        invoker = self._invoker
        for listener in listeners:
            try:
                run = getattr(invoker, "run_on_ui_thread", None) if invoker is not None else None
                if callable(run):
                    run(listener)
                elif invoker is not None:
                    self._queue_on(invoker, listener)
                else:
                    listener()
            except Exception:
                logger.exception("pipeline presentation listener failed")

    def disable_notifications(self) -> None:
        """Stop delivering listener callbacks (used during teardown)."""
        self._notifications_enabled = False
        with self._notification_lock:
            self._batched_dirty_keys.clear()
            self._batched_flush_scheduled = False

    def subscribe(self, key: str, listener: Listener) -> None:
        listeners = self._listeners.setdefault(key, [])
        if listener not in listeners:
            listeners.append(listener)

    def unsubscribe(self, key: str, listener: Listener) -> None:
        listeners = self._listeners.get(key)
        if not listeners:
            return
        try:
            listeners.remove(listener)
        except ValueError:
            return
        if not listeners:
            self._listeners.pop(key, None)

    def _notify(self, key: str) -> None:
        if not self._notifications_enabled:
            return

        listeners = list(self._listeners.get(key, []))
        if not listeners:
            return

        if key in self.HOT_RUNTIME_KEYS:
            self._schedule_batched_notification(key)
            return

        # If no invoker is set (e.g., unit tests), invoke inline.
        if self._invoker is None:
            for listener in listeners:
                try:
                    listener()
                except Exception:
                    continue
            return

        for listener in listeners:
            try:
                self._queue_on(self._invoker, listener)
            except Exception:
                continue

    def _schedule_batched_notification(self, key: str) -> None:
        invoker = self._invoker
        if invoker is None:
            self._deliver_notification_key(key)
            return

        should_schedule = False
        with self._notification_lock:
            self._batched_dirty_keys.add(key)
            if not self._batched_flush_scheduled:
                self._batched_flush_scheduled = True
                should_schedule = True

        if not should_schedule:
            return

        invoke_later = getattr(invoker, "invoke_later", None)
        try:
            if callable(invoke_later):
                invoke_later(self._batched_flush_delay_ms, self._batched_flush_callback)
            else:
                self._queue_on(invoker, self._batched_flush_callback)
        except Exception:
            with self._notification_lock:
                self._batched_flush_scheduled = False
            self._flush_batched_notifications()

    def _deliver_notification_key(self, key: str) -> None:
        if not self._notifications_enabled:
            return

        listeners = list(self._listeners.get(key, []))
        if not listeners:
            return

        if self._invoker is None:
            for listener in listeners:
                try:
                    listener()
                except Exception:
                    continue
            return

        for listener in listeners:
            try:
                listener()
            except Exception:
                continue

    def _flush_batched_notifications(self) -> None:
        with self._notification_lock:
            dirty_keys = list(self._batched_dirty_keys)
            self._batched_dirty_keys.clear()
            self._batched_flush_scheduled = False

        for key in dirty_keys:
            self._deliver_notification_key(key)

    def flush_now(self) -> None:
        if self._invoker is None or threading.current_thread() is threading.main_thread():
            self._flush_batched_notifications()
            return
        try:
            self._queue_on(self._invoker, self._batched_flush_callback)
        except Exception:
            self._flush_batched_notifications()

    def set_batched_flush_delay_for_tests(self, delay_ms: int) -> None:
        self._batched_flush_delay_ms = max(0, int(delay_ms))

    def set_prompt(self, value: str) -> None:
        if self.prompt != value:
            self.prompt = value
            self._notify("prompt")

    def set_negative_prompt(self, value: str) -> None:
        if self.negative_prompt != value:
            self.negative_prompt = value
            self._notify("negative_prompt")

    def set_help_mode_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.help_mode_enabled != enabled:
            self.help_mode_enabled = enabled
            self._notify("help_mode")

    def toggle_help_mode(self) -> bool:
        enabled = not bool(self.help_mode_enabled)
        self.set_help_mode_enabled(enabled)
        return enabled

    def set_content_visibility_mode(
        self, mode: str | ContentVisibilityMode
    ) -> ContentVisibilityMode:
        normalized = normalize_content_visibility_mode(mode)
        value = normalized.value
        if self.content_visibility_mode != value:
            self.content_visibility_mode = value
            self._notify("content_visibility_mode")
        return normalized

    def toggle_content_visibility_mode(self) -> ContentVisibilityMode:
        current = normalize_content_visibility_mode(self.content_visibility_mode)
        target = (
            ContentVisibilityMode.SFW
            if current == ContentVisibilityMode.NSFW
            else ContentVisibilityMode.NSFW
        )
        return self.set_content_visibility_mode(target)

    def set_current_pack(self, value: str | None) -> None:
        """DEPRECATED: Use set_selected_prompt_pack instead."""
        if self.current_pack != value:
            self.current_pack = value
            self._notify("current_pack")

    # PR-CORE-D: PromptPack-Only setters
    def set_selected_prompt_pack(self, pack_id: str | None, pack_name: str | None = None) -> None:
        """Set the selected PromptPack (PR-CORE-D PromptPack-only enforcement)."""
        changed = False
        if self.selected_prompt_pack_id != pack_id:
            self.selected_prompt_pack_id = pack_id
            changed = True
        if self.selected_prompt_pack_name != pack_name:
            self.selected_prompt_pack_name = pack_name
            changed = True
        if changed:
            self._notify("selected_prompt_pack")

    def set_selected_config_snapshot(self, snapshot_id: str | None) -> None:
        """Set the selected config snapshot ID (PR-CORE-D)."""
        if self.selected_config_snapshot_id != snapshot_id:
            self.selected_config_snapshot_id = snapshot_id
            self._notify("selected_config_snapshot")

    def set_last_unified_job_summary(self, summary: UnifiedJobSummary | None) -> None:
        """Set the last unified job summary for preview display (PR-CORE-D)."""
        if self.last_unified_job_summary != summary:
            self.last_unified_job_summary = summary
            self._notify("last_unified_job_summary")

    def set_running(self, value: bool) -> None:
        if self.is_running != value:
            self.is_running = value
            self._notify("is_running")

    def set_status_text(self, value: str) -> None:
        if self.status_text != value:
            self.status_text = value
            self._notify("status_text")

    def set_last_error(self, value: str | None) -> None:
        if self.last_error != value:
            self.last_error = value
            self._notify("last_error")

    def set_learning_enabled(self, value: bool) -> None:
        if self.learning_enabled != value:
            self.learning_enabled = value
            self._notify("learning_enabled")

    def set_webui_state(self, value: str) -> None:
        if self.webui_state != value:
            self.webui_state = value
            self._notify("webui_state")

    def add_resource_listener(self, callback: ResourceListener) -> None:
        if callback in self._resource_listeners:
            return
        self._resource_listeners.append(callback)

    def _notify_resource_listeners(self) -> None:
        listeners = list(self._resource_listeners)
        for listener in listeners:
            try:
                listener(self.resources)
            except Exception:
                logger.exception("Error in AppStateV2 resource listener")

    def set_resources(self, value: dict[str, list[Any]] | None) -> None:
        if value is None:
            return
        normalized = normalize_resource_map(value)
        if self.resources != normalized:
            self.resources = normalized
            self._notify("resources")
            self._notify_resource_listeners()
        self.set_adetailer_resources(
            normalized.get("adetailer_models"),
            normalized.get("adetailer_detectors"),
        )

    def set_run_config(self, value: dict[str, Any] | None) -> None:
        if value is None:
            return
        if self._config_adapter.apply_run_config(value):
            self._notify("run_config")
            self._notify("config_layers")

    def set_adetailer_enabled(self, value: bool) -> None:
        normalized = bool(value)
        if self.adetailer_enabled != normalized:
            self.adetailer_enabled = normalized
            self._notify("adetailer_enabled")

    def set_adetailer_config(self, value: dict[str, Any] | None) -> None:
        normalized = dict(value) if value else {}
        if self.adetailer_config != normalized:
            self.adetailer_config = normalized
            self._notify("adetailer_config")

    def get_collapse_state(self, key: str) -> bool | None:
        """Return the stored collapse state for the given key."""
        return self.collapse_states.get(key)

    def set_collapse_state(self, key: str, is_open: bool) -> None:
        """Persist the open/closed state of a collapsible card."""
        normalized = bool(is_open)
        if self.collapse_states.get(key) == normalized:
            return
        self.collapse_states[key] = normalized

    def set_adetailer_resources(
        self,
        models: list[str] | None = None,
        detectors: list[str] | None = None,
    ) -> None:
        if models is not None and self.adetailer_models != models:
            self.adetailer_models = list(models)
            self._notify("adetailer_models")
        if detectors is not None and self.adetailer_detectors != detectors:
            self.adetailer_detectors = list(detectors)
            self._notify("adetailer_detectors")

    def set_lora_strengths(self, strengths: list[LoraRuntimeConfig] | None) -> None:
        if strengths is None:
            return
        if self.lora_strengths != strengths:
            self.lora_strengths = list(strengths)
            self._notify("lora_strengths")

    def set_queue_items(self, items: list[str] | None) -> None:
        if items is None:
            return
        self.queue_items = list(items)
        self._notify("queue_items")

    def set_queue_jobs(self, jobs: list[UnifiedJobSummary] | None) -> None:
        if jobs is None:
            jobs = []

        # Order, identity, and lifecycle state define the active queue
        # projection. A QUEUED -> RUNNING transition keeps the same ID and
        # length but must still reach observers.
        def _signature(values: list[UnifiedJobSummary]) -> tuple[tuple[str, str], ...]:
            return tuple(
                (
                    str(getattr(job, "job_id", "")),
                    str(getattr(job, "status", "")).upper(),
                )
                for job in values
            )

        changed = _signature(self.queue_jobs) != _signature(jobs)
        if changed:
            logger.debug(
                f"set_queue_jobs: Updating from {len(self.queue_jobs)} to {len(jobs)} jobs"
            )
            self.queue_jobs = list(jobs)
            self._notify("queue_jobs")
        else:
            logger.debug(f"set_queue_jobs: No change detected, {len(jobs)} jobs")

    def set_queue_dispatch_hold(self, message: str | None) -> None:
        """Record why queued work is not dispatching ("" when nothing is held); notifies only on change."""
        text = str(message or "")
        if text != self.queue_dispatch_hold:
            self.queue_dispatch_hold = text
            self._notify("queue_dispatch_hold")

    def set_running_job(self, job: UnifiedJobSummary | None) -> None:
        if self.running_job != job:
            self.running_job = job
            self._notify("running_job")

    def set_runtime_status(self, status: RuntimeJobStatus | None) -> None:
        """Set the runtime execution status for the currently running job.

        This should be updated periodically during job execution to reflect
        current stage, progress, seed, and ETA information.
        """
        if self.runtime_status != status:
            self.runtime_status = status
            self._notify("runtime_status")

    def set_queue_status(self, status: str) -> None:
        if self.queue_status != status:
            self.queue_status = status
            self._notify("queue_status")

    def set_history_items(self, items: list[JobHistoryEntry] | None) -> None:
        if items is None:
            return
        if self.history_items != items:
            self.history_items = list(items)
            self._notify("history_items")

    def add_history_item(self, item: JobHistoryEntry | None) -> None:
        if not item:
            return
        self.history_items.insert(0, item)
        self.history_items = list(self.history_items)
        self._notify("history_items")

    def add_packs_to_job_draft(self, entries: list[PackJobEntry]) -> bool:
        """Add pack entries; False (nothing changed) while an unsent history variation is the draft."""
        logger.info(
            f"[AppState] add_packs_to_job_draft received {len(entries)} PackJobEntry objects"
        )
        with self._preview_lock:
            if self.job_draft.history_variation is not None:
                return False  # draft modes never mix and an unsent variation is never discarded implicitly
            self.job_draft.packs.extend(entries)
            self._reset_preview_locked()
        self._notify("preview_jobs")
        logger.info(f"[AppState] Total packs in draft: {len(self.job_draft.packs)}")
        self._notify("job_draft")
        return True

    def add_job_draft_part(
        self,
        positive_prompt: str,
        negative_prompt: str,
        estimated_images: int = 1,
    ) -> bool:
        """Add a prompt part; False (nothing changed) while an unsent history variation is the draft."""
        part = JobDraftPart(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            estimated_images=estimated_images,
        )
        with self._preview_lock:
            if self.job_draft.history_variation is not None:
                return False
            self.job_draft.add_part(part)
            self._reset_preview_locked()
        self._notify("preview_jobs")
        self._notify("job_draft")
        return True

    def clear_job_draft(self) -> None:
        with self._preview_lock:
            self.job_draft.clear()
            self.job_draft.packs.clear()
            self._reset_preview_locked()
        self._notify("preview_jobs")
        self._notify("job_draft")

    def begin_history_variation(self, variation: Any) -> None:
        """Make ``variation`` (a ``HistoryVariationDraft``) the unsent draft, replacing any pack/part draft.

        One step under the Preview lifecycle lock: the previous draft and Preview are dropped and the revision advances,
        so a build still in flight for the old draft can no longer publish and the old Preview cannot be admitted.
        """
        with self._preview_lock:
            self.job_draft.clear()
            self.job_draft.packs.clear()
            self.job_draft.history_variation = variation
            self._reset_preview_locked()
        self._notify("preview_jobs")
        self._notify("job_draft")

    def update_history_variation(self, variation: Any) -> bool:
        """Replace the current variation with an edited copy; every edit invalidates the Preview. False without one."""
        with self._preview_lock:
            if self.job_draft.history_variation is None:
                return False
            if variation == self.job_draft.history_variation:
                return True
            self.job_draft.history_variation = variation
            self._reset_preview_locked()
        self._notify("preview_jobs")
        self._notify("job_draft")
        return True

    def has_unsent_pipeline_work(self) -> bool:
        """Whether the Pipeline draft holds anything an operator could lose by replacing it."""
        draft = self.job_draft
        return bool(draft.packs or draft.parts or draft.history_variation is not None)

    def clear_admitted_draft(self, admitted: list[NormalizedJobRecord]) -> bool:
        """Clear the draft and Preview of a successfully admitted submission, unless the draft changed since.

        The Preview is the witness: every change to a compile input empties it (``invalidate_preview``), and an
        admission presents its records as the Preview, so ``preview_jobs`` still being exactly ``admitted`` means
        nothing was edited after admission. The check and the clear are one step under the lifecycle lock, so an edit
        either lands first (nothing is cleared) or after (the edit starts the next draft). Returns whether it cleared.
        """
        with self._preview_lock:
            current = self.preview_jobs
            if (
                not admitted
                or len(current) != len(admitted)
                or any(left is not right for left, right in zip(current, admitted, strict=True))
            ):
                return False
            self.job_draft.clear()
            self.job_draft.packs.clear()
            self._reset_preview_locked()
        self._notify("preview_jobs")
        self._notify("job_draft")
        return True

    def pack_save_listener(self, packs_dir: str | Path) -> Callable[[Path], None]:
        """A ``PromptWorkspaceState.pack_saved_listener`` that reports saves to ``pack_file_saved`` for ``packs_dir``."""

        def on_saved(path: Path) -> None:
            self.pack_file_saved(path, packs_dir=packs_dir)

        return on_saved

    def pack_file_saved(self, pack_path: str | Path, *, packs_dir: str | Path) -> bool:
        """A PromptPack file was saved successfully. A Preview compiled from its previous contents is stale.

        The draft's pack ids are resolved exactly as the compiler resolves them (``pack_json_path``), so only the
        very same file matches: another pack with the same file name in a different directory does not. Invalidates
        and announces the draft (the Pipeline tab then rebuilds the Preview) only when the draft uses that file;
        returns whether it did. Call it after a save has succeeded, never after a failed one.
        """
        saved = Path(pack_path)
        if not any(
            same_pack_file(pack_json_path(entry.pack_id, packs_dir), saved)
            for entry in self.job_draft.packs
        ):
            return False
        self.invalidate_preview()
        self._notify("job_draft")
        return True

    def invalidate_preview(self) -> None:
        """Invalidate only transient preview work, including results awaiting UI delivery."""
        with self._preview_lock:
            self._reset_preview_locked()
        self._notify("preview_jobs")

    def _reset_preview_locked(self) -> None:
        """Drop the Preview and advance the revision. The caller holds ``_preview_lock`` and notifies afterwards."""
        self.preview_revision += 1
        self.preview_jobs = []
        self.preview_error = None

    def claim_preview_for_admission(self) -> tuple[list[NormalizedJobRecord], int]:
        """``(accepted records, revision)`` for a queue submission.

        With an accepted Preview, its frozen records are returned untouched. With none, the Preview revision is
        advanced under the lock so a build that is still in flight (for an older revision) can no longer publish: it
        would otherwise display a different (for an unseeded random Matrix, differently sampled) selection than the
        one the submission compiles and queues. The caller compiles once and presents that result with
        ``accept_preview_result(..., revision=<returned revision>)``.
        """
        with self._preview_lock:
            if self.preview_jobs:
                return list(self.preview_jobs), self.preview_revision
            self.preview_revision += 1
            return [], self.preview_revision

    def accept_preview_result(
        self, jobs: list[NormalizedJobRecord], *, revision: int | None, error: str | None = None
    ) -> bool:
        """Publish ``jobs`` as the Preview only if ``revision`` is still the current one (``None`` = unconditionally).

        The check and the assignment are one step under the lifecycle lock, so a concurrent claim or invalidation
        either happens before it (the result is discarded) or after it (the result is superseded).
        """
        with self._preview_lock:
            if revision is not None and revision != self.preview_revision:
                return False
            changed = self.preview_jobs != jobs or self.preview_error != error
            if changed:
                self.preview_jobs = list(jobs)
                self.preview_error = error
        if changed:
            self._notify("preview_jobs")
        return True

    def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None, *, error: str | None = None) -> None:
        logger.debug(f"[AppState] set_preview_jobs called with {len(jobs) if jobs else 0} jobs")
        if jobs is None:
            jobs = []
        if self.preview_jobs != jobs or self.preview_error != error:
            logger.debug("[AppState] preview_jobs changed, notifying subscribers")
            self.preview_jobs = list(jobs)
            self.preview_error = error
            self._notify("preview_jobs")
        else:
            logger.debug("[AppState] preview_jobs unchanged, not notifying")

    def append_log_event(self, event: JobLifecycleLogEvent) -> None:
        self.log_events.append(event)
        if len(self.log_events) > self.log_events_max:
            self.log_events = list(self.log_events[-self.log_events_max :])
        self._notify("log_events")

    def append_operator_log_line(self, text: str) -> None:
        line = str(text)
        self.operator_log.append(line)
        if len(self.operator_log) > self.operator_log_max:
            self.operator_log = list(self.operator_log[-self.operator_log_max :])
        self._notify("operator_log")

    def clear_operator_log(self) -> None:
        if not self.operator_log:
            return
        self.operator_log = []
        self._notify("operator_log")

    # PR-111: Run Controls UX state setters
    def set_is_run_in_progress(self, value: bool) -> None:
        if self.is_run_in_progress != value:
            self.is_run_in_progress = value
            self._notify("is_run_in_progress")

    def set_is_queue_paused(self, value: bool) -> None:
        if self.is_queue_paused != value:
            self.is_queue_paused = value
            self._notify("is_queue_paused")

    def set_auto_run_queue(self, value: bool) -> None:
        """PR-203: Set auto-run queue flag."""
        if self.auto_run_queue != value:
            self.auto_run_queue = value
            self._notify("auto_run_queue")

    def set_last_run_job_id(self, value: str | None) -> None:
        if self.last_run_job_id != value:
            self.last_run_job_id = value
            self._notify("last_run_job_id")

    def set_last_error_message(self, value: str | None) -> None:
        if self.last_error_message != value:
            self.last_error_message = value
            self._notify("last_error_message")

    # PR-CORE-E: Config Sweep setters
    def set_config_sweep_enabled(self, value: bool) -> None:
        """Enable/disable config sweep feature."""
        if self.config_sweep_enabled != value:
            self.config_sweep_enabled = value
            self._notify("config_sweep_enabled")

    def set_config_sweep_variants(self, variants: list[dict[str, Any]] | None) -> None:
        """Set the list of config sweep variants."""
        if variants is None:
            variants = []
        if self.config_sweep_variants != variants:
            self.config_sweep_variants = list(variants)
            self._notify("config_sweep_variants")

    def add_config_sweep_variant(self, variant: dict[str, Any]) -> None:
        """Add a config sweep variant to the list."""
        self.config_sweep_variants.append(variant)
        self._notify("config_sweep_variants")

    def remove_config_sweep_variant(self, index: int) -> None:
        """Remove a config sweep variant by index."""
        if 0 <= index < len(self.config_sweep_variants):
            self.config_sweep_variants.pop(index)
            self._notify("config_sweep_variants")

    def set_apply_global_negative(self, stage: str, value: bool) -> None:
        """Set apply_global_negative flag for a specific stage."""
        attr_name = f"apply_global_negative_{stage}"
        if hasattr(self, attr_name):
            current = getattr(self, attr_name)
            if current != value:
                setattr(self, attr_name, value)
                self._notify(attr_name)
