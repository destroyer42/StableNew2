"""Read-only model readiness line for the Base Generation panel (PR-IMG-MODELS-150).

One label and one explicit ``Check readiness`` button. Pressing it runs ``probe_model_readiness`` (GET /sd-models, a bounded
safetensors header and, for a multi-component checkpoint, the module catalog and live selection) on a background worker and
publishes the verdict back on the Tk thread. Nothing here hashes, scans, writes to Forge, changes the selected model or any
control, or runs at startup / on a model change: selecting a model only marks the previous result stale. Results are
latest-request-wins and dropped when the model changed or the widget was destroyed, so an obsolete answer can never
overwrite a newer one.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from src.gui.theme_v2 import MUTED_LABEL_STYLE
from src.gui.widgets.responsive_wrap_v2 import bind_wraplength
from src.image_backends.forge_klein_profile import is_klein_transformer_name
from src.image_backends.model_readiness import ModelReadiness
from src.image_backends.model_readiness_probe import probe_model_readiness

logger = logging.getLogger(__name__)

NOT_CHECKED = "Model readiness: not checked. Use Check readiness to inspect the selected model (read-only)."


class ModelReadinessPresenter:
    def __init__(
        self,
        panel: Any,
        parent: tk.Misc,
        *,
        controller: Any = None,
        probe: Callable[[Any, str], ModelReadiness] | None = None,
    ) -> None:
        self._panel = panel
        self._controller = controller
        self._probe = probe or (
            lambda client, model: probe_model_readiness(client, model, qualified_profile=is_klein_transformer_name(model))
        )
        self._request_id = 0
        self._shown_model = ""
        self._destroyed = False
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.button = ttk.Button(self.frame, text="Check readiness", command=self.check)
        self.button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.label = ttk.Label(self.frame, text=NOT_CHECKED, style=MUTED_LABEL_STYLE, justify="left")
        self.label.grid(row=0, column=0, sticky="ew")
        bind_wraplength(self.label)
        row = parent.grid_size()[1]
        self.frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.frame.bind("<Destroy>", self._on_destroy, add="+")
        panel.model_var.trace_add("write", lambda *_: self.mark_stale())

    # -- public ---------------------------------------------------------------------------------------------------

    def mark_stale(self) -> None:
        """The selected model changed: any in-flight or shown verdict no longer describes it."""

        self._request_id += 1
        if self._shown_model != str(self._panel.model_var.get() or ""):
            self._set_text(NOT_CHECKED)

    def check(self) -> None:
        model = str(self._panel.model_var.get() or "").strip()
        if not model:
            self._set_text("Model readiness: select a model first.")
            return
        client = getattr(self._controller, "_api_client", None)
        if client is None:
            self._set_text("Model readiness unavailable: no WebUI connection is configured.")
            return
        self._request_id += 1
        request_id = self._request_id
        self._shown_model = model
        self._set_text(f"Checking {model} (read-only)...")

        def work() -> None:
            try:
                readiness: ModelReadiness | None = self._probe(client, model)
            except Exception:  # noqa: BLE001 - the worker must always complete the request
                logger.exception("Model readiness check failed unexpectedly")
                readiness = None
            try:
                self.frame.after(0, lambda: self._publish(request_id, model, readiness))
            except (RuntimeError, tk.TclError):
                return  # the widget or the Tk root is gone

        from src.utils.thread_registry import get_thread_registry

        try:
            get_thread_registry().spawn(
                target=work, name="ModelReadinessCheck", daemon=False, purpose="Read-only model readiness probe"
            )
        except Exception:  # noqa: BLE001
            logger.warning("Model readiness worker could not start")
            self._set_text("Model readiness unavailable: the background check could not start.")

    # -- internals ------------------------------------------------------------------------------------------------

    def _publish(self, request_id: int, model: str, readiness: ModelReadiness | None) -> None:
        if self._destroyed or request_id != self._request_id:
            return  # superseded by a newer request or a model change
        if str(self._panel.model_var.get() or "").strip() != model:
            return
        if readiness is None:
            self._set_text(f"Model readiness unavailable for {model}: the check failed.")
            return
        details = " ".join(readiness.reasons)
        self._set_text(f"{readiness.label}: {model}. {details}".strip())

    def _set_text(self, text: str) -> None:
        if self._destroyed:
            return
        try:
            self.label.configure(text=text)
        except tk.TclError:
            self._destroyed = True

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.frame:
            self._destroyed = True
            self._request_id += 1


__all__ = ["ModelReadinessPresenter", "NOT_CHECKED"]
