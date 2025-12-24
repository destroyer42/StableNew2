from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.gui.gui_invoker import GuiInvoker
from src.pipeline.job_models_v2 import (
    JobLifecycleLogEvent,
    NormalizedJobRecord,
    QueueJobV2,
    UnifiedJobSummary,
)
from src.queue.job_history_store import JobHistoryEntry
from src.utils.config import LoraRuntimeConfig

if TYPE_CHECKING:  # pragma: no cover
    from src.gui.prompt_workspace_state import PromptWorkspaceState

logger = logging.getLogger(__name__)

# Type aliases for listeners
Listener = Callable[[], None]
ResourceListener = Callable[[dict[str, list[Any]]], None]


@dataclass
class PackJobEntry:
    pack_id: str
    pack_name: str
    config_snapshot: dict[str, Any]  # includes randomization-related fields
    prompt_text: str | None = None
    negative_prompt_text: str | None = None
    stage_flags: dict[str, bool] = field(default_factory=dict)
    randomizer_metadata: dict[str, Any] | None = None
    pack_row_index: int | None = None
    pack_version: str | None = None
    matrix_slot_values: dict[str, str] = field(default_factory=dict)


@dataclass
class JobDraftPart:
    positive_prompt: str
    negative_prompt: str
    estimated_images: int = 1


@dataclass
class JobDraftSummary:
    part_count: int = 0
    total_images: int = 0
    last_positive_prompt: str = ""
    last_negative_prompt: str = ""


@dataclass
class JobDraft:
    packs: list[PackJobEntry] = field(default_factory=list)
    parts: list[JobDraftPart] = field(default_factory=list)
    summary: JobDraftSummary = field(default_factory=JobDraftSummary)

    def add_part(self, part: JobDraftPart) -> None:
        self.parts.append(part)
        self.summary.part_count = len(self.parts)
        self.summary.total_images += part.estimated_images
        self.summary.last_positive_prompt = part.positive_prompt
        self.summary.last_negative_prompt = part.negative_prompt

    def clear(self) -> None:
        self.parts.clear()
        self.summary = JobDraftSummary()


@dataclass
class CurrentConfig:
    """Lightweight facade for the currently selected run configuration."""

    preset_name: str = ""
    model_name: str = ""
    vae_name: str = ""
    sampler_name: str = ""
    scheduler_name: str = ""
    width: int = 512
    height: int = 512
    steps: int = 20
    cfg_scale: float = 7.0
    batch_size: int = 1
    seed: int | None = None
    randomization_enabled: bool = False
    max_variants: int = 1
    refiner_enabled: bool = False
    refiner_model_name: str = ""
    refiner_switch_at: float = 0.8
    hires_enabled: bool = False
    hires_upscaler_name: str = "Latent"
    hires_upscale_factor: float = 2.0
    hires_steps: int | None = None
    hires_denoise: float = 0.3
    hires_use_base_model_for_hires: bool = True


