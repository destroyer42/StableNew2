"""Multi-character selector widget for PR-CORE-014.

Provides a compact Tkinter panel that lists registered character LoRAs from the
LoRAManager manifest, lets the user tick multiple characters and adjust their
relative LoRA weight, and exposes `get_selected_actors()` / `set_actors()` for
round-trip persistence.

Usage::

    panel = MultiCharacterSelectorWidget(parent, on_change=my_callback)
    panel.pack(fill="x")

    # Load actors from an existing config / intent_config:
    panel.set_actors(intent_config.get("actors", []))

    # Retrieve the current selection as actor dicts ready for intent_config:
    actors = panel.get_selected_actors()

LoRA ordering convention (primary → secondary → style) is preserved; characters
are listed in the order they were registered in the LoRAManager manifest.  The
user can reorder via drag-and-drop in a future polish pass; for now, manual
weight setting is the primary interaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from tkinter import ttk
import tkinter as tk
from typing import Any

from src.gui.tooltip import attach_tooltip
from src.training.lora_manager import LoRAManager

_logger = logging.getLogger(__name__)

_WEIGHT_MIN = 0.1
_WEIGHT_MAX = 2.0
_WEIGHT_DEFAULT = 1.0
_WEIGHT_STEP = 0.05


class _CharacterRow:
    """State for a single character entry in the selector."""

    def __init__(
        self,
        *,
        frame: ttk.Frame,
        check_var: tk.BooleanVar,
        weight_var: tk.DoubleVar,
        character_name: str,
        lora_name: str | None,
        trigger_phrase: str | None,
    ) -> None:
        self.frame = frame
        self.check_var = check_var
        self.weight_var = weight_var
        self.character_name = character_name
        self.lora_name = lora_name
        self.trigger_phrase = trigger_phrase


class MultiCharacterSelectorWidget(ttk.LabelFrame):
    """Panel listing registered characters with per-character toggle and weight.

    Parameters
    ----------
    parent:
        Tkinter parent widget.
    on_change:
        Optional callback fired whenever the selection or any weight changes.
    lora_manager:
        LoRAManager instance.  Defaults to a new manager pointed at
        ``data/embeddings``.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_change: Callable[[], None] | None = None,
        lora_manager: LoRAManager | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("text", "Characters")
        kwargs.setdefault("padding", (6, 4))
        super().__init__(parent, **kwargs)
        self._on_change = on_change
        self._lora_manager = lora_manager or LoRAManager()
        self._rows: list[_CharacterRow] = []
        self._content_frame: ttk.Frame | None = None
        self._no_chars_label: ttk.Label | None = None
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_selected_actors(self) -> list[dict[str, Any]]:
        """Return actor dicts for all ticked characters, in display order.

        Each dict matches the ``actors`` schema in config_contract_v26:
        ``{name, character_name, lora_name, trigger_phrase, weight}``.
        """
        actors: list[dict[str, Any]] = []
        for row in self._rows:
            if not row.check_var.get():
                continue
            try:
                weight = round(float(row.weight_var.get()), 4)
            except (ValueError, tk.TclError):
                weight = _WEIGHT_DEFAULT
            actors.append(
                {
                    "name": row.character_name,
                    "character_name": row.character_name,
                    "lora_name": row.lora_name,
                    "trigger_phrase": row.trigger_phrase,
                    "weight": weight,
                }
            )
        return actors

    def set_actors(self, actors: list[dict[str, Any]] | None) -> None:
        """Restore a previous selection from a list of actor dicts.

        Unknown characters (not in the current manifest) are silently ignored.
        """
        actors_list = list(actors or [])
        # Build a lookup by character_name / name for quick matching.
        by_key: dict[str, dict[str, Any]] = {}
        for actor in actors_list:
            for key_field in ("character_name", "name"):
                key = str(actor.get(key_field) or "").strip().lower()
                if key:
                    by_key[key] = actor
                    break

        for row in self._rows:
            identity = row.character_name.lower()
            if identity in by_key:
                actor_data = by_key[identity]
                row.check_var.set(True)
                try:
                    weight = float(actor_data.get("weight") or _WEIGHT_DEFAULT)
                    row.weight_var.set(round(weight, 4))
                except (TypeError, ValueError):
                    row.weight_var.set(_WEIGHT_DEFAULT)
            else:
                row.check_var.set(False)
                row.weight_var.set(_WEIGHT_DEFAULT)

    def refresh(self) -> None:
        """Reload the character list from the LoRAManager manifest."""
        self._populate()

    # ------------------------------------------------------------------
    # Internal UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # Toolbar row
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        toolbar.columnconfigure(0, weight=1)

        ttk.Button(
            toolbar, text="↻ Refresh", command=self.refresh, width=10
        ).grid(row=0, column=1, sticky="e")

        # Scrollable content area
        self._content_frame = ttk.Frame(self)
        self._content_frame.grid(row=1, column=0, sticky="nsew")
        self._content_frame.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

    def _populate(self) -> None:
        """Rebuild the character rows from the manifest."""
        assert self._content_frame is not None
        # Capture current selection state before clearing.
        prior_selection: dict[str, dict[str, Any]] = {
            row.character_name.lower(): {
                "checked": row.check_var.get(),
                "weight": row.weight_var.get(),
            }
            for row in self._rows
        }

        # Destroy old rows.
        for row in self._rows:
            row.frame.destroy()
        if self._no_chars_label is not None:
            self._no_chars_label.destroy()
            self._no_chars_label = None
        self._rows.clear()

        entries = list(self._lora_manager.list())
        if not entries:
            self._no_chars_label = ttk.Label(
                self._content_frame,
                text="No characters registered yet.\nTrain a character LoRA to get started.",
                foreground="gray",
                justify="center",
            )
            self._no_chars_label.grid(row=0, column=0, pady=8)
            return

        for idx, entry in enumerate(entries):
            character_name = str(entry.get("character_name") or "").strip()
            if not character_name:
                continue
            lora_name = str(entry.get("lora_name") or "").strip() or None
            trigger_phrase = str(entry.get("trigger_phrase") or "").strip() or None

            prior = prior_selection.get(character_name.lower(), {})
            check_var = tk.BooleanVar(value=prior.get("checked", False))
            weight_var = tk.DoubleVar(value=prior.get("weight", _WEIGHT_DEFAULT))

            row_frame = ttk.Frame(self._content_frame)
            row_frame.grid(row=idx, column=0, sticky="ew", pady=1)
            row_frame.columnconfigure(1, weight=1)

            chk = ttk.Checkbutton(
                row_frame,
                variable=check_var,
                command=self._on_row_changed,
            )
            chk.grid(row=0, column=0, padx=(0, 4))

            name_label = ttk.Label(row_frame, text=character_name, width=16)
            name_label.grid(row=0, column=1, sticky="w")
            if trigger_phrase:
                attach_tooltip(name_label, f"Trigger: {trigger_phrase}")

            # Weight spinbox
            spinbox = ttk.Spinbox(
                row_frame,
                from_=_WEIGHT_MIN,
                to=_WEIGHT_MAX,
                increment=_WEIGHT_STEP,
                textvariable=weight_var,
                width=5,
                command=self._on_row_changed,
            )
            spinbox.grid(row=0, column=2, padx=4)
            attach_tooltip(spinbox, "LoRA weight (0.1 – 2.0)")

            ttk.Label(row_frame, text="wt", foreground="gray").grid(row=0, column=3)

            row_obj = _CharacterRow(
                frame=row_frame,
                check_var=check_var,
                weight_var=weight_var,
                character_name=character_name,
                lora_name=lora_name,
                trigger_phrase=trigger_phrase,
            )
            self._rows.append(row_obj)

            # Bind spinbox text edits too
            weight_var.trace_add("write", lambda *_: self._on_row_changed())

    def _on_row_changed(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                _logger.exception("[MultiCharacterSelectorWidget] on_change callback raised")
