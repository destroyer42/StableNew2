# Subsystem: Learning
# Role: Interactive Two-Axis Grid comparison view (cells at their frozen X/Y coordinates).

from __future__ import annotations

import queue
import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk
from typing import Any

from PIL import ImageTk

from src.gui.ui_tokens import TOKENS
from src.learning.grid_contact_sheet import ContactSheetError, export_contact_sheet, load_thumbnail
from src.learning.grid_results import GridCellModel, GridModel
from src.utils.thread_registry import get_thread_registry

THUMB = 96
_CACHE_LIMIT = 96
_STATUS_TEXT = {
    "completed": "Completed",
    "uncontrolled": "Uncontrolled",
    "requires_attention": "Needs attention",
}


class _Tile:
    def __init__(self, frame: tk.Frame, images: list[tk.Label]) -> None:
        self.frame = frame
        self.images = images


class LearningGridView(ttk.Frame):
    """Scrollable grid of result tiles; every tile is one frozen cell, never positioned by job order."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        learning_controller: Any,
        visibility_mode: str = "nsfw",
        on_cell_selected: Callable[[int], None] | None = None,
        on_presence_changed: Callable[[bool], None] | None = None,
        save_dialog: Callable[..., str] | None = None,
        confirm: Callable[[str, str], bool] | None = None,
        notify: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.learning_controller = learning_controller
        self.visibility_mode = visibility_mode
        self._on_cell_selected = on_cell_selected
        self._on_presence_changed = on_presence_changed
        self._present = False
        self._model_error = ""
        self._pending: set[tuple[str, int]] = set()
        self._save_dialog = save_dialog or filedialog.asksaveasfilename
        self._confirm = confirm or (
            lambda title, text: messagebox.askyesno(title, text, parent=self)
        )
        self._notify = notify or (lambda title, text: messagebox.showinfo(title, text, parent=self))
        self.tiles: dict[int, _Tile] = {}
        self.selected_index: int | None = None
        self.model: GridModel | None = None
        self._generation = 0
        self._destroyed = False
        self._results: queue.Queue[Any] = queue.Queue()
        self._cache: OrderedDict[tuple[str, int], Any] = OrderedDict()
        self._requested: set[tuple[str, int]] = set()
        self._labels_by_key: dict[tuple[str, int], list[tk.Label]] = {}
        self._render_after: str | None = None
        self._poll_after: str | None = None
        self._visible_after: str | None = None
        self._export_busy = False
        self._export_results: queue.Queue[Any] = queue.Queue()
        self._export_after: str | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 2))
        bar.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="No Two-Axis Grid experiment.")
        ttk.Label(bar, textvariable=self.summary_var, wraplength=520, justify="left").grid(
            row=0, column=0, sticky="w"
        )
        self.export_button = ttk.Button(
            bar, text="Export Contact Sheet", command=self._on_export, state="disabled"
        )
        self.export_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.canvas = tk.Canvas(
            self, width=520, height=300, highlightthickness=0, bg=TOKENS.colors.surface_secondary
        )
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self._on_yscroll, xscrollcommand=self._on_xscroll)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.vbar.grid(row=1, column=1, sticky="ns")
        self.hbar.grid(row=2, column=0, sticky="ew")
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_visible())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.bind("<Map>", lambda _e: self._schedule_visible(), add="+")

    # ---- public ------------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        """Debounced re-render from the controller's exact-association model; safe to call from callbacks."""
        if self._destroyed or self._render_after is not None:
            return
        self._render_after = self.after_idle(self._render)

    def set_visibility_mode(self, mode: str) -> None:
        if str(mode) == self.visibility_mode:
            return
        self.visibility_mode = str(mode)
        self._cache.clear()
        self.model = None
        self.refresh()

    # ---- rendering ---------------------------------------------------------------------------------------------
    def _current_model(self) -> GridModel | None:
        self._model_error = ""
        try:
            model: GridModel = self.learning_controller.get_grid_results_model(self.visibility_mode)
            return model
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            experiment = getattr(
                self.learning_controller.learning_state, "current_experiment", None
            )
            saved = str(getattr(experiment, "execution_snapshot_json", "") or "")
            if "two_axis_grid" in saved or "prompt_model_matrix" in saved:
                self._model_error = f"The saved grid cannot be shown: {exc}"
            return None

    def _render(self) -> None:
        self._render_after = None
        if self._destroyed:
            return
        model = self._current_model()
        selected = self._selected_from_state(model)
        present = model is not None or bool(self._model_error)
        if present != self._present:
            self._present = present
            if callable(self._on_presence_changed):
                self._on_presence_changed(self._present)
        if model is not None and model == self.model and selected == self.selected_index:
            return
        self._generation += 1
        self.model, self.selected_index = model, selected
        for child in self.inner.winfo_children():
            child.destroy()
        self.tiles.clear()
        self._labels_by_key.clear()
        self._requested.clear()
        self._pending.clear()
        if model is None:
            self.summary_var.set(self._model_error or "No Two-Axis Grid experiment.")
            self.export_button.configure(state="disabled")
            return
        self.summary_var.set(
            f"{model.title}\n{model.subtitle}\nColumns: {model.x_variable} | Rows: {model.y_variable} | "
            f"images {model.completed_total}/{model.planned_total}"
        )
        self.export_button.configure(
            state="normal" if model.exportable and not self._export_busy else "disabled"
        )
        ttk.Label(self.inner, text=f"{model.y_variable} \\ {model.x_variable}").grid(
            row=0, column=0, padx=4, pady=2
        )
        for col, label in enumerate(model.x_labels):
            ttk.Label(self.inner, text=label, font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=col + 1, padx=4, pady=2
            )
        for row, label in enumerate(model.y_labels):
            ttk.Label(self.inner, text=label, font=("TkDefaultFont", 9, "bold")).grid(
                row=row + 1, column=0, padx=4, pady=2, sticky="e"
            )
        for cell in model.cells:
            self._build_tile(cell, cell.index == selected)
        self.inner.update_idletasks()
        self._schedule_visible()

    def _selected_from_state(self, model: GridModel | None) -> int | None:
        state = self.learning_controller.learning_state
        if model is None or state.selected_variant is None:
            return None
        try:
            position = state.plan.index(state.selected_variant)
        except ValueError:
            return None
        return position if 0 <= position < len(model.cells) else None

    def _build_tile(self, cell: GridCellModel, selected: bool) -> None:
        frame = tk.Frame(
            self.inner,
            highlightthickness=3,
            highlightbackground=TOKENS.colors.accent_primary
            if selected
            else TOKENS.colors.border_subtle,
            bg=TOKENS.colors.surface_secondary,
            cursor="hand2",
        )
        frame.grid(row=cell.row + 1, column=cell.col + 1, padx=3, pady=3, sticky="nsew")
        status = _STATUS_TEXT.get(cell.status, cell.status.replace("_", " ").title())
        head = f"{status}{' (uncontrolled)' if cell.uncontrolled and cell.status != 'uncontrolled' else ''}"
        widgets: list[tk.Widget] = [
            tk.Label(
                frame,
                text=cell.label,
                bg=TOKENS.colors.surface_secondary,
                fg=TOKENS.colors.text_primary,
                font=("TkDefaultFont", 8, "bold"),
            ),
            tk.Label(
                frame,
                text=f"{head} | {cell.completed}/{cell.planned}",
                bg=TOKENS.colors.surface_secondary,
                fg=TOKENS.colors.text_muted,
                font=("TkDefaultFont", 8),
            ),
        ]
        images: list[tk.Label] = []
        strip = tk.Frame(frame, bg=TOKENS.colors.surface_secondary)
        if cell.images:
            for image in cell.images:
                text = "Loading..." if image.available else (cell.placeholder or "Artifact missing")
                holder = tk.Label(
                    strip,
                    text=text,
                    width=THUMB // 8,
                    height=THUMB // 16,
                    compound="top",
                    bg=TOKENS.colors.surface_primary,
                    fg=TOKENS.colors.text_muted,
                    wraplength=THUMB,
                )
                holder.pack(side="left", padx=1)
                images.append(holder)
                if image.available:
                    self._labels_by_key.setdefault((image.path, THUMB), []).append(holder)
                holder.image_path = image.path  # type: ignore[attr-defined]
                holder.caption = ""  # type: ignore[attr-defined]
        else:
            tk.Label(
                strip,
                text=cell.placeholder or "No images",
                width=THUMB // 8,
                height=THUMB // 16,
                wraplength=THUMB,
                bg=TOKENS.colors.surface_primary,
                fg=TOKENS.colors.text_muted,
            ).pack(side="left", padx=1)
        widgets.append(strip)
        widgets.append(
            tk.Label(
                frame,
                text=cell.rating_summary,
                bg=TOKENS.colors.surface_secondary,
                fg=TOKENS.colors.text_muted,
                font=("TkDefaultFont", 8),
            )
        )
        for widget in widgets:
            widget.pack(anchor="w", padx=2)

        def choose(_event: tk.Event[tk.Misc], index: int = cell.index) -> None:
            self._select(index)

        for widget in (frame, strip, *widgets, *images):
            widget.bind("<Button-1>", choose, add="+")
            widget.bind("<MouseWheel>", self._on_wheel, add="+")
        self.tiles[cell.index] = _Tile(frame, images)

    def _select(self, index: int) -> None:
        if self._destroyed or index == self.selected_index:
            return
        if callable(self._on_cell_selected):
            self._on_cell_selected(index)
        self.selected_index = index
        for position, tile in self.tiles.items():
            tile.frame.configure(
                highlightbackground=TOKENS.colors.accent_primary
                if position == index
                else TOKENS.colors.border_subtle
            )

    # ---- lazy thumbnails ---------------------------------------------------------------------------------------
    def _schedule_visible(self) -> None:
        if self._destroyed or self._visible_after is not None:
            return
        self._visible_after = self.after_idle(self._request_visible)

    def _viewport(self) -> tuple[int, int, int, int]:
        width = max(
            self.canvas.winfo_width(),
            int(self.canvas.cget("width")) if self.canvas.winfo_width() <= 1 else 0,
        )
        height = max(
            self.canvas.winfo_height(),
            int(self.canvas.cget("height")) if self.canvas.winfo_height() <= 1 else 0,
        )
        left, top = int(self.canvas.canvasx(0)), int(self.canvas.canvasy(0))
        return left, top, left + width, top + height

    def _request_visible(self) -> None:
        self._visible_after = None
        if self._destroyed or self.model is None or not self.winfo_ismapped():
            return  # <Map> and layout <Configure> events re-request once the view is actually shown
        self.inner.update_idletasks()
        if self.tiles and next(iter(self.tiles.values())).frame.winfo_width() <= 1:
            return  # geometry not computed yet; the inner frame's <Configure> follows
        left, top, right, bottom = self._viewport()
        wanted: list[str] = []
        for tile in self.tiles.values():
            frame = tile.frame
            x, y = frame.winfo_x(), frame.winfo_y()
            if (
                x > right
                or y > bottom
                or x + frame.winfo_reqwidth() < left
                or y + frame.winfo_reqheight() < top
            ):
                continue
            for holder in tile.images:
                key = (getattr(holder, "image_path", ""), THUMB)
                if key not in self._labels_by_key:
                    continue
                if key in self._cache:
                    self._attach(key)
                elif key not in self._requested:
                    self._requested.add(key)
                    self._pending.add(key)
                    wanted.append(key[0])
        if wanted:
            generation = self._generation
            get_thread_registry().spawn(
                self._decode_batch,
                args=(generation, wanted),
                name=f"learning-grid-thumbnails-{generation}",
                purpose="Decode bounded Learning grid thumbnails",
            )
            self._schedule_poll()

    def _decode_batch(self, generation: int, paths: list[str]) -> None:
        """Worker: file reads and PIL work only; no Tk object is created or touched here."""
        for path in paths:
            if generation != self._generation or self._destroyed:
                return
            try:
                picture = load_thumbnail(path, THUMB)
                self._results.put((generation, path, picture, ""))
            except (OSError, ValueError, SyntaxError, ContactSheetError, Warning) as exc:
                self._results.put(
                    (generation, path, None, f"Unreadable image ({type(exc).__name__})")
                )

    def _schedule_poll(self) -> None:
        if self._destroyed or self._poll_after is not None:
            return
        self._poll_after = self.after(40, self._drain)

    def _drain(self) -> None:
        self._poll_after = None
        if self._destroyed:
            return
        while True:
            try:
                generation, path, picture, error = self._results.get_nowait()
            except queue.Empty:
                break
            self.accept_thumbnail(generation, path, picture, error)
        if self._pending:
            self._schedule_poll()

    def accept_thumbnail(self, generation: int, path: str, picture: Any, error: str = "") -> bool:
        """Tk-thread entry for a decoded thumbnail; a response from an older render or a closed view is dropped."""
        if self._destroyed or generation != self._generation:
            if picture is not None:
                picture.close()
            return False
        key = (path, THUMB)
        self._pending.discard(key)
        if picture is None:
            for holder in self._labels_by_key.get(key, []):
                if holder.winfo_exists():
                    holder.configure(text=error or "Unreadable image")
            self._requested.discard(key)
            self._labels_by_key.pop(key, None)
            return True
        self._cache[key] = ImageTk.PhotoImage(picture)
        picture.close()
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        self._attach(key)
        return True

    def _attach(self, key: tuple[str, int]) -> None:
        photo = self._cache.get(key)
        if photo is None:
            return
        self._cache.move_to_end(key)
        for holder in self._labels_by_key.get(key, []):
            if holder.winfo_exists():
                holder.configure(image=photo, text="", width=THUMB, height=THUMB)
                holder.image = photo  # type: ignore[attr-defined]

    # ---- scrolling ---------------------------------------------------------------------------------------------
    def _on_inner_configure(self, _event: Any = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._schedule_visible()

    def _on_yscroll(self, first: float, last: float) -> None:
        self.vbar.set(first, last)
        self._schedule_visible()

    def _on_xscroll(self, first: float, last: float) -> None:
        self.hbar.set(first, last)
        self._schedule_visible()

    def _on_wheel(self, event: Any) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_shift_wheel(self, event: Any) -> None:
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")

    # ---- export ------------------------------------------------------------------------------------------------
    def _on_export(self) -> None:
        if self._export_busy or self.model is None or not self.model.exportable:
            return
        path = self._save_dialog(
            parent=self,
            title="Export Contact Sheet",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            confirmoverwrite=False,
        )
        if not path:
            return
        from pathlib import Path

        overwrite = False
        if Path(path).exists() or Path(path).with_suffix(".json").exists():
            if not self._confirm(
                "Replace contact sheet?",
                f"{Path(path).name} or its manifest already exists. Replace them?",
            ):
                return
            overwrite = True
        self._export_busy = True
        self.export_button.configure(state="disabled")
        # The model and protected paths are read here, on the Tk thread; the worker only renders and writes.
        model = self.model
        protected = [
            ref
            for variant in self.learning_controller.learning_state.plan
            for ref in variant.image_refs
        ]
        get_thread_registry().spawn(
            self._export_worker,
            args=(path, model, protected, overwrite),
            name="learning-grid-export",
            purpose="Render Learning grid contact sheet",
        )
        self._export_after = self.after(60, self._poll_export)

    def _export_worker(
        self, path: str, model: GridModel, protected: list[str], overwrite: bool
    ) -> None:
        outcome: tuple[str, Any] = ("error", "Export failed unexpectedly; see the log.")
        try:
            outcome = (
                "ok",
                export_contact_sheet(model, path, overwrite=overwrite, protected_paths=protected),
            )
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, MemoryError) as exc:
            outcome = ("error", str(exc) or type(exc).__name__)
        finally:
            self._export_results.put(outcome)

    def _poll_export(self) -> None:
        self._export_after = None
        if self._destroyed:
            return
        try:
            kind, value = self._export_results.get_nowait()
        except queue.Empty:
            self._export_after = self.after(60, self._poll_export)
            return
        self._export_busy = False
        self.export_button.configure(
            state="normal" if self.model is not None and self.model.exportable else "disabled"
        )
        if kind == "ok":
            extra = f" ({len(value.warnings)} image(s) could not be read)" if value.warnings else ""
            self._notify("Contact sheet exported", f"Saved {value.path.name}{extra}.")
        else:
            self._notify("Contact sheet not exported", str(value))

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    def _on_destroy(self, event: Any) -> None:
        if event.widget is not self:
            return
        self._destroyed = True
        self._generation += 1
        for name in ("_render_after", "_poll_after", "_visible_after", "_export_after"):
            handle = getattr(self, name, None)
            if handle:
                try:
                    self.after_cancel(handle)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        self._cache.clear()
        self._labels_by_key.clear()
