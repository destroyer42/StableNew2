"""One golden-path journey run: isolated workspace, backends, a (restartable) real app and the chosen desktop driver."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk
from typing import Any

from tools.operator_journey.capture import FaultCapture, leaked_non_daemon_threads, thread_snapshot
from tools.operator_journey.dialogs import DialogSeam, scripted_dialogs
from tools.operator_journey.evidence import JourneyEvidence
from tools.operator_journey.golden.frozen import PlanGate
from tools.operator_journey.golden.media import sha256_file
from tools.operator_journey.observe import (
    SubmissionObserver,
    job_lifecycle_settled,
    read_job_rows,
)
from tools.operator_journey.owned import OwnedResources
from tools.operator_journey.tk_driver import ActionTrace, JourneyTimeout, TkDriver, WidgetNotFound
from tools.operator_journey.workspace import (
    AccessSpy,
    OperatorWorkspace,
    UserDataGuard,
    archive_workspace,
    repo_sha,
)


class JourneyAbort(RuntimeError):
    """The journey cannot continue; the message is the failed assertion."""


class JourneyHold(RuntimeError):
    """A prerequisite is unmet (not a product failure)."""


class JourneyNoGo(RuntimeError):
    """A safety or resource condition forbids continuing."""


@dataclass
class RunConfig:
    driver: str = "tk"  # "tk" (semantic widget calls) or "windows" (physical Win32 input)
    evidence_dir: Path = Path("reports/operator_journeys")
    hide_window: bool = False
    startup_wait: float = 60.0
    run_timeout: float = 180.0
    window_geometry: str = "1500x940+10+10"
    maximize: bool = True  # windows driver: maximize with a title-bar double-click so every run has the same canvas
    #: windows driver window layout: "maximized" (title-bar double-click, recorded as a workaround), "normal" (the
    #: application's own startup window, nothing forced) or "minimum" (resized to the application's declared minimum).
    layout: str = "maximized"
    discard_workspace: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


def create_root() -> tk.Tk:
    import sys

    if sys.platform.startswith("win"):
        base = os.path.dirname(os.path.abspath(tk.__file__))
        for name, sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
            candidate = os.path.join(base, "tcl", sub)
            if os.path.isdir(candidate):
                os.environ.setdefault(name, candidate)
    return tk.Tk()


class GoldenRun:
    """Owns everything one journey touches; journeys receive it and drive ``self.driver``."""

    def __init__(
        self,
        journey_id: str,
        config: RunConfig,
        evidence: JourneyEvidence,
        workspace: OperatorWorkspace,
        *,
        fake_a1111: Any = None,
        fake_comfy: Any = None,
    ) -> None:
        self.journey_id, self.config, self.ev, self.ws = journey_id, config, evidence, workspace
        self.fake_a1111, self.fake_comfy = fake_a1111, fake_comfy
        self.trace = ActionTrace()
        target, key = config.extras.get("target"), config.extras.get("journey_key")
        # A physical run declines any submission whose NJR disagrees with the frozen plan (it can only decline).
        self.submissions: SubmissionObserver = (
            PlanGate(key, target) if target and key else SubmissionObserver()
        )
        self.responder: Any = None
        self.seam = DialogSeam()
        self._seam_cm: Any = None
        self.faults: FaultCapture | None = None
        self.driver: TkDriver
        self.window: Any
        self.controller: Any
        self.app_state: Any
        self.root: tk.Tk | None = None
        self.screens_dir = Path(evidence.summary.get("evidence_dir", ".")) / "screenshots"
        self.boots = 0
        self._baseline_threads = {t.name for t in threading.enumerate()}

    # -- plumbing ----------------------------------------------------------------
    def check(self, phase: str, name: str, passed: bool, detail: str = "") -> bool:
        return self.ev.check(phase, name, passed, "" if passed else detail)

    def require(self, phase: str, name: str, passed: bool, detail: str = "") -> None:
        if not self.check(phase, name, passed, detail):
            raise JourneyAbort(f"{phase}/{name}: {detail}")

    def checkpoint(self, label: str) -> None:
        self.ev.thread_checkpoints.append(thread_snapshot(label))

    def snap(self, name: str) -> None:
        """Screenshot of what the operator sees (windows driver only; the semantic driver has no display contract)."""

        if hasattr(self.driver, "screenshot"):
            self.driver.screenshot(self.screens_dir, f"{self.boots}_{name}")  # type: ignore[attr-defined]

    @property
    def repository_path(self) -> Path:
        return Path(self.controller._job_repository_path)

    def job_rows(self) -> list[dict[str, Any]]:
        return read_job_rows(self.repository_path, self.ws.root)

    def assert_plan_agreed(self) -> None:
        """Stop the journey as NO-GO when the frozen-plan gate declined a submission (nothing was queued)."""

        mismatches = getattr(self.submissions, "mismatches", [])
        if mismatches:
            raise JourneyNoGo(
                "the NJR about to be dispatched disagrees with the frozen plan: "
                + "; ".join(mismatches)
            )

    def wait_jobs_terminal(self, expected: int, *, description: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        abort_check = self.config.extras.get("abort_check")

        def probe() -> bool:
            nonlocal rows
            reason = abort_check() if callable(abort_check) else None
            if reason:
                raise JourneyNoGo(str(reason))
            self.assert_plan_agreed()
            rows = self.job_rows()
            return job_lifecycle_settled(rows, expected)

        self.driver.wait_until(
            probe,
            timeout=self.config.run_timeout,
            description=description,
            evidence=lambda: [(r["job_id"], r["status"]) for r in self.job_rows()],
        )
        self.driver.pump(1.5)  # settle: a duplicate or retry would appear as extra rows here
        rows = self.job_rows()
        self.checkpoint("jobs_terminal")
        return rows

    # -- dialogs: scripted answers at the dialog boundary (tk driver) or real native/Tk dialogs (windows driver) ----
    def answer_file(self, path: str) -> None:
        if self.config.driver == "windows":
            self.responder.queue("file", str(path))
        else:
            self.seam.files.append(str(path))

    def answer_yesno(self, yes: bool = True) -> None:
        if self.config.driver == "windows":
            self.responder.queue("button", "Yes" if yes else "No")
        else:
            self.seam.answers.append(bool(yes))

    def answer_string(self, text: str, *, ok_label: str = "OK") -> None:
        """Answer the next ``simpledialog.askstring`` (a Tk dialog): typed into its entry, confirmed with OK."""

        if self.config.driver != "windows":
            self.seam.strings.append(text)
            return
        d, root = self.driver, self.root
        assert root is not None
        state = {"stage": 0, "tries": 0}

        def tick() -> None:
            state["tries"] += 1
            from tools.operator_journey.tk_driver import iter_widgets

            top = entry = ok = None
            for (
                candidate
            ) in root.winfo_children():  # any visible dialog with an entry and the OK button
                if not (isinstance(candidate, tk.Toplevel) and candidate.winfo_viewable()):
                    continue
                found_entry = next(
                    (w for w in iter_widgets(candidate) if isinstance(w, (tk.Entry, ttk.Entry))),
                    None,
                )
                found_ok = next(
                    (
                        w
                        for w in iter_widgets(candidate)
                        if isinstance(w, (tk.Button, ttk.Button))
                        and str(w.cget("text")) == ok_label
                    ),
                    None,
                )
                if found_entry is not None and found_ok is not None:
                    top, entry, ok = candidate, found_entry, found_ok
                    break
            if top is None:
                if (
                    state["tries"] < 1200
                ):  # ~2 minutes: a slow dialog is not a reason to leave it unanswered
                    root.after(100, tick)
                else:
                    self.trace.record("dialog_never_appeared", label=ok_label)
                return
            win = d.win32  # type: ignore[attr-defined]
            if state["stage"] == 0:
                x, y = d._center(entry)  # type: ignore[attr-defined]
                win.click(x, y)
                win.press(0x23)  # End
                for _ in range(len(str(entry.get())) + 3):
                    win.press(0x08)  # Backspace the suggested text away, as a person would
                win.type_text(text)
                self.trace.record("type_in_dialog", label=top.title(), value=text)
                state["stage"] = 1
                root.after(150, tick)
            elif str(entry.get()) != text:
                self.trace.record(
                    "dialog_entry_mismatch", label=top.title(), shown=str(entry.get()), wanted=text
                )
                state["stage"] = 0
                root.after(150, tick)
            else:
                x, y = d._center(ok)  # type: ignore[attr-defined]
                win.click(x, y)
                self.trace.record("click", label=f"dialog {ok_label}", x=x, y=y)

        root.after(200, tick)

    # -- app lifecycle ------------------------------------------------------------------
    def boot_app(self) -> None:
        from src.app_factory import build_v2_app

        self.boots += 1
        # The real application is a new process with a fresh thread registry.  In the harness every boot after the
        # first in this process (a reopen within a journey, or the next journey of the suite) would inherit the
        # previous application's "shutdown requested" registry and decline every queue submission, so each boot
        # starts from a fresh one.
        import src.utils.thread_registry as thread_registry

        thread_registry._global_registry = None
        thread_registry.ThreadRegistry._instance = None
        root = create_root()
        self.root = root
        if self.config.hide_window:
            root.withdraw()
        else:
            root.geometry(self.config.window_geometry)
        self.trace = ActionTrace()
        if self._seam_cm is None and self.config.driver != "windows":
            self._seam_cm = scripted_dialogs(self.seam)
            self._seam_cm.__enter__()
        if self.config.driver == "windows":
            from tools.operator_journey.desktop import (
                NativeDialogResponder,
                WindowsDesktopDriver,
            )

            self.driver = WindowsDesktopDriver(root, self.trace)
            self.responder = NativeDialogResponder(self.driver.win32, os.getpid())  # type: ignore[attr-defined]
            self.responder.__enter__()
        else:
            self.driver = TkDriver(root, self.trace)
        self.faults = FaultCapture(root)
        self.faults.__enter__()
        _, self.app_state, self.controller, self.window = build_v2_app(
            root=root,
            webui_manager=None,  # an external endpoint is never adopted or managed
            threaded=True,
            config_manager=self.ws.config_manager(),
        )
        self.driver.pump(0.8)
        if self.config.driver == "windows":
            self.driver.ensure_foreground()  # type: ignore[attr-defined]
            if not self.config.hide_window:
                self.ev.observe(
                    f"window_requested_{self.boots}",
                    {"geometry": self.config.window_geometry, "layout": self.config.layout},
                )
                self.ev.observe(
                    f"window_startup_{self.boots}",
                    self.driver.window_facts(),  # type: ignore[attr-defined]
                )
                if self.config.layout == "minimum":
                    min_w, min_h = self.root.minsize()  # type: ignore[union-attr]
                    self.root.state("normal")  # type: ignore[union-attr]
                    self.root.geometry(f"{max(min_w, 1)}x{max(min_h, 1)}+20+20")  # type: ignore[union-attr]
                    self.driver.pump(1.0)
                elif self.config.layout == "maximized" and self.config.maximize:
                    self.driver.maximize_window()  # type: ignore[attr-defined]
                    self.driver.pump(0.8)
                self.ev.observe(
                    f"window_{self.boots}",
                    self.driver.window_facts(),  # type: ignore[attr-defined]
                )
        self.submissions.install(self.controller.job_service)
        self.checkpoint(f"app_started_{self.boots}")

    def await_models(
        self, *, description: str = "StableNew projects at least one image model"
    ) -> None:
        """Click Refresh like an operator until the resource projection lists an image model."""

        d, refresh = self.driver, self.window.header_zone.refresh_button
        last = float("-inf")

        def projected() -> bool:
            nonlocal last
            if time.monotonic() - last >= 4.0:
                d.invoke(refresh, label="header Refresh")
                last = time.monotonic()
            return len(self.controller.state.resources.get("models", [])) > 0

        try:
            d.wait_until(projected, timeout=self.config.startup_wait, description=description)
        except JourneyTimeout as exc:
            raise JourneyHold(f"no usable image model after resource refresh ({exc})") from exc
        d.pump(1.0)

    def shutdown_app(self) -> None:
        """Close through the application's own exit path and prove nothing leaked."""

        ph = f"shutdown_{self.boots}"
        d, root = self.driver, self.root
        if root is None:
            return
        try:
            self.submissions.uninstall()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.checkpoint(f"before_shutdown_{self.boots}")
            assert self.faults is not None
            # A person does not close the window while a background scan is still running: let started work finish
            # (pumping Tk, because those workers hand results back to the GUI thread) before the exit path is used.
            settle_until = time.monotonic() + 20
            while (
                leaked_non_daemon_threads(self._baseline_threads)
                and time.monotonic() < settle_until
            ):
                d.pump(0.1)
            self.faults.begin_shutdown()
            close_started = time.monotonic()
            d.close_via_window_manager()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    root.update()
                    root.winfo_exists()
                except tk.TclError:
                    break
                time.sleep(0.02)
            else:
                self.check(ph, "graceful_close", False, "Tk root still alive 20s after close")
            self.ev.observe(
                f"shutdown_latency_s_{self.boots}", round(time.monotonic() - close_started, 3)
            )
        except tk.TclError:
            pass
        leaked = leaked_non_daemon_threads(self._baseline_threads)
        deadline = time.monotonic() + 10
        while leaked and time.monotonic() < deadline:
            time.sleep(0.1)
            leaked = leaked_non_daemon_threads(self._baseline_threads)
        self.check(ph, "no_leaked_threads", not leaked, f"non-daemon threads still alive: {leaked}")
        if self.faults is not None:
            self.faults.__exit__(None, None, None)
            self.ev.shutdown_noise.extend(self.faults.shutdown_noise)
            self.ev.gui_errors.extend(self.faults.tk_errors)
            self.ev.thread_errors.extend([*self.faults.thread_errors, *self.faults.main_errors])
            self.ev.log_errors.extend(self.faults.error_logs())
        if self.responder is not None:
            self.ev.observations.append(
                {
                    "name": f"native_dialogs_{self.boots}",
                    "value": self.responder.seen,
                    "source": "observed",
                }
            )
            self.responder.__exit__(None, None, None)
            self.responder = None
        self.ev.action_trace.extend(self.trace.entries)
        if self._seam_cm is not None:
            self._seam_cm.__exit__(None, None, None)
            self._seam_cm = None
            self.ev.observations.append(
                {
                    "name": f"scripted_dialogs_{self.boots}",
                    "source": "observed",
                    "value": [(r.kind, r.title, r.message[:120]) for r in self.seam.history],
                }
            )
        self.root = None


