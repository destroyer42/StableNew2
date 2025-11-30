# Renamed from prompt_tab_frame.py to prompt_tab_frame_v2.py
# ...existing code...

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from src.gui.app_state_v2 import AppStateV2
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.widgets.matrix_helper_widget import MatrixHelperDialog
from src.gui.tooltip import attach_tooltip
from src.gui.scrolling import enable_mousewheel
from src.gui.advanced_prompt_editor import AdvancedPromptEditorV2
from src.gui.theme_v2 import SURFACE_FRAME_STYLE, BODY_LABEL_STYLE


class PromptTabFrame(ttk.Frame):
	def apply_prompt_pack(self, summary) -> None:
		"""Apply a PromptPackSummary to the prompt editor fields."""
		if not summary:
			return
		# Update positive prompt
		if hasattr(self, "editor") and hasattr(summary, "prompt"):
			self.editor.delete("1.0", "end")
			self.editor.insert("1.0", getattr(summary, "prompt", ""))
		# Update negative prompt if present
		if hasattr(self, "negative_prompt_editor") and hasattr(summary, "negative_prompt"):
			self.negative_prompt_editor.delete("1.0", "end")
			self.negative_prompt_editor.insert("1.0", getattr(summary, "negative_prompt", ""))
	"""Prompt tab with slot selection, editor, and metadata preview."""

	def __init__(self, master: tk.Misc, app_state: Optional[AppStateV2] = None, *args, **kwargs) -> None:
		super().__init__(master, *args, **kwargs)
		self.workspace_state = PromptWorkspaceState()
		self.app_state = app_state
		self.workspace_state.new_pack("Untitled", slot_count=10)
		if self.app_state is not None:
			try:
				self.app_state.prompt_workspace_state = self.workspace_state
			except Exception:
				pass
		self.workspace_state.set_current_slot_index(0)
		self._suppress_editor_change = False

		self.columnconfigure(0, weight=1, uniform="prompt_col")
		self.columnconfigure(1, weight=2, uniform="prompt_col")
		self.columnconfigure(2, weight=1, uniform="prompt_col")
		self.rowconfigure(0, weight=1)

		self.left_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
		self.center_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)
		self.right_frame = ttk.Frame(self, padding=8, style=SURFACE_FRAME_STYLE)

		self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)
		self.center_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
		self.right_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=4)

		self._build_left_panel()
		self._build_center_panel()
		self._build_right_panel()
		self._refresh_editor()
		self._refresh_metadata()

	# Left column -------------------------------------------------------
	def _build_left_panel(self) -> None:
		header = ttk.Label(self.left_frame, text="Prompt Slots", style=BODY_LABEL_STYLE)
		header.pack(anchor="w")

		btn_frame = ttk.Frame(self.left_frame)
		btn_frame.pack(fill="x", pady=(4, 6))
		ttk.Button(btn_frame, text="New", command=self._on_new_pack).pack(side="left", padx=(0, 2))
		ttk.Button(btn_frame, text="Open...", command=self._on_open_pack).pack(side="left", padx=(0, 2))
		ttk.Button(btn_frame, text="Save", command=self._on_save_pack).pack(side="left", padx=(0, 2))
		ttk.Button(btn_frame, text="Save As...", command=self._on_save_pack_as).pack(side="left")

		self.slot_list = tk.Listbox(self.left_frame, exportselection=False, height=10)
		for i in range(10):
			self.slot_list.insert("end", f"Prompt {i+1}")
		self.slot_list.selection_set(0)
		self.slot_list.bind("<<ListboxSelect>>", self._on_slot_select)
		self.slot_list.pack(fill="both", expand=True, pady=(2, 0))
		enable_mousewheel(self.slot_list)
		attach_tooltip(self.slot_list, "Select a prompt slot to edit or apply.")

	# Center column -----------------------------------------------------
	def _build_center_panel(self) -> None:
		header_frame = ttk.Frame(self.center_frame)
		header_frame.pack(fill="x")
		self.pack_name_label = ttk.Label(header_frame, text="Editor", style=BODY_LABEL_STYLE)
		self.pack_name_label.pack(side="left")
		advanced_btn = ttk.Button(
			header_frame, text="Advanced Editor", command=self._on_open_advanced_editor
		)
		advanced_btn.pack(side="right", padx=(0, 4))
		attach_tooltip(advanced_btn, "Open the advanced prompt editor for the active prompt.")
		ttk.Button(header_frame, text="Insert Matrix...", command=self._open_matrix_helper).pack(
			side="right"
		)

		self.editor = tk.Text(self.center_frame, height=12, wrap="word")
		self.editor.pack(fill="both", expand=True, pady=(6, 0))
		self.editor.bind("<<Modified>>", self._on_editor_modified)
		enable_mousewheel(self.editor)
		attach_tooltip(self.editor, "Main prompt text for txt2img/img2img runs.")

	# Right column ------------------------------------------------------
	def _build_right_panel(self) -> None:
		self.summary_label = ttk.Label(self.right_frame, text="Current Slot Summary", style=BODY_LABEL_STYLE)
		self.summary_label.pack(anchor="w", pady=(0, 6))

		self.meta_text = tk.Text(self.right_frame, height=12, wrap="word", state="disabled")
		self.meta_text.pack(fill="both", expand=True)

	# Event handlers / helpers ------------------------------------------
	def _on_new_pack(self) -> None:
		if self.workspace_state.dirty:
			proceed = messagebox.askyesno("Unsaved Changes", "Discard unsaved changes and create a new pack?")
			if not proceed:
				return
		self.workspace_state.new_pack("Untitled", slot_count=10)
		self.workspace_state.set_current_slot_index(0)
		self.slot_list.selection_clear(0, "end")
		self.slot_list.selection_set(0)
		self._refresh_editor()
		self._refresh_metadata()

	def _on_slot_select(self, _event=None) -> None:
		try:
			sel = self.slot_list.curselection()
			if not sel:
				return
			self.workspace_state.set_current_slot_index(int(sel[0]))
			self._refresh_editor()
			self._refresh_metadata()
		except Exception:
			pass

	def _refresh_editor(self) -> None:
		slot = self.workspace_state.get_slot(self.workspace_state.get_current_slot_index())
		self._suppress_editor_change = True
		try:
			self.editor.delete("1.0", "end")
			if slot.text:
				self.editor.insert("1.0", slot.text)
			self.editor.edit_modified(False)
		finally:
			self._suppress_editor_change = False

	def _on_editor_modified(self, _event=None) -> None:
		if self._suppress_editor_change:
			self.editor.edit_modified(False)
			return
		if not self.editor.edit_modified():
			return
		text = self.editor.get("1.0", "end").rstrip("\n")
		try:
			self.workspace_state.set_slot_text(self.workspace_state.get_current_slot_index(), text)
			# keep UI indicator in sync
			self.pack_name_label.config(
				text=f"Editor - {self.workspace_state.current_pack.name if self.workspace_state.current_pack else 'None'} (modified)"
			)
		except Exception:
			pass
		self.editor.edit_modified(False)
		self._refresh_metadata()

	def _refresh_metadata(self) -> None:
		pack = self.workspace_state.current_pack
		slot_index = self.workspace_state.get_current_slot_index()
		slot = pack.get_slot(slot_index) if pack else None
		meta = self.workspace_state.get_current_prompt_metadata() if pack else None
		loras = meta.loras if meta else []
		embeds = meta.embeddings if meta else []
		dirty = " (modified)" if self.workspace_state.dirty else ""
		self.pack_name_label.config(text=f"Editor - {pack.name if pack else 'None'}{dirty}")
		summary_lines = [
			f"Pack: {pack.name if pack else 'None'}{dirty}",
			f"Slot: {slot_index + 1}",
		]
		if meta:
			summary_lines.extend(
				[
					f"Length: {meta.text_length} chars across {meta.line_count} line(s)",
					f"Matrix expressions: {meta.matrix_count}",
				]
			)
		summary_lines.extend(
			[
			"",
			"Detected LoRAs:",
			]
		)
		if loras:
			for ref in loras:
				if ref.weight is None:
					summary_lines.append(f" - {ref.name}")
				else:
					summary_lines.append(f" - {ref.name} (w={ref.weight})")
		else:
			summary_lines.append(" - None")
		summary_lines.append("")
		summary_lines.append("Detected Embeddings:")
		if embeds:
			for ref in embeds:
				summary_lines.append(f" - {ref.name}")
		else:
			summary_lines.append(" - None")
		summary_lines.append("")
		summary_lines.append("Pipeline Preview (conceptual):")
		if slot_index == 0:
			summary_lines.append(" - Intended as the base prompt for txt2img.")
		else:
			summary_lines.append(" - Additional prompt slot; mapping determined in pipeline tab.")

		self.meta_text.config(state="normal")
		self.meta_text.delete("1.0", "end")
		self.meta_text.insert("1.0", "\n".join(summary_lines))
		self.meta_text.config(state="disabled")

	def _open_matrix_helper(self) -> None:
		dialog = MatrixHelperDialog(self, on_apply=self._insert_matrix_expression)
		dialog.grab_set()
		dialog.wait_window(dialog)

	def _on_open_advanced_editor(self) -> None:
		controller = getattr(self.app_state, "controller", None) if self.app_state else None
		if controller and hasattr(controller, "on_open_advanced_editor"):
			try:
				controller.on_open_advanced_editor()
				return
			except Exception:
				pass
		self._open_advanced_editor_dialog()

	def _open_advanced_editor_dialog(self) -> None:
		top = tk.Toplevel(self)
		top.title("Advanced Prompt Editor")
		top.transient(self.winfo_toplevel())
		def _handle_apply(prompt_value: str, negative_value: Optional[str] = None) -> None:
			self.apply_prompt_text(prompt_value)
			try:
				top.destroy()
			except Exception:
				pass

		editor = AdvancedPromptEditorV2(
			top,
			initial_prompt=self.workspace_state.get_current_prompt_text(),
			on_apply=_handle_apply,
			on_cancel=lambda: top.destroy(),
		)
		editor.pack(fill="both", expand=True)
		try:
			top.grab_set()
		except Exception:
			pass

	def apply_prompt_text(self, prompt: str) -> None:
		text = prompt or ""
		try:
			index = self.workspace_state.get_current_slot_index()
			self.workspace_state.set_slot_text(index, text)
		except Exception:
			pass
		self._refresh_editor()
		self._refresh_metadata()

	def _insert_matrix_expression(self, expression: str) -> None:
		try:
			self.editor.insert("insert", expression)
			self._on_editor_modified()
		except Exception:
			pass

	def _on_open_pack(self) -> None:
		path = filedialog.askopenfilename(
			title="Open Prompt Pack",
			filetypes=[("Prompt Packs", "*.json"), ("All Files", "*.*")],
		)
		if not path:
			return
		try:
			self.workspace_state.load_pack(path)
			self.workspace_state.set_current_slot_index(0)
			self.slot_list.selection_clear(0, "end")
			self.slot_list.selection_set(0)
			self._refresh_editor()
			self._refresh_metadata()
		except Exception as exc:
			messagebox.showerror("Open Prompt Pack", f"Failed to open pack:\n{exc}")

	def _on_save_pack(self) -> None:
		pack = self.workspace_state.current_pack
		if pack is None:
			return
		path = pack.path
		if not path:
			return self._on_save_pack_as()
		try:
			self.workspace_state.save_current_pack()
			self._refresh_metadata()
		except Exception as exc:
			messagebox.showerror("Save Prompt Pack", f"Failed to save pack:\n{exc}")

	def _on_save_pack_as(self) -> None:
		path = filedialog.asksaveasfilename(
			title="Save Prompt Pack As",
			defaultextension=".json",
			filetypes=[("Prompt Packs", "*.json"), ("All Files", "*.*")],
		)
		if not path:
			return
		try:
			self.workspace_state.save_current_pack_as(path)
			self._refresh_metadata()
		except Exception as exc:
			messagebox.showerror("Save Prompt Pack", f"Failed to save pack:\n{exc}")

PromptTabFrame = PromptTabFrame
