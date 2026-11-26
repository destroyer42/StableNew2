"""Desktop control for the live update (LAUNCH-UPDATE-1): Update and restart, the remote-update switch, the receipt.

Presentation only. Git, the wait for the running job and the updater launch run on registry worker threads inside
``LiveUpdateService``; this module reads plain attributes on a Tk timer, so Tk never waits. When the service asks for
the restart, the timer calls the window's normal graceful exit (the only Tk-thread effect).
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from src.app import live_update as lu
from src.app.live_update_service import LiveUpdateService, Outcome
from src.utils.thread_registry import get_thread_registry

log = logging.getLogger(__name__)

_TICK_MS = 1000
_RESULT_POLLS = 150  # 2 s apart: the updater confirms health within its 180 s window


def _confirm(parent: tk.Misc, title: str, text: str) -> bool:
    return bool(messagebox.askyesno(title, text, parent=parent))


def describe(receipt: dict[str, Any] | None) -> str:
    if not receipt:
        return "No update has run yet."
    status = receipt.get("status")
    old = str(receipt.get("old_sha") or "")[:10]
    new = str(receipt.get("new_sha") or "")[:10]
    when = receipt.get("finished_at") or ""
    if status == "applied":
        health = " (start not confirmed)" if receipt.get("health") == "unconfirmed" else ""
        return f"Updated {old} -> {new}{health}. {when}"
    if status == "already_current":
        return f"Already up to date at {old}. {when}"
    reason = str(receipt.get("reason") or "")
    return f"Not updated: {lu.REASON_TEXT.get(reason, reason)} {when}".strip()


def describe_check(check: lu.Preflight) -> str:
    if check.ok:
        return f"Update available: {check.old_sha[:10]} -> {check.target_sha[:10]} ({check.commits_ahead} commit(s))."
    text = lu.REASON_TEXT.get(check.reason, check.reason)
    return f"{text} {check.detail}".strip()


class LiveUpdateControl:
    """Lifecycle owner: collects the previous update's receipt at start and performs the requested restart."""

    def __init__(
        self,
        root: tk.Misc,
        service: LiveUpdateService,
        request_exit: Callable[[str], None],
        head_sha: Callable[[], str],
    ) -> None:
        self._root = root
        self.service = service
        self._request_exit = request_exit
        self._head_sha = head_sha
        self._exit_sent = False
        self._timer: str | None = None
        self._stop = threading.Event()
        self._unsubscribe: Callable[[], None] | None = None
        self.head = ""
        self.message = ""
        self.receipt: dict[str, Any] | None = service.last_result()
        self.dialog = LiveUpdateDialog(root, self)

    def start(self) -> None:
        self._unsubscribe = get_thread_registry().add_shutdown_listener(self._stop.set)
        self._spawn(self._collect_previous, "Live update receipt")
        self._timer = self._root.after(_TICK_MS, self._tick)

    def shutdown(self) -> None:
        self._stop.set()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._timer is not None:
            try:
                self._root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None

    # -- worker side -----------------------------------------------------------------------------------------------

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        get_thread_registry().spawn(target=target, name=name, purpose=name)

    def _collect_previous(self) -> None:
        try:
            self.head = self._head_sha()
            self.service.mark_started(self.head)
            for _ in range(_RESULT_POLLS):
                receipt = self.service.collect_result()
                if receipt is not None:
                    self.receipt = receipt
                    self.message = describe(receipt)
                    return
                if self.service.store.read("intent.json") is None or self._stop.wait(2.0):
                    return
        except Exception:  # noqa: BLE001 - a receipt problem must never stop the app from starting
            log.exception("Live update: the previous update's receipt could not be read")

    def check(self) -> None:
        self.message = "Checking origin/main..."
        self._spawn(self._run_check, "Live update check")

    def _run_check(self) -> None:
        try:
            self.message = describe_check(self.service.check())
        except Exception as error:  # noqa: BLE001 - shown to the owner instead of failing silently
            self.message = f"The check failed: {error}"

    def update(self) -> None:
        self.message = "Checking..."
        self._spawn(self._run_update, "Live update")

    def _run_update(self) -> None:
        try:
            outcome: Outcome = self.service.update(source="desktop", expected_sha=None)
        except Exception as error:  # noqa: BLE001
            self.message = f"The update failed: {error}"
            return
        if outcome.status == "restarting":
            self.message = (
                f"Restarting to update {outcome.old_sha[:10]} -> {outcome.target_sha[:10]}..."
            )
        else:
            self.receipt = self.service.last_result()
            self.message = describe(self.receipt)

    # -- Tk side ---------------------------------------------------------------------------------------------------

    def _tick(self) -> None:
        self._timer = None
        if self.service.exit_requested and not self._exit_sent:
            self._exit_sent = True
            log.info("Live update: closing StableNew for the restart")
            self._request_exit("live-update")
            return
        self.dialog.render()
        self._timer = self._root.after(_TICK_MS, self._tick)