def run_journey_body(
    journey_id: str,
    body: Any,
    config: RunConfig,
    *,
    mode_label: str,
    fake_a1111_factory: Any = None,
    fake_comfy_factory: Any = None,
    workspace_hook: Any = None,
    base_url: str | None = None,
    settings_extra: dict[str, Any] | None = None,
    execution_mode: str = "simulated",
) -> JourneyEvidence:
    """Create the evidence + isolated workspace + backends, run ``body(run)``, and always clean up what it owns."""

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path(config.evidence_dir) / f"{stamp}_{journey_id}_{mode_label}"
    ev = JourneyEvidence(journey_id=journey_id, backend_mode=mode_label)
    ev.execution_mode, ev.desktop_driver = execution_mode, config.driver
    ev.repository_sha = repo_sha()
    ev.started_at = ev.now()
    ev.summary["evidence_dir"] = str(run_dir)
    guard = UserDataGuard()
    guard.capture()
    owned = OwnedResources()
    run: GoldenRun | None = None
    try:
        fake_a, fake_c = None, None
        if fake_a1111_factory is not None:
            fake_a = fake_a1111_factory()
            fake_a.start()
            owned.register("fake-a1111", fake_a.stop)
        if fake_comfy_factory is not None:
            fake_c = fake_comfy_factory()
            fake_c.start()
            owned.register("fake-comfy", fake_c.stop)
        url = fake_a.base_url if fake_a is not None else (base_url or "http://127.0.0.1:9")
        workspace = OperatorWorkspace(
            root=Path(tempfile.mkdtemp(prefix="gpj_")),
            webui_base_url=url,
            startup_grace_sec=0.0 if execution_mode == "simulated" else None,
            settings_extra=dict(settings_extra or {}),
        )
        ev.summary["workspace"] = str(workspace.root)
        ev.summary["desktop_driver"] = config.driver
        ev.summary["layout"] = config.layout if config.driver == "windows" else None
        spy = AccessSpy(allowed=(workspace.root,))
        with workspace.activate(), spy:
            if workspace_hook is not None:
                workspace_hook(workspace, fake_a, fake_c)
            run = GoldenRun(journey_id, config, ev, workspace, fake_a1111=fake_a, fake_comfy=fake_c)
            try:
                body(run)
            except (JourneyAbort, JourneyTimeout, WidgetNotFound) as exc:
                ev.abort_reason = f"{type(exc).__name__}: {exc}"
            except JourneyHold as exc:
                ev.hold_reason = str(exc)
            except JourneyNoGo as exc:
                ev.no_go_reason = str(exc)
            except Exception as exc:  # noqa: BLE001 - unexpected harness or product failure
                ev.abort_reason = f"unexpected {type(exc).__name__}: {exc}"
            finally:
                if os.environ.get("OPERATOR_JOURNEY_ECHO") and (
                    ev.abort_reason or ev.hold_reason or ev.no_go_reason
                ):
                    print(
                        f"[journey stopped] {ev.abort_reason or ev.hold_reason or ev.no_go_reason}",
                        file=sys.stderr,
                        flush=True,
                    )
                if run.root is not None:
                    if ev.abort_reason or ev.hold_reason or ev.no_go_reason:
                        try:  # what the application itself said, for diagnosis without a screen
                            ev.observe(
                                "operator_log_tail",
                                [str(x)[:300] for x in list(run.app_state.operator_log)[-40:]],
                            )
                            ev.observe(
                                "captured_log_tail",
                                [
                                    f"{r['level']} {r['logger']}: {r['message'][:200]}"
                                    for r in run.faults.logs[-25:]
                                ]
                                if run.faults is not None
                                else [],
                            )
                        except Exception:  # noqa: BLE001 - diagnostics are evidence, never a new failure
                            pass
                        try:
                            run.snap("failure")  # what the operator saw when the journey stopped
                        except Exception:  # noqa: BLE001 - the screenshot is evidence, never a new failure
                            pass
                    try:
                        run.shutdown_app()
                    except Exception as exc:  # noqa: BLE001
                        ev.abort_reason = ev.abort_reason or f"shutdown failed: {exc}"
        ev.isolation_violations.extend(spy.violations())
        archive_workspace(workspace, ev, run_dir, discard=config.discard_workspace)
        # Produced media is copied (hash-verified) before the workspace is released, so the proof outlives it.
        from tools.operator_journey.golden.provenance import retain_media

        retained = retain_media(ev.observations, run_dir)
        if retained:
            ev.observe("retained_media", retained)
    except Exception as exc:  # noqa: BLE001
        ev.abort_reason = ev.abort_reason or f"harness error {type(exc).__name__}: {exc}"
    finally:
        owned.cleanup()
        ev.isolation_violations.extend(guard.violations())
        ev.completed_at = ev.now()
        ev.write(run_dir)
    return ev


def file_identity(path: Path) -> dict[str, Any]:
    path = Path(path)
    return (
        {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}
        if path.is_file()
        else {"path": str(path), "missing": True}
    )
