"""
Enhanced slider widget with arrow buttons for precise control
"""

import tkinter as tk
from tkinter import ttk


class EnhancedSlider(ttk.Frame):
    """Slider with arrow buttons and improved value display"""

    def __init__(
        self,
        parent,
        from_=0,
        to=100,
        variable=None,
        resolution=0.01,
        width=150,
        length=150,
        label="",
        command=None,
        **kwargs,
    ):
        # length is a valid ttk.Scale parameter, so we keep it
        if "length" in kwargs:
            length = kwargs.pop("length")
        else:
            length = 150  # Default value

        super().__init__(parent, **kwargs)

        self.variable = variable or tk.DoubleVar()
        self.command = command

        # Main frame for layout
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.X, expand=True)

        # Label
        if label:
            self.label_widget = ttk.Label(main_frame, text=label, width=12)
            self.label_widget.pack(side=tk.LEFT, padx=(0, 5))

        # Down arrow
        self.down_arrow = ttk.Button(
            main_frame,
            text="◀",
            width=3,
            style="Dark.TButton",
            command=lambda: self.set_value(self.variable.get() - resolution),
        )
        self.down_arrow.pack(side=tk.LEFT)

        # Slider
        self.slider = ttk.Scale(
            main_frame,
            from_=from_,
            to=to,
            orient=tk.HORIZONTAL,
            variable=self.variable,
            command=self._on_slider_change,
            length=length,
            style="Dark.Horizontal.TScale",
        )
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Up arrow
        self.up_arrow = ttk.Button(
            main_frame,
            text="▶",
            width=3,
            style="Dark.TButton",
            command=lambda: self.set_value(self.variable.get() + resolution),
        )
        self.up_arrow.pack(side=tk.LEFT)

        # Value entry
        self.value_entry = ttk.Entry(main_frame, textvariable=self.variable, width=6)
        self.value_entry.pack(side=tk.LEFT, padx=(5, 0))

        self.value_entry.bind("<Return>", self._on_entry_commit)
        self.value_entry.bind("<FocusOut>", self._on_entry_commit)

    def _on_slider_change(self, value_str):
        """Handle slider value change"""
        value = float(value_str)
        self.variable.set(round(value, 2))
        if self.command:
            self.command(self.variable.get())

    def _on_entry_commit(self, event=None):
        """Handle when user commits a value in the entry box"""
        try:
            value = float(self.value_entry.get())
            self.variable.set(value)
        except ValueError:
            # Revert to last valid value if input is invalid
            self.value_entry.delete(0, tk.END)
            self.value_entry.insert(0, f"{self.variable.get():.2f}")

        if self.command:
            self.command(self.variable.get())

    def set_value(self, value):
        """Set the slider's value programmatically"""
        self.variable.set(value)
        if self.command:
            self.command(value)

    def get_value(self):
        """Get the slider's current value"""
        return self.variable.get()

    def configure_state(self, state):
        """Enable or disable the entire widget"""
        for widget in [self.down_arrow, self.slider, self.up_arrow, self.value_entry]:
            widget.configure(state=state)

    def update_label(self, new_label):
        """Update the label text"""
        if hasattr(self, "label_widget"):
            self.label_widget.config(text=new_label)

    def _create_widgets(self, width, label):
        """Create the slider widgets"""
        # Left arrow button
        self.left_btn = ttk.Button(
            self, text="◀", width=3, style="Dark.TButton", command=self._decrease_value
        )
        self.left_btn.pack(side=tk.LEFT, padx=(0, 2))

        # Scale widget
        self.scale = ttk.Scale(
            self,
            from_=self.from_,
            to=self.to,
            variable=self.variable,
            orient=tk.HORIZONTAL,
            length=width,
            style="Dark.Horizontal.TScale",
        )
        self.scale.pack(side=tk.LEFT, padx=2)

        # Right arrow button
        self.right_btn = ttk.Button(
            self, text="▶", width=3, style="Dark.TButton", command=self._increase_value
        )
        self.right_btn.pack(side=tk.LEFT, padx=(2, 5))

        # Value display label
        self.value_label = ttk.Label(self, text="0.00", width=6)
        self.value_label.pack(side=tk.LEFT)

        # Update display
        self._update_display()

    def _decrease_value(self):
        """Decrease value by resolution"""
        current = self.variable.get()
        new_value = max(self.from_, current - self.resolution)
        self.variable.set(new_value)

    def _increase_value(self):
        """Increase value by resolution"""
        current = self.variable.get()
        new_value = min(self.to, current + self.resolution)
        self.variable.set(new_value)

    def _on_variable_change(self, *args):
        """Handle variable changes"""
        self._update_display()
        if self.command:
            self.command(self.variable.get())

    def _update_display(self):
        """Update the value display"""
        value = self.variable.get()
        # Format based on resolution
        if self.resolution >= 1:
            display_text = f"{int(value)}"
        elif self.resolution >= 0.1:
            display_text = f"{value:.1f}"
        else:
            display_text = f"{value:.2f}"

        self.value_label.config(text=display_text)

    def get(self):
        """Get current value"""
        return self.variable.get()

    def set(self, value):
        """Set current value"""
        self.variable.set(value)

    def configure(self, **kwargs):
        """Configure the slider"""
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if "state" in kwargs:
            state = kwargs.pop("state")
            self.scale.config(state=state)
            self.left_btn.config(state=state)
            self.right_btn.config(state=state)

        super().configure(**kwargs)
