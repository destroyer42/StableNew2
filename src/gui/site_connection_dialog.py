"""Native consent and frozen Preview attachment for the StableNew operator Site."""

from __future__ import annotations

import logging
import secrets
import time
import tkinter as tk
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from src.app.site_pack_catalog import PreparePack, SitePackCatalog, pack_digest
from src.app.site_pairing_protocol import PairingTickets, register_protocol
from src.app.site_phone_admission import PhoneQueueAdmission
from src.app.site_phone_connector import SitePhoneConnector
from src.app.site_phone_eval import PhoneEvalReports
from src.app.site_phone_followup import PhoneFollowup
from src.app.site_phone_preview_host import PhonePreviewHost
from src.app.site_phone_queue import PhoneQueueView
from src.app.site_phone_video import PhoneVideo
from src.app.site_queue_bridge import (
    PreviewJob,
    PreviewView,
    SiteListener,
    SiteSession,
    SubmissionReceipt,
)
from src.config.app_config import output_dir_default
from src.contracts import PackJobEntry
from src.controller.app_controller_services.pack_draft_service import SitePackDraft
from src.controller.app_controller_services.run_submission_service import (
    PreviewWitness,
    same_preview,
)
from src.gui.site_phone_dialog import PhoneReviewDialog
from src.learning.learning_paths import get_learning_records_path
from src.pipeline.job_models_v2 import UnifiedJobSummary, WorkloadKind
from src.review.review_lineage import repository_of, verified_review_outputs
from src.state.output_routing import get_output_root

log = logging.getLogger(__name__)
_MAX_PREVIEW_JOBS = 250
_RECEIPT_SECONDS = 20


