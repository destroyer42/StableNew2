from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class MatrixHelperDialog(tk.Toplevel):
    """Minimal dialog to build matrix expressions like {opt1|opt2|opt3}."""

    def __init__(self, master: tk.Misc, on_apply: Optional[Callable[[str], None]] = None):
        super().__init__(master)
        self.title("Matrix Helper")
        self.on_apply = on_apply
        self.result: str | None = None
        self.resizable(True, True)

        ttk.Label(self, text="Enter one option per line:").pack(anchor="w", padx=8, pady=(8, 4))
        self.text = tk.Text(self, height=8, width=40, wrap="word")
        self.text.pack(fill="both", expand=True, padx=8, pady=4)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).pack(side="right", padx=(4, 0))
        ttk.Button(btn_frame, text="Insert", command=self._on_apply).pack(side="right")

    def _build_matrix_expression(self) -> str:
        options = [line.strip() for line in self.text.get("1.0", "end").splitlines() if line.strip()]
        return "{" + "|".join(options) + "}" if options else ""

    def _on_apply(self) -> None:
        self.result = self._build_matrix_expression()
        if self.on_apply and self.result:
            try:
                self.on_apply(self.result)
            except Exception:
                pass
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
