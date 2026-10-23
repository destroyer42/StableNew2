"""Authored LoRA controls and local browser; all discovery is off Tk."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import TYPE_CHECKING, Any, cast

from src.assets.registry import AssetRegistrySnapshot
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.gui.enhanced_slider import EnhancedSlider
from src.gui.gui_invoker import GuiInvoker
from src.gui.tooltip import attach_tooltip
from src.gui.widgets.lora_keyword_dialog import LoRAKeywordDialog
from src.gui_v2.lora_authoring_view import project_selected_lora
from src.gui_v2.lora_browser import target_profile, visible_resource
from src.image_backends.model_policy import ModelPolicy
from src.utils.lora_keyword_detector import LoRAMetadata
from src.utils.lora_scanner import LoRAResource, LoRAScanner, get_lora_scanner
from src.utils.thread_registry import get_thread_registry

if TYPE_CHECKING:
    from src.gui.widgets.lora_browser_dialog import LoRABrowserDialog


class LoRAPickerPanel(ttk.Frame):
    """Panel for managing LoRAs with add/remove/strength controls."""

    NAME_WRAP_LENGTH = 280
    COMBO_MIN_WIDTH = 180
    CONTROL_ROW_MIN_WIDTH = 220
    SLIDER_MAX = 1.5
    SLIDER_RESOLUTION = 0.01
    LIST_HEIGHT = 320  # room for one selected LoRA's evidence rows without scrolling

    def __init__(
        self,
        parent: tk.Misc,
        on_change_callback: Callable[[], None] | None = None,
        webui_root: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(parent, **kwargs)
        self.on_change_callback = on_change_callback
        self.webui_root = webui_root
        self._lora_entries: list[
            tuple[str, tk.DoubleVar, ttk.Frame]
        ] = []  # (name, strength_var, frame)
        self._entry_widgets: dict[str, dict[str, object]] = {}
        #: Model-specific per-LoRA notes (e.g. "not verified for FLUX.2 Klein 4B"); never removes a selection.
        self._annotations: dict[str, str] = {}
        #: Called whenever the selection changes (add/remove/strength/set/clear), after ``on_change_callback``.
        self.selection_listener: Callable[[], None] | None = None
        #: Called on the Tk thread after each discovery finishes (success or failure), for views that depend on the
        #: local inventory (the Style Consistency selector). Never called from the worker.
        self.inventory_listener: Callable[[], None] | None = None
        #: Exact LoRA names the last successful discovery returned; ``None`` while unknown or after a failed refresh.
        self._inventory_names: frozenset[str] | None = None
        self.scanner: LoRAScanner | None = None  # constructed by the discovery worker, never on Tk
        self._content_visibility_mode = self._discover_content_visibility_mode()
        self._available_loras: list[str] = []
        self._visible_loras: list[str] = []
        self._resources: dict[str, LoRAResource] = {}
        self._verified = False
        self._browser: LoRABrowserDialog | None = None
        self._keyword_dialog: LoRAKeywordDialog | None = None
        self._policy: ModelPolicy | None = None
        self._model_name = ""
        self._asset_snapshot = AssetRegistrySnapshot(())

        self._build_ui()

        self._init_discovery()
        self._initial_scan: str | None = self.after(100, self._scan_loras)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _init_discovery(self) -> None:
        self._closed = False
        self._scan_active = False
        self._request_id = 0
        self._cancel_scan = threading.Event()
        self._invoker = GuiInvoker(self)

    def _build_ui(self) -> None:
        """Build the LoRA picker UI."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header
        header_frame = ttk.Frame(self)
        header_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 2))
        header_frame.columnconfigure(0, weight=1)

        ttk.Label(header_frame, text="LoRAs", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        ttk.Button(header_frame, text="↻ Refresh", command=self.refresh_loras, width=10).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Button(header_frame, text="Browse…", command=self.open_browser).grid(row=0, column=2)
        self.discovery_status = tk.StringVar(
            value="Local inventory not verified yet; saved choices retained."
        )
        ttk.Label(header_frame, textvariable=self.discovery_status, wraplength=360).grid(
            row=1, column=0, columnspan=3, sticky="ew"
        )
        self.insertion_status = tk.StringVar(value="")
        ttk.Label(header_frame, textvariable=self.insertion_status, wraplength=360).grid(
            row=2, column=0, columnspan=3, sticky="ew"
        )

        # Add button frame
        add_frame = ttk.Frame(self)
        add_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        add_frame.columnconfigure(0, weight=1, minsize=self.COMBO_MIN_WIDTH)

        self.lora_name_var = tk.StringVar()
        self.lora_name_combo = ttk.Combobox(
            add_frame, textvariable=self.lora_name_var, width=28, state="readonly"
        )
        self.lora_name_combo.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.lora_name_combo.bind("<Return>", lambda e: self._on_add_lora())

        ttk.Button(add_frame, text="Add LoRA", command=self._on_add_lora).grid(
            row=0, column=1, sticky="e"
        )

        # Scrollable list of LoRAs
        list_frame = ttk.Frame(self, relief="sunken", borderwidth=1)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, height=self.LIST_HEIGHT, bg="#2b2b2b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)

        self.lora_list_frame = ttk.Frame(canvas)
        self.lora_list_frame.columnconfigure(0, weight=1)
        self.lora_list_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.lora_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._canvas = canvas

        # Enable mousewheel scrolling
        canvas.bind(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        )

    def _discover_content_visibility_mode(self) -> str:
        widget = getattr(self, "master", None)
        while widget is not None:
            app_state = getattr(widget, "app_state", None)
            mode = getattr(app_state, "content_visibility_mode", None)
            if isinstance(mode, str) and mode.strip():
                return mode
            widget = getattr(widget, "master", None)
        return "nsfw"

    def set_content_visibility_mode(self, mode: str) -> None:
        self._content_visibility_mode = str(mode or "nsfw")
        self.insertion_status.set("")  # the last message may name trigger words the new mode hides
        self._close_keywords()
        self._refresh_visible_lora_names()
        self._refresh_selected_projection()
        self._render_browser()

    def _refresh_visible_lora_names(self) -> None:
        visible: list[str] = []
        for name in self._available_loras:
            resource = self._resources.get(name)
            if resource and visible_resource(resource, self._content_visibility_mode):
                visible.append(name)
        self._visible_loras = sorted(visible)
        self.lora_name_combo["values"] = self._visible_loras
        if self.lora_name_var.get() not in self._visible_loras:
            self.lora_name_var.set("")

    def _hidden_selection(self, name: str) -> bool:
        resource = self._resources.get(name)
        return self._content_visibility_mode == "sfw" and (
            resource is None or not visible_resource(resource, self._content_visibility_mode)
        )

    def _on_add_lora(self) -> None:
        """Add a new LoRA to the list."""
        name = self.lora_name_var.get().strip()
        if not name:
            return
        if name not in self._visible_loras:
            return

        # Check for duplicates
        for existing_name, _, _ in self._lora_entries:
            if existing_name == name:
                return

        # Create LoRA entry
        self._add_lora_entry(name, 0.8)

        # Clear combobox
        self.lora_name_var.set("")

        # Notify change
        if self.on_change_callback:
            self.on_change_callback()
        self._notify_selection()

    def _add_lora_entry(self, name: str, strength: float) -> None:
        """Add a LoRA entry widget to the list."""
        hidden = self._hidden_selection(name)
        display_name = REDACTED_TEXT if hidden else name
        entry_frame = ttk.Frame(self.lora_list_frame, relief="solid", borderwidth=1, padding=(6, 4))
        entry_frame.pack(fill="x", padx=2, pady=2)
        entry_frame.columnconfigure(0, weight=1)

        name_row = ttk.Frame(entry_frame)
        name_row.grid(row=0, column=0, sticky="ew")
        name_row.columnconfigure(0, weight=1)
        controls_row = ttk.Frame(entry_frame)
        controls_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        controls_row.columnconfigure(0, weight=1, minsize=self.CONTROL_ROW_MIN_WIDTH)

        name_label = ttk.Label(
            name_row,
            text=display_name,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=self.NAME_WRAP_LENGTH,
        )
        name_label.grid(row=0, column=0, sticky="ew")
        attach_tooltip(name_label, display_name)

        strength_var = tk.DoubleVar(value=strength)

        def on_delete() -> None:
            self._remove_lora_entry(name)

        remove_button = ttk.Button(controls_row, text="X", width=3, command=on_delete)
        remove_button.grid(row=0, column=2, sticky="e", padx=(4, 0))

        def on_keywords() -> None:
            self._show_keywords(name)

        keywords_button = ttk.Button(controls_row, text="Keywords", command=on_keywords)
        keywords_button.grid(row=0, column=1, sticky="e", padx=(4, 0))
        if hidden:
            keywords_button.state(["disabled"])

        def on_strength_change(value: float | str) -> None:
            try:
                normalized = round(float(value), 2)
            except (TypeError, ValueError):
                normalized = round(strength_var.get(), 2)
            strength_var.set(normalized)
            if self.on_change_callback:
                self.on_change_callback()
            self._notify_selection()

        slider = cast(Any, EnhancedSlider)(
            controls_row,
            from_=0.0,
            to=self.SLIDER_MAX,
            variable=strength_var,
            resolution=self.SLIDER_RESOLUTION,
            command=on_strength_change,
            length=180,
        )
        slider.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        annotation_label = ttk.Label(
            entry_frame,
            text="",
            justify="left",
            wraplength=self.NAME_WRAP_LENGTH,
            foreground="#e0a030",
        )
        annotation_label.grid(row=2, column=0, sticky="ew")
        annotation_label.grid_remove()
        inventory_label = ttk.Label(
            entry_frame,
            text="Inventory not verified; selection retained",
            wraplength=self.NAME_WRAP_LENGTH,
        )
        inventory_label.grid(row=3, column=0, sticky="ew")
        compatibility_label = ttk.Label(entry_frame, text="", wraplength=self.NAME_WRAP_LENGTH)
        compatibility_label.grid(row=4, column=0, sticky="ew")
        trigger_label = ttk.Label(entry_frame, text="", wraplength=self.NAME_WRAP_LENGTH)
        trigger_label.grid(row=5, column=0, sticky="ew")
        insert_button = ttk.Button(
            entry_frame,
            text="Insert Trigger Words",
            command=lambda: self._insert_trigger_words(name),
        )
        insert_button.grid(row=6, column=0, sticky="w", pady=(2, 0))
        insert_button.state(["disabled"])
        attach_tooltip(
            insert_button,
            "Append this LoRA's metadata-backed trigger words to the current slot's positive prompt. "
            "Nothing is saved or queued.",
        )

        self._lora_entries.append((name, strength_var, entry_frame))
        self._entry_widgets[name] = {
            "annotation_label": annotation_label,
            "frame": entry_frame,
            "name_row": name_row,
            "controls_row": controls_row,
            "name_label": name_label,
            "strength_var": strength_var,
            "strength_slider": slider,
            "keywords_button": keywords_button,
            "remove_button": remove_button,
            "inventory_label": inventory_label,
            "compatibility_label": compatibility_label,
            "trigger_label": trigger_label,
            "insert_button": insert_button,
        }
        self._refresh_selected_projection()

    def _notify_selection(self) -> None:
        listener = self.selection_listener
        if listener is not None:
            listener()
        self._render_browser()

    def set_annotations(self, annotations: dict[str, str]) -> None:
        """Show a note under each named selected LoRA (empty clears all); selections are never changed."""

        self._annotations = dict(annotations or {})
        for name, widgets in self._entry_widgets.items():
            label = widgets.get("annotation_label")
            if label is None:
                continue
            text = (
                REDACTED_TEXT
                if self._hidden_selection(name) and self._annotations.get(name)
                else self._annotations.get(name, "")
            )
            cast(Any, label).configure(
                text=f"⚠ {text}" if text and not text.startswith("verified") else text
            )
            if text:
                cast(Any, label).grid()
            else:
                cast(Any, label).grid_remove()

    def _remove_lora_entry(self, name: str) -> None:
        """Remove a LoRA entry from the list."""
        for i, (lora_name, _, frame) in enumerate(self._lora_entries):
            if lora_name == name:
                frame.destroy()
                self._lora_entries.pop(i)
                self._entry_widgets.pop(name, None)
                if self.on_change_callback:
                    self.on_change_callback()
                self._notify_selection()
                break

    def get_loras(self) -> list[tuple[str, float]]:
        """Return list of (name, strength) tuples."""
        return [(name, var.get()) for name, var, _ in self._lora_entries]

    def set_loras(self, loras: list[tuple[str, float]]) -> None:
        """Load LoRAs into UI."""
        # Clear existing
        for _, _, frame in self._lora_entries:
            frame.destroy()
        self._lora_entries.clear()
        self._entry_widgets.clear()

        # Add new
        for name, strength in loras:
            self._add_lora_entry(name, strength)
        self._notify_selection()

    def clear(self) -> None:
        """Clear all LoRAs."""
        for _, _, frame in self._lora_entries:
            frame.destroy()
        self._lora_entries.clear()
        self._entry_widgets.clear()

        if self.on_change_callback:
            self.on_change_callback()
        self._notify_selection()

    def _show_keywords(self, lora_name: str) -> None:
        """Show keyword detection dialog for a LoRA."""
        resource = self._resources.get(lora_name)
        if resource is None or self._hidden_selection(lora_name):
            self.discovery_status.set("Keyword evidence unavailable; refresh local inventory.")
            return
        metadata = LoRAMetadata(
            name=lora_name,
            path=resource.path,
            keywords=resource.keywords,
            source=resource.source,
            description=resource.description,
        )
        # Show dialog
        self._close_keywords()
        dialog = self._keyword_dialog = LoRAKeywordDialog(
            self,
            metadata=metadata,
            on_copy=lambda keywords: self._report_insertion(
                self._insert_keywords_to_prompt(keywords)
            ),
        )
        dialog.grab_set()

    def _close_keywords(self) -> None:
        dialog = self._keyword_dialog
        self._keyword_dialog = None
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()

    def _insert_trigger_words(self, lora_name: str) -> None:
        """Offer this LoRA's evidence-backed words to the prompt; nothing is inserted without this explicit action."""
        resource = self._resources.get(lora_name)
        if resource is None or self._hidden_selection(lora_name) or not resource.keywords:
            self.insertion_status.set("No trigger words are available to insert.")
            return
        self._report_insertion(self._insert_keywords_to_prompt(tuple(resource.keywords)))

    def _report_insertion(self, message: object) -> None:
        if isinstance(message, str):
            self.insertion_status.set(message)

    def _insert_keywords_to_prompt(self, keywords: str | Sequence[str]) -> str | None:
        """Insert keywords into the prompt editor and return a status message.

        This is a placeholder - will be overridden by parent frame.
        """
        text = keywords if isinstance(keywords, str) else ", ".join(keywords)
        # Just copy to clipboard for now
        self.clipboard_clear()
        self.clipboard_append(text)
        return None

    def _scan_loras(self) -> None:
        self._initial_scan = None
        self.refresh_loras()

    def refresh_loras(self) -> None:
        """Latest wins; at most one tracked scan and one coalesced pending request."""
        if self._closed:
            return
        self._request_id += 1
        self._verified = False
        self._cancel_scan.set()
        self.discovery_status.set(
            "Discovering local LoRAs… retained choices are not currently verified."
        )
        self._refresh_selected_projection()
        self._render_browser()
        if not self._scan_active:
            self._launch_refresh()

    def _launch_refresh(self) -> None:
        self._scan_active = True
        request = self._request_id
        cancel = self._cancel_scan = threading.Event()
        root, scanner, invoker = self.webui_root, self.scanner, self._invoker

        def work() -> None:
            resources, failed = {}, False
            snapshot = AssetRegistrySnapshot(())
            try:
                worker_scanner = scanner if scanner is not None else get_lora_scanner(root)
                resources = worker_scanner.scan_loras(read_only=True, cancelled=cancel.is_set)
                snapshot = worker_scanner.registry.snapshot
            except Exception:  # path/content-bearing exception text must never reach the GUI
                failed = True
            invoker.invoke(lambda: self._finish_refresh(request, resources, failed, snapshot))

        try:
            get_thread_registry().spawn(
                target=work, name="LoRA-Discovery", daemon=False, purpose="Read local LoRA evidence"
            )
        except Exception:
            self._finish_refresh(request, {}, True)

    def _finish_refresh(
        self,
        request: int,
        resources: dict[str, LoRAResource],
        failed: bool,
        snapshot: AssetRegistrySnapshot | None = None,
    ) -> None:
        if self._closed:
            return
        self._scan_active = False
        if request != self._request_id:
            self._launch_refresh()
            return
        if failed:
            self._inventory_names = None
            self.discovery_status.set(
                "Local discovery failed. Retained choices/inventory are unverified. Retry Refresh."
            )
        else:
            self._close_keywords()
            self._resources = resources
            self._inventory_names = frozenset(resources)
            self._asset_snapshot = snapshot or AssetRegistrySnapshot(())
            self._available_loras = list(resources)
            self._verified = True
            self.discovery_status.set(
                "Local discovery complete. Preview/compile and backend admission remain required."
            )
        self._refresh_visible_lora_names()
        self._refresh_selected_projection()
        self._render_browser()
        listener = self.inventory_listener
        if listener is not None:
            listener()

    def discovered_lora_names(self) -> frozenset[str] | None:
        """The last successful discovery's exact names, or ``None`` when no inventory is currently known."""
        return self._inventory_names

    def _refresh_selected_projection(self) -> None:
        target = target_profile(self._asset_snapshot, self._model_name)
        for name, widgets in self._entry_widgets.items():
            hidden = self._hidden_selection(name)
            label = cast(Any, widgets["name_label"])
            label.configure(text=REDACTED_TEXT if hidden else name)
            tooltip = getattr(label, "tooltip", None)
            if tooltip is not None:
                tooltip._hide()
                tooltip.text = REDACTED_TEXT if hidden else name
            cast(Any, widgets["keywords_button"]).state(["disabled"] if hidden else ["!disabled"])
            view = project_selected_lora(
                self._resources.get(name),
                verified=self._verified,
                hidden=hidden,
                policy=self._policy,
                target=target,
            )
            cast(Any, widgets["inventory_label"]).configure(text=view.availability)
            cast(Any, widgets["compatibility_label"]).configure(text=view.compatibility)
            trigger_text = " ".join((view.trigger_line, *view.warnings))
            cast(Any, widgets["trigger_label"]).configure(text=trigger_text)
            cast(Any, widgets["insert_button"]).state(
                ["!disabled"] if view.can_insert else ["disabled"]
            )
        self.set_annotations(self._annotations)

    def set_model_policy(self, policy: ModelPolicy | None, model_name: str = "") -> None:
        self._policy = policy
        self._model_name = model_name
        self._refresh_selected_projection()
        self._render_browser()

    def open_browser(self) -> None:
        from src.gui.widgets.lora_browser_dialog import LoRABrowserDialog

        if self._browser is None or self._browser.closed:
            self._browser = LoRABrowserDialog(self)
        else:
            self._browser.lift()

    def _render_browser(self) -> None:
        if self._browser is not None and not self._browser.closed:
            self._browser.render()

    def choose_from_browser(self, name: str, strength: float, selected: bool) -> None:
        if not selected:
            self._remove_lora_entry(name)
            return
        if name not in self._visible_loras:
            return
        for entry_name, variable, _ in self._lora_entries:
            if entry_name == name:
                variable.set(strength)
                break
        else:
            self._add_lora_entry(name, strength)
        if self.on_change_callback:
            self.on_change_callback()
        self._notify_selection()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self or self._closed:
            return
        self._closed = True
        self._cancel_scan.set()
        if self._initial_scan is not None:
            self.after_cancel(self._initial_scan)
            self._initial_scan = None
        if self._browser is not None and not self._browser.closed:
            self._browser.destroy()
        self._invoker.dispose()