class PreviewQueueConnection:
    """All methods run on the existing UI thread. The listener never touches the GUI or queue."""

    def __init__(
        self, app: Any, session: SiteSession, confirm: Any, confirm_prepare: Any = None
    ) -> None:
        self.app = app
        self.session = session
        self.confirm = confirm
        self.confirm_prepare = confirm_prepare
        self.witness: PreviewWitness | None = None
        self.preview_id: str | None = None
        self.pending: tuple[SubmissionReceipt, tuple[str, ...], float] | None = None
        self.uncertain: PreviewWitness | None = None
        self.prepared: PreparePack | None = None
        self.prepared_entries: tuple[PackJobEntry, ...] = ()

    def _owns_draft(self) -> bool:
        draft = self.app.app_state.job_draft
        return (
            bool(self.prepared_entries)
            and not draft.parts
            and draft.history_variation is None
            and (
                len(self.prepared_entries) == len(draft.packs)
                and all(a is b for a, b in zip(self.prepared_entries, draft.packs, strict=True))
            )
        )

    def _draft_pack_matches(self, record: Any) -> bool:
        return self.prepared is None or (
            record.prompt_pack_id == self.prepared.pack.name
            and record.prompt_pack_row_index in self.prepared.slots
        )

    def _preview_job(self, record: Any) -> PreviewJob:
        settings = None
        if self.prepared is not None:
            summary = UnifiedJobSummary.from_normalized_record(record)
            effective = record.config
            txt2img = effective.get("txt2img", {})
            settings = {
                "pack": summary.prompt_pack_name,
                "slot": summary.prompt_pack_row_index + 1,
                "model": summary.base_model,
                "sampler": summary.sampler_name,
                "width": summary.width,
                "height": summary.height,
                "steps": summary.steps,
                "cfg": summary.cfg_scale,
                "seed": record.seed,
                "vae": txt2img.get("vae", effective.get("vae")),
                "scheduler": txt2img.get("scheduler", effective.get("scheduler")),
                "subseed": txt2img.get("subseed", effective.get("subseed")),
                "subseed_strength": txt2img.get(
                    "subseed_strength", effective.get("subseed_strength")
                ),
                "loop_count": record.batch_total,
            }
        return PreviewJob(record.job_id, tuple(record.stage_chain_labels), settings)

    def _pack_current(self, command: PreparePack) -> bool:
        if self.session.expired or self.app._is_shutting_down:
            return False
        try:
            return pack_digest(command.pack.path) == command.digest
        except (OSError, ValueError):
            return False

    def _prepare_draft(self, command: PreparePack) -> None:
        app_state = self.app.app_state
        revision, accepted = app_state.snapshot_accepted_preview()
        draft = app_state.job_draft
        owned = self.session.allow_promptpack_queue and self._owns_draft()
        if not owned and (
            accepted or draft.packs or draft.parts or draft.history_variation is not None
        ):
            self.session.finish_preparation(command, "desktop_draft_open")
            return
        if command.overrides and not self.app._build_stage_flags().get("txt2img", True):
            self.session.finish_preparation(command, "txt2img_disabled")
            return
        if not any(
            pack.name == command.pack.name and pack.path.resolve() == command.pack.path
            for pack in self.app.packs
        ) or not self._pack_current(command):
            self.session.finish_preparation(command, "refused")
            return
        if not self.session.allow_promptpack_queue and (
            self.confirm_prepare is None or not self.confirm_prepare(command)
        ):
            self.session.finish_preparation(command, "declined")
            return

        def complete(state: str) -> None:
            if state == "draft_added":
                self.prepared = command
                self.prepared_entries = tuple(app_state.job_draft.packs)
            self.session.finish_preparation(command, state)

        self.app.on_pipeline_add_packs_to_job(
            [command.pack.name],
            selection=SitePackDraft(
                command.slots,
                revision,
                lambda: self._pack_current(command),
                complete,
                self.prepared_entries if owned else (),
                command.overrides,
            ),
        )

    def _publish_current(self) -> None:
        current = self.app.app_state.snapshot_accepted_preview()
        records = current[1]
        if not records:
            reason = (
                "preview_failed"
                if self.prepared is not None and getattr(self.app.app_state, "preview_error", None)
                else "open_an_image_preview"
            )
            self.session.publish(None, reason)
        elif len(records) > _MAX_PREVIEW_JOBS:
            self.session.publish(None, "preview_too_large")
        elif any(record.workload_kind != WorkloadKind.IMAGE for record in records):
            self.session.publish(None, "image_preview_required")
        elif self.prepared is not None and (
            not self._owns_draft()
            or not all(self._draft_pack_matches(record) for record in records)
            or {record.prompt_pack_row_index for record in records} != set(self.prepared.slots)
        ):
            self.session.publish(None, "preview_changed")
        elif self.uncertain is not None and same_preview(self.uncertain, current):
            self.session.publish(None, "check_native_queue")
        else:
            if self.witness is None or not same_preview(self.witness, current):
                self.preview_id = secrets.token_hex(16)
            assert self.preview_id is not None
            self.witness = current
            self.session.publish(
                PreviewView(
                    self.preview_id,
                    tuple(self._preview_job(record) for record in records),
                    self.prepared.request_id if self.prepared else None,
                )
            )
            return
        self.witness = None
        self.preview_id = None

    def _finish(
        self, receipt: SubmissionReceipt, state: str, job_ids: tuple[str, ...] = ()
    ) -> None:
        self.session.finish(receipt, state, job_ids)
        self.pending = None
        self.witness = None
        self.preview_id = None

    def _committed(self, job_ids: tuple[str, ...]) -> tuple[str, ...]:
        repository = self.app.job_service.history_store
        return tuple(job_id for job_id in job_ids if repository.get_job(job_id) is not None)

    def _check_receipt(self) -> None:
        if self.pending is None:
            return
        receipt, job_ids, timeout = self.pending
        try:
            committed = self._committed(job_ids)
        except Exception:  # noqa: BLE001 - job admission might already have committed
            log.exception("Unable to read the native queue receipt")
            self.uncertain = self.witness
            self._finish(receipt, "check_native_queue")
            return
        if committed == job_ids:
            self._finish(receipt, "queued", committed)
            self.prepared = None
            self.prepared_entries = ()
        elif time.monotonic() >= timeout or not self.app._queue_submit_in_progress:
            self.uncertain = self.witness
            self._finish(receipt, "check_native_queue")

    def _consume(self, receipt: SubmissionReceipt) -> None:
        witness = self.witness
        if witness is None or receipt.preview_id != self.preview_id:
            self._finish(receipt, "preview_changed")
            return
        job_ids = tuple(record.job_id for record in witness[1])
        delegated = (
            self.session.allow_promptpack_queue and self.prepared is not None and self._owns_draft()
        )
        if not delegated and not self.confirm(len(job_ids)):
            self._finish(receipt, "declined")
            return
        if self.session.expired or self.app._is_shutting_down:
            self._finish(receipt, "connection_closed")
            return
        if not same_preview(witness, self.app.app_state.snapshot_accepted_preview()):
            self._finish(receipt, "preview_changed")
            return
        if self.prepared is not None and (
            not self._owns_draft() or not self._pack_current(self.prepared)
        ):
            self._finish(receipt, "preview_changed")
            return
        try:
            if self._committed(job_ids):
                self.uncertain = witness
                self._finish(receipt, "check_native_queue")
                return
            if not self.app.submit_frozen_site_preview(witness):
                self._finish(receipt, "native_queue_refused")
                return
        except Exception:  # noqa: BLE001 - never retry uncertain queue admission
            log.exception("Failed to observe the native queue handoff")
            self.uncertain = witness
            self._finish(receipt, "check_native_queue")
            return
        self.session.finish(receipt, "submitting")
        self.pending = (receipt, job_ids, time.monotonic() + _RECEIPT_SECONDS)

    def tick(self) -> None:
        if self.session.expired or self.app._is_shutting_down:
            return
        self._check_receipt()
        if self.pending is not None:
            return
        preparation = self.session.take_preparation()
        if preparation is not None:
            self._prepare_draft(preparation)
            return
        self._publish_current()
        receipt = self.session.take_request()
        if receipt is not None:
            self._consume(receipt)


