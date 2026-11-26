"""Desktop settings for the phone review gateway (RG-120): address, pinned certificate, sync secret, pairing,
devices, revocation and sync status.

Presentation only. Every action records intent on ``ReviewGatewaySync`` (which does its network and file work on its
own worker thread); this dialog reads ``status()`` snapshots on a Tk timer, so nothing here waits on the gateway.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from src.app.review_gateway_sync import ReviewGatewaySync, SyncStatus

_REFRESH_MS = 1000
_REASONS = {
    "digest_mismatch": "file changed since it was published",
    "unknown_item": "item not found",
    "revoked_device": "device revoked or not paired",
    "not_granted": "not permitted",
    "invalid_record": "invalid request",
    "favorite_with_delete": "favorite with delete",
    "archive_failed": "could not be archived",
    "admission_refused": "queue refused",
    "summary_changed": "summary changed; shown again",
    "action_unavailable": "action not possible",
    "prepare_required": "summary expired",
}


def _confirm(parent: tk.Misc, title: str, text: str) -> bool:
    return bool(messagebox.askyesno(title, text, parent=parent))


class ReviewGatewayDialog:
    def __init__(self, root: tk.Misc, sync: ReviewGatewaySync) -> None:
        self._root = root
        self._sync = sync
        self._dialog: tk.Toplevel | None = None
        self._timer: str | None = None
        #: Replaced by tests: a real modal would hang the run.
        self.confirm: Callable[[tk.Misc, str, str], bool] = _confirm
        self._vars: dict[str, tk.StringVar] = {}
        self._allow_queue: tk.BooleanVar | None = None
        self._pairing_scope = "review and queueing"
        self._devices: ttk.Treeview | None = None

    def open(self) -> None:
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.lift()
            return
        dialog = self._dialog = tk.Toplevel(self._root)
        dialog.title("Phone review gateway")
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        self._vars = {
            name: tk.StringVar(master=dialog)
            for name in ("address", "fingerprint", "secret", "status", "counts", "code", "refusals")
        }
        settings = ttk.LabelFrame(panel, text="Gateway (from its install output)", padding=8)
        settings.pack(fill="x")
        for row, (label, name, hidden) in enumerate(
            (
                ("Address (host:port or the installer's https://host:port)", "address", False),
                ("Certificate SHA-256 fingerprint", "fingerprint", False),
                ("Sync secret", "secret", True),
            )
        ):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(
                settings, textvariable=self._vars[name], width=56, show="*" if hidden else ""
            ).grid(row=row, column=1, sticky="ew", pady=2)
        buttons = ttk.Frame(settings)
        buttons.grid(row=3, column=1, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text="Save", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Forget", command=self.forget).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Sync now", command=self._sync.sync_now).pack(
            side="left", padx=(6, 0)
        )

        status = ttk.LabelFrame(panel, text="Status", padding=8)
        status.pack(fill="x", pady=(12, 0))
        ttk.Label(status, textvariable=self._vars["status"], wraplength=460).pack(anchor="w")
        ttk.Label(status, textvariable=self._vars["counts"], wraplength=460).pack(anchor="w")
        ttk.Label(status, textvariable=self._vars["refusals"], wraplength=460).pack(anchor="w")

        pairing = ttk.LabelFrame(panel, text="Phones", padding=8)
        pairing.pack(fill="both", expand=True, pady=(12, 0))
        top = ttk.Frame(pairing)
        top.pack(fill="x")
        ttk.Button(top, text="Pair a phone", command=self.pair).pack(side="left")
        ttk.Label(top, textvariable=self._vars["code"], font=("TkFixedFont", 14)).pack(
            side="left", padx=(12, 0)
        )
        self._allow_queue = tk.BooleanVar(master=dialog, value=True)
        ttk.Checkbutton(
            pairing,
            text="Allow queueing on phone (fix face or hands, more like this)",
            variable=self._allow_queue,
        ).pack(anchor="w", pady=(6, 0))
        devices = self._devices = ttk.Treeview(
            pairing, columns=("label", "enrolled", "access", "state"), show="headings", height=5
        )
        for column, heading, width in (
            ("label", "Phone", 160),
            ("enrolled", "Paired", 160),
            ("access", "Access", 110),
            ("state", "State", 80),
        ):
            devices.heading(column, text=heading)
            devices.column(column, width=width, anchor="w")
        devices.pack(fill="both", expand=True, pady=(8, 0))
        actions = ttk.Frame(pairing)
        actions.pack(anchor="e", pady=(6, 0))
        ttk.Button(actions, text="Queueing on/off", command=self.toggle_queue_selected).pack(
            side="left"
        )
        ttk.Button(actions, text="Revoke selected", command=self.revoke_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(panel, text="Close", command=self.close).pack(anchor="e", pady=(12, 0))
        self.refresh()

    def _parent(self) -> tk.Misc:
        return self._dialog if self._dialog is not None else self._root

    def close(self) -> None:
        if self._timer is not None:
            try:
                self._root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        if self._dialog is not None:
            self._dialog.destroy()
        self._dialog = self._devices = None

    def save(self) -> None:
        values = {name: self._vars[name].get() for name in ("address", "fingerprint", "secret")}
        try:
            self._sync.configure(values["address"], values["fingerprint"], values["secret"])
        except ValueError as error:
            messagebox.showerror("Phone review gateway", str(error), parent=self._parent())
            return
        except OSError:
            messagebox.showerror(
                "Phone review gateway",
                "Windows could not save the gateway settings.",
                parent=self._parent(),
            )
            return
        self._vars["secret"].set("")
        self.refresh()

    def forget(self) -> None:
        if self._dialog is None or not self.confirm(
            self._dialog,
            "Phone review gateway",
            "Forget the gateway address and sync secret? Paired phones stay paired on the gateway.",
        ):
            return
        try:
            self._sync.forget()
        except OSError:
            messagebox.showerror(
                "Phone review gateway",
                "Windows could not remove the settings.",
                parent=self._parent(),
            )
        self.refresh()

    def pair(self) -> None:
        allow_queue = bool(self._allow_queue.get()) if self._allow_queue is not None else False
        self._pairing_scope = "review and queueing" if allow_queue else "review only"
        try:
            code = self._sync.create_pairing(allow_queue=allow_queue)
        except (OSError, ValueError):
            messagebox.showerror(
                "Phone review gateway",
                "A pairing code could not be created.",
                parent=self._parent(),
            )
            return
        self._vars["code"].set(f"Code: {code}  (5 minutes, {self._pairing_scope})")

    def toggle_queue_selected(self) -> None:
        devices = self._devices
        if devices is None or not devices.selection():
            return
        device_id = str(devices.selection()[0])
        current = next((d for d in self._sync.status().devices if d.device_id == device_id), None)
        if current is None or current.revoked:
            return
        try:
            self._sync.set_queue(device_id, "queue" not in current.scopes)
        except OSError:
            messagebox.showerror(
                "Phone review gateway", "The change could not be saved.", parent=self._parent()
            )
        self.refresh()

    def revoke_selected(self) -> None:
        devices = self._devices
        if devices is None or self._dialog is None:
            return
        selected = devices.selection()
        if not selected:
            return
        device_id = str(selected[0])
        label = str(devices.item(device_id, "values")[0])
        if not self.confirm(
            self._dialog,
            "Revoke phone",
            f"Revoke {label}? Its decisions are refused from now on.",
        ):
            return
        try:
            self._sync.revoke(device_id)
        except OSError:
            messagebox.showerror(
                "Phone review gateway", "The revocation could not be saved.", parent=self._parent()
            )
        self.refresh()

    def refresh(self) -> None:
        self._timer = None
        if self._dialog is None or not self._dialog.winfo_exists():
            return
        self.render(self._sync.status())
        self._timer = self._root.after(_REFRESH_MS, self.refresh)

    def render(self, status: SyncStatus) -> None:
        self._vars["status"].set(
            status.message + (f"  Gateway: {status.address}" if status.address else "")
        )
        self._vars["counts"].set(
            f"Published {status.published}; waiting to publish {status.pending_publish}; "
            f"refused {status.refused}. Last publish {status.last_publish_at or 'never'}; "
            f"last pull {status.last_pull_at or 'never'}."
        )
        refusals = ", ".join(
            _REASONS.get(reason, reason) for _at, reason in status.recent_refusals[:3]
        )
        self._vars["refusals"].set(f"Recent refusals: {refusals}" if refusals else "")
        if status.pairing_code:
            self._vars["code"].set(
                f"Code: {status.pairing_code}  (5 minutes, {self._pairing_scope})"
            )
        elif self._vars["code"].get():
            self._vars["code"].set("")
        devices = self._devices
        if devices is None:
            return
        wanted = {device.device_id: device for device in status.devices}
        for existing in devices.get_children():
            if existing not in wanted:
                devices.delete(existing)
        for device in status.devices:
            values = (
                device.label or device.device_id[:12],
                device.enrolled_at,
                "review, queue" if "queue" in device.scopes else "review",
                "revoked" if device.revoked else "active",
            )
            if devices.exists(device.device_id):
                devices.item(device.device_id, values=values)
            else:
                devices.insert("", "end", iid=device.device_id, values=values)


class ReviewGatewayControl:
    """Lifecycle owner: the worker starts after the window is up and is signalled (not joined) on shutdown."""

    def __init__(self, root: tk.Misc, sync: ReviewGatewaySync) -> None:
        self.sync = sync
        self.dialog = ReviewGatewayDialog(root, sync)

    def start(self) -> None:
        self.sync.start()

    def shutdown(self) -> None:
        self.sync.stop(timeout=0)


def install_review_gateway_control(
    root: tk.Tk, app: Any, header: ttk.Frame
) -> ReviewGatewayControl:
    from src.app.runtime_stack import build_review_gateway_sync

    control = ReviewGatewayControl(root, build_review_gateway_sync(app))
    button = ttk.Button(
        header, text="Phone Review", style="Secondary.TButton", command=control.dialog.open
    )
    button.grid(row=0, column=header.grid_size()[0], padx=4, pady=4)
    root.after(0, control.start)
    return control
