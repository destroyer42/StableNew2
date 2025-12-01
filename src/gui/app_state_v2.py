from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.gui.gui_invoker import GuiInvoker
from src.queue.job_history_store import JobHistoryEntry
from src.utils.config import LoraRuntimeConfig

if TYPE_CHECKING:  # pragma: no cover
    from src.gui.prompt_workspace_state import PromptWorkspaceState

@dataclass
class PackJobEntry:
    pack_id: str
    pack_name: str
    config_snapshot: dict[str, Any]  # includes randomization-related fields

@dataclass
class JobDraft:
    packs: list[PackJobEntry] = field(default_factory=list)


@dataclass
class AppStateV2:
    """Central GUI-facing state container for the V2 application."""

    _listeners: Dict[str, List[Listener]] = field(default_factory=dict)
    _invoker: Optional[GuiInvoker] = None
    _notifications_enabled: bool = True

    prompt: str = ""
    negative_prompt: str = ""
    current_pack: Optional[str] = None
    is_running: bool = False
    controller: Optional[Any] = None
    status_text: str = "Idle"
    last_error: Optional[str] = None
    webui_state: str = "disconnected"
    learning_enabled: bool = False
    prompt_workspace_state: Optional["PromptWorkspaceState"] = None
    resources: Dict[str, List[Any]] = field(
        default_factory=lambda: {
            "models": [],
            "vaes": [],
            "samplers": [],
            "schedulers": [],
        }
    )
    queue_items: List[str] = field(default_factory=list)
    running_job: dict[str, Any] | None = None
    queue_status: str = "idle"
    history_items: list[JobHistoryEntry] = field(default_factory=list)
    run_config: Dict[str, Any] = field(default_factory=dict)
    _resource_listeners: List[Callable[[Dict[str, List[Any]]], None]] = field(default_factory=list)
    job_draft: JobDraft = field(default_factory=JobDraft)
    lora_strengths: list[LoraRuntimeConfig] = field(default_factory=list)
    adetailer_models: list[str] = field(default_factory=list)
    adetailer_detectors: list[str] = field(default_factory=list)
    adetailer_enabled: bool = False
    adetailer_config: dict[str, Any] = field(default_factory=dict)

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

    def set_current_pack(self, value: Optional[str]) -> None:
        if self.current_pack != value:
            self.current_pack = value
            self._notify("current_pack")

    def set_running(self, value: bool) -> None:
        if self.is_running != value:
            self.is_running = value
            self._notify("is_running")

    def set_status_text(self, value: str) -> None:
        if self.status_text != value:
            self.status_text = value
            self._notify("status_text")

    def set_last_error(self, value: Optional[str]) -> None:
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
        if self.queue_items != items:
            self.queue_items = list(items)
            self._notify("queue_items")

    def set_running_job(self, job: dict[str, Any] | None) -> None:
        if self.running_job != job:
            self.running_job = dict(job) if job else None
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
        self.job_draft.packs.extend(entries)
        self._notify("job_draft")

    def clear_job_draft(self) -> None:
        self.job_draft.packs.clear()
        self._notify("job_draft")