class SiteConnectionDialog:
    def __init__(self, root: tk.Tk, app: Any) -> None:
        self.root = root
        self.app = app
        self.dialog: tk.Toplevel | None = None
        self.listener: SiteListener | None = None
        self.connection: PreviewQueueConnection | None = None
        self._timer: str | None = None
        self._checkout = Path(__file__).resolve().parents[2]
        self._tickets = PairingTickets(self._checkout)
        self._shared_output: Path | None = None
        self._omit_output = False
        self._startup_error = ""
        repository = repository_of(app)
        self._review_outputs = partial(verified_review_outputs, repository) if repository else None
        records = get_learning_records_path(create_parent=False)
        admission = None
        if repository is not None:
            host = PhonePreviewHost(app, repository, records)
            video = PhoneVideo(app.job_service)
            admission = PhoneQueueAdmission(
                PhoneQueueView(repository, app.job_service),
                app.job_service,
                packs=host.packs,
                compile_pack=host.compile_pack,
                compile_rework=host.compile_rework,
                video=video,
                followup=PhoneFollowup(repository, video),
            )
        runner = getattr(getattr(app, "job_service", None), "runner", None)

        def preview_idle() -> bool:
            return not getattr(runner, "current_job_id", None)

        self._preview_idle = preview_idle
        self._phone = SitePhoneConnector(
            review_outputs=self._review_outputs,
            review_records=records,
            phone_queue=admission,
            phone_eval=PhoneEvalReports(repository) if repository is not None else None,
            preview_idle=self._preview_idle,
        )
        self._phone_dialog = PhoneReviewDialog(root, self._phone)

    def start_default(self) -> None:
        """Enable pairing when the Windows app starts, with the existing output and pack scopes."""
        self._phone.start()
        try:
            register_protocol(self._checkout)
        except OSError:
            log.warning("Could not register the StableNew Operator link")
        self._start()

    def _output_root(self) -> Path:
        config = getattr(self.app, "_config_manager", None)
        settings = config.load_settings() if config is not None else {}
        configured = settings.get("output_dir") if isinstance(settings, dict) else None
        if not isinstance(configured, str):
            configured = None
        return (
            get_output_root(
                configured or getattr(self.app, "output_dir", None) or output_dir_default(),
                create=False,
            )
            .expanduser()
            .absolute()
        )

    def _start(self) -> None:
        if self.connection is not None or self.app._is_shutting_down:
            return
        session = SiteSession(
            self.app.job_service.history_store.get_job,
            allow_promptpack_queue=True,
            claim_ticket=self._tickets.consume,
            review_outputs=self._review_outputs,
            preview_idle=self._preview_idle,
        )
        if not self._omit_output:
            try:
                session.set_output_folder(self._shared_output or self._output_root())
            except (OSError, ValueError):
                log.warning("The configured Output folder is unavailable for the Operator Site")
        self._share_packs(session)
        try:
            self.listener = SiteListener(session)
        except OSError:
            session.revoke()
            self._startup_error = "StableNew could not open its local Site port. Close another connection using the port and try again."
            log.warning(self._startup_error)
            return
        self._startup_error = ""
        self.connection = PreviewQueueConnection(
            self.app, session, self._confirm, self._confirm_prepare
        )
        self._tick()

    def open(self) -> None:
        if self.dialog is not None:
            self.dialog.lift()
            return
        self._start()
        if self.connection is None:
            messagebox.showerror(
                "StableNew Site connection",
                self._startup_error or "StableNew is shutting down.",
                parent=self.root,
            )
            if not self.app._is_shutting_down:
                self._phone_dialog.open()
            return
        session = self.connection.session

        self.dialog = dialog = tk.Toplevel(self.root)
        dialog.title("StableNew Site connection")
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.bind("<Destroy>", self._destroyed, add="+")
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text="Pair the private StableNew Site", font=("TkDefaultFont", 12, "bold")
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Choose Connect on the private Site, or enter this code manually within 15 minutes. Authenticated activity keeps an eight-hour desktop inactivity lease alive.",
            wraplength=370,
        ).pack(anchor="w", pady=(5, 12))
        self._lease_status = ttk.Label(frame, text="Desktop · Waiting for pairing", wraplength=370)
        self._lease_status.pack(anchor="w")
        ttk.Button(frame, text="Reconnect", command=self._reconnect).pack(anchor="w")
        ttk.Label(
            frame,
            text="The paired Site can read visible PromptPacks, build Previews and submit its own Preview to the queue. Choose Disconnect to stop sharing.",
            wraplength=370,
        ).pack(anchor="w", pady=(4, 8))
        output_root = self._output_root()
        output_text = (
            f"Shared for this session\n{self._shared_output or output_root}"
            if session.output_catalog
            else "Output folder is private or unavailable."
        )
        output_status = ttk.Label(frame, text=output_text, wraplength=370)
        output_status.pack(anchor="w")
        share_configured = tk.BooleanVar(
            master=dialog, value=session.output_catalog is not None and self._shared_output is None
        )

        def share_default() -> None:
            if share_configured.get():
                if not self._grant_output(session, output_root, output_status):
                    share_configured.set(False)
                else:
                    self._shared_output = None
                    self._omit_output = False
            else:
                self._stop_sharing_output(session, output_status)

        def stop_output() -> None:
            share_configured.set(False)
            self._stop_sharing_output(session, output_status)

        ttk.Checkbutton(
            frame,
            text="Share configured Output with this pairing",
            variable=share_configured,
            command=share_default,
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="Allows the private Site to view output media and metadata and save ratings and albums on this PC.",
            wraplength=370,
        ).pack(anchor="w")
        output_controls = ttk.Frame(frame)
        output_controls.pack(anchor="w", pady=(3, 10))
        ttk.Button(
            output_controls,
            text="Change output folder…",
            command=lambda: self._share_output(
                session, dialog, output_status, share_configured, output_root
            ),
        ).pack(side="left")
        ttk.Button(
            output_controls,
            text="Stop sharing output",
            command=stop_output,
        ).pack(side="left", padx=(6, 0))
        code = ttk.Entry(frame, width=48)
        code.insert(0, session.code)
        code.configure(state="readonly")
        code.pack(fill="x")
        ttk.Button(frame, text="Copy pairing code", command=lambda: self._copy(session.code)).pack(
            anchor="w", pady=6
        )
        pack_text = (
            "Visible PromptPacks are shared."
            if session.pack_catalog is not None
            else "PromptPacks are unavailable."
        )
        pack_status = ttk.Label(frame, text=pack_text, wraplength=370)
        pack_status.pack(anchor="w")
        ttk.Button(
            frame,
            text="Refresh shared PromptPacks",
            command=lambda: self._share_packs(session, pack_status),
        ).pack(anchor="w", pady=(3, 10))
        ttk.Button(frame, text="Disconnect", command=self.close).pack(anchor="e")
        ttk.Button(frame, text="Phone review…", command=self._phone_dialog.open).pack(anchor="w")

    def _copy(self, code: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(code)

    def _reconnect(self) -> None:
        self.close()
        self.open()

    def _share_packs(self, session: SiteSession, status: ttk.Label | None = None) -> None:
        if session.expired:
            return
        try:
            session.share_packs(
                SitePackCatalog(
                    self.app._packs_dir,
                    list(self.app.packs),
                    self.app._config_manager.load_pack_config,
                    self.app.app_state.resources,
                )
            )
        except (OSError, ValueError):
            if status is not None:
                status.configure(text="The visible PromptPacks could not be shared.")
            return
        if status is not None:
            status.configure(
                text="Visible PromptPacks and slot prompts are shared for this session."
            )

    def _confirm_prepare(self, command: PreparePack) -> bool:
        dialog = self.dialog
        if dialog is None:
            return False
        return messagebox.askyesno(
            "Prepare PromptPack from the Operator Site?",
            f"Use the current StableNew pipeline settings to preview {len(command.slots)} selected slot(s) "
            f"from {command.pack.name}? This will fill the empty desktop draft and build a Preview.",
            parent=dialog,
            default=messagebox.NO,
        )

    def _share_output(
        self,
        session: SiteSession,
        dialog: tk.Toplevel,
        status: ttk.Label,
        share_configured: tk.BooleanVar,
        output_root: Path,
    ) -> None:
        folder = filedialog.askdirectory(
            parent=dialog,
            title="Choose the StableNew output folder to share for this session",
            initialdir=str(output_root),
            mustexist=True,
        )
        if not folder or session.expired or dialog is not self.dialog:
            return
        if self._grant_output(session, Path(folder), status):
            selected = Path(folder).absolute()
            self._shared_output = selected if selected != output_root else None
            self._omit_output = False
            share_configured.set(self._shared_output is None)

    @staticmethod
    def _grant_output(session: SiteSession, folder: Path, status: ttk.Label) -> bool:
        try:
            folder = folder.resolve(strict=True)
            session.set_output_folder(folder)
        except (OSError, ValueError):
            status.configure(text="The selected output folder could not be opened.")
            return False
        status.configure(text=f"Shared for this session\n{folder}")
        return True

    def _stop_sharing_output(self, session: SiteSession, status: ttk.Label) -> None:
        self._omit_output = True
        session.set_output_folder(None)
        status.configure(text="Output folder is private.")

    def _confirm(self, count: int) -> bool:
        dialog = self.dialog or self.root
        return messagebox.askyesno(
            "Queue image Preview from the StableNew Site?",
            f"Add the {count} currently previewed image job(s) to the existing StableNew queue? "
            "The normal queue dispatch policy applies.",
            parent=dialog,
            default=messagebox.NO,
        )

    def _tick(self) -> None:
        self._timer = None
        connection = self.connection
        if connection is None:
            return
        if self.app._is_shutting_down:
            self.close()
            return
        if connection.session.expired:
            if self.dialog is not None:
                self._lease_status.configure(text="Desktop · Expired or revoked. Select Reconnect.")
                if self.listener is not None:
                    self.listener.close()
                self.listener = None
                self.connection = None
            else:
                self.close()
                self._timer = self.root.after(1500, self._start)
            return
        if self.dialog is not None:
            lease = connection.session.connection_status()
            minutes = (lease["remaining_ms"] + 59999) // 60000
            self._lease_status.configure(
                text=f"Desktop · {lease['state'].capitalize()} · Expires in {minutes} min"
            )
        connection.tick()
        if connection is self.connection:
            self._timer = self.root.after(150, self._tick)

    def _destroyed(self, event: tk.Event[Any]) -> None:
        if event.widget is self.dialog:
            self.dialog = None

    def _disconnect(self, *, cancel_timer: bool = True) -> None:
        self.dialog = None
        self.connection = None
        if self._timer is not None:
            if cancel_timer:
                self.root.after_cancel(self._timer)
            self._timer = None
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def close(self) -> None:
        dialog = self.dialog
        self._disconnect()
        if dialog is not None:
            dialog.destroy()

    def shutdown(self) -> None:
        """Signal the transports and drop UI references without waiting or calling Tk."""
        self._phone.close(timeout=0)
        if self.listener is not None:
            self.listener.begin_shutdown()
        self.dialog = self.connection = self.listener = self._timer = None


def install_site_connection_control(
    root: tk.Tk, app: Any, header: ttk.Frame
) -> SiteConnectionDialog:
    """Add the toolbar controls and return their lifecycle owner."""
    connection = SiteConnectionDialog(root, app)
    button = ttk.Button(
        header, text="Operator Site", style="Secondary.TButton", command=connection.open
    )
    button.grid(row=0, column=header.grid_size()[0], padx=4, pady=4)
    root.after(0, connection.start_default)
    return connection