class LiveUpdateDialog:
    def __init__(self, root: tk.Misc, control: LiveUpdateControl) -> None:
        self._root = root
        self._control = control
        self._window: tk.Toplevel | None = None
        self._vars: dict[str, tk.Variable] = {}
        #: Replaced by tests: a real modal would hang the run.
        self.confirm: Callable[[tk.Misc, str, str], bool] = _confirm

    def open(self) -> None:
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            return
        window = self._window = tk.Toplevel(self._root)
        window.title("Update StableNew")
        window.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        self._vars = {
            "head": tk.StringVar(master=window),
            "message": tk.StringVar(master=window),
            "receipt": tk.StringVar(master=window),
            "remote": tk.BooleanVar(master=window, value=self._control.service.allow_remote()),
        }
        ttk.Label(panel, textvariable=self._vars["head"]).pack(anchor="w")
        ttk.Label(panel, textvariable=self._vars["message"], wraplength=460).pack(
            anchor="w", pady=(8, 0)
        )
        ttk.Label(panel, textvariable=self._vars["receipt"], wraplength=460).pack(
            anchor="w", pady=(8, 0)
        )
        ttk.Label(
            panel,
            text=(
                "Update and restart fast-forwards this checkout's main to origin/main, waits for the running job, "
                "restarts StableNew and resumes the queue. It never installs packages."
            ),
            wraplength=460,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(
            panel,
            text="Allow remote update (a phone with an admin grant can request it)",
            variable=self._vars["remote"],
            command=self._toggle_remote,
        ).pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Check for update", command=self._control.check).pack(side="left")
        ttk.Button(buttons, text="Update and restart", command=self._update).pack(
            side="left", padx=8
        )
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.render()

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()
        self._window = None

    def render(self) -> None:
        if self._window is None or not self._window.winfo_exists():
            return
        control = self._control
        self._vars["head"].set(f"This checkout: main at {control.head[:10] or 'unknown'}")
        self._vars["message"].set(control.message)
        self._vars["receipt"].set(f"Last update: {describe(control.receipt)}")

    def _toggle_remote(self) -> None:
        remote = self._vars["remote"]
        allowed = isinstance(remote, tk.BooleanVar) and remote.get()
        try:
            self._control.service.set_allow_remote(allowed)
        except OSError:
            remote.set(not allowed)
            messagebox.showerror(
                "Update StableNew",
                "The setting could not be saved.",
                parent=self._window or self._root,
            )

    def _update(self) -> None:
        if self._window is None:
            return
        if not self.confirm(
            self._window,
            "Update and restart",
            "Fast-forward to origin/main and restart StableNew when the running job has finished?",
        ):
            return
        self._control.update()


def install_live_update_control(root: tk.Tk, app: Any, window: Any) -> LiveUpdateControl:
    from src.app.runtime_stack import build_live_update_service

    service = build_live_update_service(app)
    git = lu.subprocess_git(service.repo_root)

    def head_sha() -> str:
        result = git(["rev-parse", "HEAD"])
        return result.out if result.code == 0 else ""

    control = LiveUpdateControl(root, service, window.request_graceful_exit, head_sha)
    header = window.header_zone
    button = ttk.Button(
        header, text="Update", style="Secondary.TButton", command=control.dialog.open
    )
    button.grid(row=0, column=header.grid_size()[0], padx=4, pady=4)
    root.after(0, control.start)
    return control
