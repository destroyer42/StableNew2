"""Tooltip widget for displaying help text on hover.

PR-GUI-TOOLTIPS-001: Reusable tooltip system for the entire GUI.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class HoverTooltip:
    """Shows a tooltip window on hover with detailed information.
    
    Usage:
        label = ttk.Label(parent, text="My Label")
        HoverTooltip(label, "This is a helpful tooltip explaining the feature.")
    """
    
    def __init__(
        self,
        widget: tk.Widget,
        text: str,
        delay: int = 500,
        wrap_length: int = 400,
        bg: str = "#2B2A2E",
        fg: str = "#E0E0E0",
        border_color: str = "#D4AF37",
    ):
        """Initialize the tooltip.
        
        Args:
            widget: The widget to attach the tooltip to
            text: The tooltip text to display
            delay: Delay in milliseconds before showing tooltip
            wrap_length: Maximum width of tooltip text before wrapping
            bg: Background color
            fg: Foreground (text) color
            border_color: Border color
        """
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wrap_length = wrap_length
        self.bg = bg
        self.fg = fg
        self.border_color = border_color
        
        self._after_id: str | None = None
        self._tooltip_window: tk.Toplevel | None = None
        
        # Bind events
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        widget.bind("<Button>", self._on_leave)  # Hide on click
    
    def _on_enter(self, event: tk.Event | None = None) -> None:
        """Handle mouse enter event - schedule tooltip display."""
        self._cancel_scheduled()
        self._after_id = self.widget.after(self.delay, self._show_tooltip)
    
    def _on_leave(self, event: tk.Event | None = None) -> None:
        """Handle mouse leave event - hide tooltip and cancel schedule."""
        self._cancel_scheduled()
        self._hide_tooltip()
    
    def _cancel_scheduled(self) -> None:
        """Cancel any scheduled tooltip display."""
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
    
    def _show_tooltip(self) -> None:
        """Display the tooltip window near the cursor."""
        if self._tooltip_window:
            return
        
        # Get cursor position
        x = self.widget.winfo_pointerx() + 10
        y = self.widget.winfo_pointery() + 10
        
        # Create tooltip window
        self._tooltip_window = tk.Toplevel(self.widget)
        self._tooltip_window.wm_overrideredirect(True)  # Remove window decorations
        self._tooltip_window.wm_geometry(f"+{x}+{y}")
        
        # Create label with text
        label = tk.Label(
            self._tooltip_window,
            text=self.text,
            background=self.bg,
            foreground=self.fg,
            relief="solid",
            borderwidth=1,
            wraplength=self.wrap_length,
            justify="left",
            padx=8,
            pady=6,
            font=("Segoe UI", 9),
        )
        label.pack()
        
        # Configure border color
        try:
            self._tooltip_window.config(highlightbackground=self.border_color, highlightthickness=1)
        except Exception:
            pass
    
    def _hide_tooltip(self) -> None:
        """Destroy the tooltip window."""
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None


__all__ = ["HoverTooltip"]