@dataclass
class AppStateV2:
    """Central GUI-facing state container for the V2 application."""

    _listeners: dict[str, list[Listener]] = field(default_factory=dict)
    _invoker: GuiInvoker | None = None
    _notifications_enabled: bool = True

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
    learning_enabled: bool = False
    prompt_workspace_state: PromptWorkspaceState | None = None
    resources: dict[str, list[Any]] = field(
        default_factory=lambda: {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
            "upscalers": [],
        }
    )
    queue_items: list[str] = field(default_factory=list)
    queue_jobs: list[QueueJobV2] = field(default_factory=list)
    running_job: QueueJobV2 | None = None
    queue_status: str = "idle"
    history_items: list[JobHistoryEntry] = field(default_factory=list)
    run_config: dict[str, Any] = field(default_factory=dict)
    current_config: CurrentConfig = field(default_factory=CurrentConfig)
    _resource_listeners: list[Callable[[dict[str, list[Any]]], None]] = field(default_factory=list)
    # Canonical PromptPack-first draft state used by controllers (CORE1-A1)
    job_draft: JobDraft = field(default_factory=JobDraft)
    preview_jobs: list[NormalizedJobRecord] = field(default_factory=list)
    log_events: list[JobLifecycleLogEvent] = field(default_factory=list)
    log_events_max: int = 500
    lora_strengths: list[LoraRuntimeConfig] = field(default_factory=list)
    adetailer_models: list[str] = field(default_factory=list)
    adetailer_detectors: list[str] = field(default_factory=list)
    adetailer_enabled: bool = False
    adetailer_config: dict[str, Any] = field(default_factory=dict)
    collapse_states: dict[str, bool] = field(default_factory=dict)

    # PR-111: Run Controls UX state flags
    is_run_in_progress: bool = False
    is_direct_run_in_progress: bool = False
    is_queue_paused: bool = False
    last_run_job_id: str | None = None
    last_error_message: str | None = None

    # PR-203: Auto-run queue flag
    auto_run_queue: bool = False

    # PR-CORE-E: Config Sweep state
    config_sweep_enabled: bool = False
    config_sweep_variants: list[dict[str, Any]] = field(default_factory=list)
    apply_global_negative_txt2img: bool = True
    apply_global_negative_img2img: bool = True
    apply_global_negative_upscale: bool = True
    apply_global_negative_adetailer: bool = True

    def set_invoker(self, invoker: GuiInvoker) -> None:
        """Set an invoker used to marshal notifications onto the GUI thread."""
        self._invoker = invoker

    def disable_notifications(self) -> None:
        """Stop delivering listener callbacks (used during teardown)."""
        self._notifications_enabled = False

    def subscribe(self, key: str, listener: Listener) -> None:
        listeners = self._listeners.setdefault(key, [])
        if listener not in listeners:
            listeners.append(listener)

    def _notify(self, key: str) -> None:
        if not self._notifications_enabled:
            return

        listeners = list(self._listeners.get(key, []))
        if not listeners:
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
                self._invoker.invoke(listener)
            except Exception:
                continue

    def set_prompt(self, value: str) -> None:
        if self.prompt != value:
            self.prompt = value
            self._notify("prompt")

    def set_negative_prompt(self, value: str) -> None:
        if self.negative_prompt != value:
            self.negative_prompt = value
            self._notify("negative_prompt")

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
        normalized = {
            "models": list(value.get("models") or []),
            "vaes": list(value.get("vaes") or []),
            "samplers": list(value.get("samplers") or []),
            "schedulers": list(value.get("schedulers") or []),
            "upscalers": list(value.get("upscalers") or []),
            "adetailer_models": list(value.get("adetailer_models") or []),
            "adetailer_detectors": list(value.get("adetailer_detectors") or []),
        }
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
        if self.run_config != value:
            self.run_config = dict(value)
            self._notify("run_config")

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

    def set_queue_jobs(self, jobs: list[QueueJobV2] | None) -> None:
        if jobs is None:
            jobs = []
        if self.queue_jobs != jobs:
            self.queue_jobs = list(jobs)
            self._notify("queue_jobs")

    def set_running_job(self, job: QueueJobV2 | None) -> None:
        if self.running_job != job:
            self.running_job = job
            self._notify("running_job")

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

    def add_packs_to_job_draft(self, entries: list[PackJobEntry]) -> None:
        logger.info(f"[AppState] add_packs_to_job_draft received {len(entries)} PackJobEntry objects")
        self.job_draft.packs.extend(entries)
        logger.info(f"[AppState] Total packs in draft: {len(self.job_draft.packs)}")
        self._notify("job_draft")

    def add_job_draft_part(
        self,
        positive_prompt: str,
        negative_prompt: str,
        estimated_images: int = 1,
    ) -> None:
        part = JobDraftPart(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            estimated_images=estimated_images,
        )
        self.job_draft.add_part(part)
        self._notify("job_draft")

    def clear_job_draft(self) -> None:
        self.job_draft.clear()
        self.job_draft.packs.clear()
        self._notify("job_draft")

    def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None) -> None:
        logger.debug(f"[AppState] set_preview_jobs called with {len(jobs) if jobs else 0} jobs")
        if jobs is None:
            jobs = []
        if self.preview_jobs != jobs:
            logger.debug(f"[AppState] preview_jobs changed, notifying subscribers")
            self.preview_jobs = list(jobs)
            self._notify("preview_jobs")
        else:
            logger.debug(f"[AppState] preview_jobs unchanged, not notifying")

    def append_log_event(self, event: JobLifecycleLogEvent) -> None:
        self.log_events.append(event)
        if len(self.log_events) > self.log_events_max:
            self.log_events = list(self.log_events[-self.log_events_max :])
        self._notify("log_events")

    # PR-111: Run Controls UX state setters
    def set_is_run_in_progress(self, value: bool) -> None:
        if self.is_run_in_progress != value:
            self.is_run_in_progress = value
            self._notify("is_run_in_progress")

    def set_is_direct_run_in_progress(self, value: bool) -> None:
        if self.is_direct_run_in_progress != value:
            self.is_direct_run_in_progress = value
            self._notify("is_direct_run_in_progress")

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
