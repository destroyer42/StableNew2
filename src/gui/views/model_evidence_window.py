"""Explicit operator catalog journey. Workers return data; only Tk callbacks touch widgets."""

from __future__ import annotations

import copy
import json
import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.assets.checkpoint_structure import checkpoint_variant_from_metadata
from src.assets.evidence_census import refresh_census
from src.assets.registry import AssetKind, AssetRegistry
from src.generation_profiles.evidence_catalog import (
    EvidenceCatalog,
    load_operator_catalog,
    operator_catalog_root,
    select_operator_catalog,
)
from src.generation_profiles.evidence_refresh import EvidenceRefresh, Lookup
from src.generation_profiles.evidence_report import build_report, export_report
from src.generation_profiles.identity import ModelIdentityResolver, RegistryShaLookup
from src.gui.controllers.model_evidence_proposals import (
    capture_resources,
    preview_selected,
    save_drafts,
)
from src.gui.views.model_evidence_proposals_dialog import (
    ModelEvidenceProposalsDialog,
    choose_prompt_context,
)
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import RegistryFamilyLookup
from src.learning.evidence_autopilot import (
    EvidenceProposalPlanner,
    ProposalPlan,
    ProposalPlanningContext,
)
from src.learning.evidence_proposals import (
    ExperimentProposal,
    evidence_gaps,
)
from src.learning.qualification_batch import BatchOutcome
from src.learning.setting_evidence import inspect_experiment
from src.utils.atomic_io import atomic_write_text
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)


class ModelEvidenceWindow(tk.Toplevel):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner)
        self.owner = owner
        self.title("Model Evidence Catalog — research and qualification drafts")
        self.geometry(
            f"{min(1120, self.winfo_screenwidth() - 24)}x{min(700, self.winfo_screenheight() - 96)}"
        )
        self.registry = AssetRegistry()
        catalog_error = ""
        try:
            self.catalog = load_operator_catalog()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            from src.generation_profiles.evidence_baseline import baseline_catalog

            self.catalog = baseline_catalog()
            catalog_error = (
                f"Saved evidence unavailable ({type(exc).__name__}); displaying curated baseline. "
            )
        self.census: dict[str, Any] = {}
        self.targets: list[Any] = []
        self.proposals: list[ExperimentProposal] = []
        self.proposal_plan: ProposalPlan | None = None
        self.planning_context: ProposalPlanningContext | None = None
        self._qualification_prompt: tuple[str, str, dict[str, Any]] | None = None
        self._proposal_dialog: ModelEvidenceProposalsDialog | None = None
        self._rows: dict[str, dict[str, Any]] = {}
        self._events: queue.Queue[tuple[int, str, Any, Any]] = queue.Queue(maxsize=64)
        self._cancel = threading.Event()
        self._busy, self._closed, self._generation = False, False, 0
        self._lookup = EvidenceRefresh()
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        self.evidence_menu = tk.Menu(bar, tearoff=False)
        evidence = ttk.Menubutton(bar, text="Evidence…", menu=self.evidence_menu)
        evidence.pack(side="right")
        for label, command in (
            ("Observe assets", lambda: self._refresh(False)),
            ("Verify identities (bounded)", lambda: self._refresh(True)),
            ("Cancel", self._cancel.set),
            ("Import reviewed catalog", self._import),
            ("Export report", self._export),
            ("Inspect active experiment", self._inspect_active),
            ("Look up verified Civitai hash…", self._research),
            ("Look up exact Hugging Face revision…", self._hf_dialog),
            ("All cached/observed asset details", lambda: self._show(self.census)),
        ):
            self.evidence_menu.add_command(label=label, command=command)
        ttk.Button(bar, text="Experiment Library", command=owner._on_open_experiment_library).pack(
            side="left"
        )
        ttk.Label(
            self,
            text="No startup research or generation. Observation is provisional; only fingerprint-verified hashes identify bytes.",
            padding=6,
        ).pack(anchor="w")
        self.status = tk.StringVar(
            value=catalog_error
            + "Select a cached checkpoint. Missing identities can be verified through Evidence…. No scan has started."
        )
        ttk.Label(self, textvariable=self.status, wraplength=1050, padding=6).pack(fill="x")
        self.filter = tk.StringVar()
        ttk.Entry(self, textvariable=self.filter).pack(fill="x", padx=6)
        self.filter.trace_add("write", lambda *_: self._render_assets())
        self.tree = ttk.Treeview(
            self, columns=("identity", "family", "coverage", "qualification"), height=12
        )
        self.tree.heading("#0", text="Checkpoint (search above)")
        self.tree.column("#0", width=460)
        for key in ("identity", "family", "coverage", "qualification"):
            self.tree.heading(key, text=key)
            self.tree.column(key, width=100)
        self.tree.pack(fill="both", expand=True, padx=6)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selected_model_changed())
        actions = ttk.Frame(self, padding=6)
        actions.pack(fill="x")
        self.proposed_button = ttk.Button(
            actions,
            text="Proposed Experiments (select a model)",
            command=self._plan,
            state="disabled",
        )
        self.proposed_button.pack(side="left")
        ttk.Button(actions, text="Evidence Details", command=self._inspect_asset).pack(
            side="left", padx=4
        )
        self.repo, self.revision = tk.StringVar(), tk.StringVar()
        self._details_host = ttk.Frame(self)
        self.details = ScrolledText(self._details_host, height=12, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._poll_id = self.after(75, self._poll)
        self._load_cached_assets()

    def _close(self) -> None:
        self._closed = True
        self._cancel.set()
        self.after_cancel(self._poll_id)
        self.destroy()

    def _on_destroy(self, event: Any) -> None:
        if event.widget is self:
            self._closed = True
            self._cancel.set()

    def _show(self, data: Any) -> None:
        self._details_host.pack(fill="both", expand=True, padx=6, pady=6)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert(
            "1.0", data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        )
        self.details.configure(state="disabled")

    def _work(
        self,
        action: Callable[[Callable[[], bool], Callable[[str], None]], Any],
        success: Callable[[Any], None],
    ) -> None:
        if self._busy:
            self.status.set("A bounded operation is running; Cancel then wait for its result.")
            return
        self._busy = True
        if self._proposal_dialog is not None and self._proposal_dialog.winfo_exists():
            self._proposal_dialog.set_busy(True)
        self._cancel = threading.Event()
        self._generation += 1
        generation, cancel = self._generation, self._cancel

        def progress(message: str) -> None:
            try:
                self._events.put_nowait((generation, "progress", message, None))
            except queue.Full:
                pass

        def run() -> None:
            event: tuple[int, str, Any, Any]
            try:
                result = action(cancel.is_set, progress)
                event = (
                    generation,
                    "cancelled"
                    if cancel.is_set() and not isinstance(result, BatchOutcome)
                    else "done",
                    result,
                    success,
                )
            except Exception as exc:
                logger.exception("Model evidence operation failed")
                event = (generation, "error", f"{type(exc).__name__}: {exc}", None)
            # A closing view must not strand a worker on a full result queue.
            while not self._closed:
                try:
                    self._events.put(event, timeout=0.1)
                    break
                except queue.Full:
                    continue

        get_thread_registry().spawn(
            target=run, name="model-evidence", purpose="bounded operator evidence lookup"
        )

    def _poll(self) -> None:
        for _ in range(64):
            try:
                generation, kind, value, callback = self._events.get_nowait()
            except queue.Empty:
                break
            if generation != self._generation or self._closed:
                continue
            if kind == "progress":
                self.status.set(value)
            else:
                self._busy = False
                if self._proposal_dialog is not None and self._proposal_dialog.winfo_exists():
                    self._proposal_dialog.set_busy(False)
                if kind == "error":
                    self.status.set(value)
                    if self._proposal_dialog is not None and self._proposal_dialog.winfo_exists():
                        self._proposal_dialog.status.set(value)
                    if (
                        "stale" in str(value).casefold()
                        and self._proposal_dialog is not None
                        and self._proposal_dialog.winfo_exists()
                    ):
                        self._proposal_dialog.refuse_stale()
                elif kind == "cancelled":
                    self.status.set(
                        "Operation cancelled. Saved drafts and any confirmed admissions remain in the Experiment Library; inspect exact jobs before retrying."
                    )
                else:
                    callback(value)
        self._poll_id = self.after(75, self._poll)

    def _refresh(self, verify: bool) -> None:
        def finished(result: Any) -> None:
            census, self.targets = result
            self.census = census
            self.status.set(
                f"{'Complete' if census['complete'] else 'Partial'}: {len(census['assets'])} files, {census['verified']} verified; {census['unchanged']} unchanged; {len(census['errors'])} errors."
            )
            self._render_assets()

        def scan(cancelled: Callable[[], bool], progress: Callable[[str], None]) -> Any:
            census = refresh_census(
                self.registry, verify=verify, cancelled=cancelled, progress=progress
            )
            resolver = self._resolver()
            targets = [
                resolver.resolve(Path(row["relative"]).name)
                for row in census["assets"]
                if row["kind"] == "checkpoint"
            ]
            return census, targets

        self._work(scan, finished)

    def _render_assets(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.filter.get().casefold()
        self._rows = {}
        for i, row in enumerate(self.census.get("assets", [])):
            if row["kind"] != "checkpoint":
                continue
            if query not in (row["relative"] + " " + row["kind"] + " " + row["family"]).casefold():
                continue
            key = str(i)
            self._rows[key] = row
            self.tree.insert(
                "",
                "end",
                iid=key,
                text=row["relative"],
                values=(row["identity_status"], row["family"], "Check selection", "Not planned"),
            )
        if selected and selected[0] in self._rows:
            self.tree.selection_set(selected)

    def _selected(self) -> dict[str, Any] | None:
        selection = self.tree.selection()
        return self._rows.get(selection[0]) if selection else None

    def _resolver(self) -> ModelIdentityResolver:
        return ModelIdentityResolver(
            family_lookup=RegistryFamilyLookup(self.registry),
            sha_lookup=RegistryShaLookup(self.registry),
        )

    def _inspect_asset(self) -> None:
        row = self._selected()
        if not row:
            return

        def inspect(
            _cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> dict[str, Any]:
            target = self._resolver().resolve(Path(row["relative"]).name)
            return {
                "asset": row,
                "identity": target.identity.to_dict(),
                "policy": target.policy.policy_id,
                "coverage": [
                    {
                        "field": c.field,
                        "status": c.status,
                        "claims": [vars(claim) for claim in c.claims],
                        "reason": c.reason,
                    }
                    for c in self.catalog.coverage(
                        target.identity,
                        asset_kind=row["kind"],
                        variant=target.identity.key
                        if target.policy.qualified
                        else "sdxl_turbo"
                        if row["header"].get("checkpoint_variant") == "turbo"
                        else "",
                    )
                ],
                "gaps": [
                    vars(g)
                    for g in evidence_gaps(
                        self.catalog, target, variant=row["header"].get("checkpoint_variant") or ""
                    )
                ],
            }

        self._work(inspect, self._show)

    def _load_cached_assets(self) -> None:
        rows = []
        for record in self.registry.cached_snapshot().records_for(AssetKind.CHECKPOINT):
            for location in record.locations:
                if location.kind != AssetKind.CHECKPOINT:
                    continue
                try:
                    relative = location.path.relative_to(location.root).as_posix()
                except ValueError:
                    continue
                family = (
                    record.compatibility.family.value
                    if record.compatibility and record.compatibility.family
                    else "unknown"
                )
                rows.append(
                    {
                        "kind": "checkpoint",
                        "relative": relative,
                        "family": family,
                        "identity_status": "Cached; check selection",
                        "size": location.byte_size,
                        "sha256": record.sha256,
                        "header": {
                            "checkpoint_variant": checkpoint_variant_from_metadata(
                                record.embedded_metadata
                            )
                        },
                    }
                )
        self.census = {"assets": rows, "complete": False, "errors": []}
        self._render_assets()

    def _selected_model_changed(self) -> None:
        self._cancel.set()
        self._generation += 1
        self._busy = False
        self.proposal_plan = self.planning_context = None
        self.proposals = []
        if self._proposal_dialog is not None and self._proposal_dialog.winfo_exists():
            self._proposal_dialog.refuse_stale()
        self.proposed_button.configure(text="Proposed Experiments (checking…)", state="disabled")
        if self._selected() and getattr(self.owner, "learning_controller", None) is not None:
            self._plan(open_dialog=False)

    def _capture_planning_inputs(self) -> tuple[Any, ...]:
        row = self._selected()
        if not row or row["kind"] != "checkpoint":
            raise ValueError("Select a checkpoint first.")
        controller = self.owner.learning_controller
        baseline = copy.deepcopy(
            controller.authoring_baseline() or controller._get_baseline_config()
        )
        getter = getattr(controller.app_controller, "get_current_global_prompt_policy", None)
        policy = getter() if callable(getter) else None
        if isinstance(policy, dict):
            from src.pipeline.global_prompt_policy import apply_global_prompt_policy

            baseline = apply_global_prompt_policy(baseline, **policy)
        return (
            copy.deepcopy(row),
            baseline,
            capture_resources(controller),
            self.catalog,
            self._resolver(),
        )

    @staticmethod
    def _context(inputs: tuple[Any, ...]) -> ProposalPlanningContext:
        row, baseline, resources, catalog, resolver = inputs
        if load_operator_catalog().revision != catalog.revision:
            raise ValueError("Evidence catalog changed; reopen the window to revalidate findings.")
        target = resolver.resolve(Path(row["relative"]).name)
        baseline = copy.deepcopy(baseline)
        baseline["backend_options"] = normalize_image_backend_options(
            baseline.get("backend_options"), model_name=target.identity.display_name
        )
        return ProposalPlanningContext(
            target,
            catalog,
            baseline,
            resources,
            variant=(row.get("header") or {}).get("checkpoint_variant") or "",
        )

    def _plan(self, *, open_dialog: bool = True) -> None:
        row = self._selected()
        if not row or row["kind"] != "checkpoint":
            self.status.set("Select a checkpoint first. Accessories receive usage metadata.")
            return
        inputs = self._capture_planning_inputs()

        def planned(
            _cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> tuple[ProposalPlanningContext, ProposalPlan]:
            context = self._context(inputs)
            return context, EvidenceProposalPlanner().plan(context)

        def show(result: Any) -> None:
            self.planning_context, self.proposal_plan = result
            target = self.planning_context.target
            self.proposals = list(self.proposal_plan.proposals)
            if not any(t.identity == target.identity for t in self.targets):
                self.targets.append(target)
            count = sum(p.runnable for p in self.proposals)
            self.proposed_button.configure(text=f"Proposed Experiments ({count})", state="normal")
            covered = sum(
                c.field
                in ("sampler_name", "scheduler", "steps", "cfg_scale", "width", "height", "vae")
                and c.status == "recommended"
                for c in self.catalog.coverage(target.identity)
            )
            selected = self.tree.selection()
            if selected:
                current_row = self._selected()
                if current_row is not None and target.identity.sha256:
                    current_row.update(identity_status="verified", sha256=target.identity.sha256)
                self.tree.item(
                    selected[0],
                    values=(
                        "Verified" if target.identity.sha256 else "Unavailable",
                        target.identity.family,
                        f"{covered}/7",
                        f"{count} eligible",
                    ),
                )
            self.status.set(
                f"{count} eligible experiments; remaining rows explain blockers or metadata. No prompt, network lookup or generation was used."
            )
            if open_dialog:
                self._proposal_dialog = ModelEvidenceProposalsDialog(self, self.proposal_plan)

        self._work(planned, show)

    def _save_selected(
        self, dialog: ModelEvidenceProposalsDialog, *, queue_to_learning: bool
    ) -> None:
        inputs, ids, accepted = self._capture_planning_inputs(), dialog.selection_ids(), dialog.plan
        prompt_context = copy.deepcopy(self._qualification_prompt)

        def saved(identities: Any) -> None:
            self.status.set(
                f"Saved/preserved {len(identities)} Experiment Library drafts. No jobs admitted."
            )
            if dialog.winfo_exists():
                dialog.status.set(self.status.get())
            if queue_to_learning:
                self.owner._on_open_experiment_library()

        self._work(
            lambda cancelled, _p: save_drafts(
                accepted,
                ids,
                self._context(inputs),
                self.owner.experiment_store,
                cancelled=cancelled,
                prompt_context=prompt_context,
            ),
            saved,
        )

    def _choose_qualification_prompt(self, *, change: bool = False) -> Any:
        if self._qualification_prompt is not None and not change:
            return self._qualification_prompt
        panel = getattr(self.owner, "experiment_panel", None)
        selected = panel._get_selected_prompt_payload() if panel is not None else None
        if selected and not change:
            metadata = {
                "prompt_source": "pack",
                "selected_prompt_pack_path": selected.get("prompt_pack_path", ""),
                "selected_prompt_pack_name": selected.get("prompt_pack_name", ""),
                "selected_prompt_index": selected.get("prompt_index", 0),
                "selected_prompt_label": selected.get("label", ""),
            }
            self._qualification_prompt = (
                str(selected.get("prompt_text", "")),
                str(selected.get("negative_prompt_text", "")),
                metadata,
            )
        else:
            experiment = self.owner.learning_controller.learning_state.current_experiment
            prompt = getattr(experiment, "prompt_text", "") if not change else ""
            negative = str(
                (getattr(experiment, "metadata", {}) or {}).get("selected_prompt_negative_text", "")
            )
            if not prompt or change:
                self._qualification_prompt = choose_prompt_context(
                    self, selected, (prompt, negative)
                )
            else:
                metadata = getattr(experiment, "metadata", {}) or {}
                source = {
                    k: copy.deepcopy(v)
                    for k, v in metadata.items()
                    if k == "prompt_source" or k.startswith("selected_prompt_")
                }
                self._qualification_prompt = (
                    prompt,
                    negative,
                    source
                    if source.get("prompt_source") == "pack"
                    else {"prompt_source": "custom"},
                )
        return self._qualification_prompt

    def _preview_selected(self, dialog: ModelEvidenceProposalsDialog) -> None:
        if self._busy:
            self.status.set("Wait for the current bounded operation before Preview.")
            return
        prompt = self._choose_qualification_prompt()
        if prompt is None:
            return
        inputs, ids, accepted = self._capture_planning_inputs(), dialog.selection_ids(), dialog.plan
        getter = getattr(
            getattr(self.owner.learning_controller, "app_controller", None),
            "get_current_global_prompt_policy",
            None,
        )
        policy = copy.deepcopy(getter()) if callable(getter) else None

        def shown(previews: Any) -> None:
            if dialog.winfo_exists():
                dialog.show(
                    "\n\n".join(
                        f"{state.current_experiment.name}\n{summary.headline}\n"
                        + "\n".join(f"{k}: {v}" for k, v in summary.rows)
                        for state, _records, summary in previews
                    )
                )
                dialog.status.set(
                    f"{len(previews)} canonical Learning Previews compiled; no drafts, jobs, ratings or profiles written."
                )

        self._work(
            lambda cancelled, _p: preview_selected(
                accepted,
                ids,
                self._context(inputs),
                prompt=prompt[0],
                negative=prompt[1],
                prompt_metadata=prompt[2],
                global_policy=policy,
                cancelled=cancelled,
            ),
            shown,
        )

    def _queue_selected(self, dialog: ModelEvidenceProposalsDialog) -> None:
        if self._busy or dialog._stale:
            return
        service = getattr(self.owner, "qualification_batch", None)
        if service is None:
            dialog.status.set("Canonical Learning/JobService admission is unavailable.")
            return
        inputs, ids, plan = self._capture_planning_inputs(), dialog.selection_ids(), dialog.plan

        def prepared(batch: Any) -> None:
            if not dialog.winfo_exists() or dialog._stale:
                return
            dialog.show(batch.confirmation)
            if not any(entry.records for entry in batch.experiments):
                dialog.status.set(
                    "Every selected experiment already has jobs. Open Experiment Library to review; reruns require a new experiment."
                )
                return
            generation = self._generation
            if not messagebox.askyesno(
                "Queue qualification batch", batch.confirmation, parent=dialog
            ):
                dialog.status.set(
                    "Generation not confirmed. Drafts remain saved; zero jobs admitted."
                )
                return
            if (
                self._closed
                or generation != self._generation
                or not dialog.winfo_exists()
                or dialog._stale
            ):
                return
            fresh_inputs = self._capture_planning_inputs()

            def admitted(outcome: Any) -> None:
                self.status.set(outcome.describe())
                if dialog.winfo_exists():
                    dialog.status.set(outcome.describe())
                    dialog.show(outcome.describe())

            self._work(
                lambda cancelled, _p: service.admit(
                    batch, self._context(fresh_inputs), confirmed=True, cancelled=cancelled
                ),
                admitted,
            )

        def context_ready(saved_prompt: Any) -> None:
            if not dialog.winfo_exists() or dialog._stale:
                return
            if saved_prompt is not None:
                self._qualification_prompt = saved_prompt
            prompt_context = self._choose_qualification_prompt()
            if prompt_context is None:
                return
            self._work(
                lambda cancelled, _p: service.prepare(
                    plan, ids, self._context(inputs), prompt_context, cancelled=cancelled
                ),
                prepared,
            )

        self._work(lambda _cancelled, _p: service.saved_prompt_context(ids), context_ready)

    def _open_draft(self, dialog: ModelEvidenceProposalsDialog) -> None:
        selected = dialog.tree.selection()
        if not selected or selected[0] not in dialog.proposals:
            return
        identity = selected[0]

        def loaded(payload: Any) -> None:
            if not payload:
                dialog.status.set("Save the highlighted runnable draft first.")
            elif self.owner._restore_from_store_payload(payload, experiment_id=identity):
                dialog.status.set(
                    "Opened in Learning Design. Choose prompt context, Build Preview, then explicitly Run there."
                )

        self._work(lambda _c, _p: self.owner.experiment_store.load_session(identity), loaded)

    def _hf_dialog(self) -> None:
        window = tk.Toplevel(self)
        window.title("Explicit evidence refresh — exact Hugging Face revision")
        for row, (label, variable) in enumerate(
            (("Repository", self.repo), ("40-character commit", self.revision))
        ):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=6, pady=6)
            ttk.Entry(window, textvariable=variable, width=50).grid(
                row=row, column=1, padx=6, pady=6
            )
        ttk.Button(window, text="Review disclosure and look up…", command=self._research_hf).grid(
            row=2, column=0, columnspan=2, pady=6
        )

    def _lookup_source(self, lookup: Lookup) -> None:
        if not messagebox.askyesno(
            "External identifier disclosure", lookup.disclosure, parent=self
        ):
            return

        def research(
            cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> dict[str, Any]:
            result = self._lookup.refresh(lookup, confirmed=True, cancelled=cancelled)
            if result["status"] == "candidate" and not cancelled():
                root = operator_catalog_root() / "lookups"
                root.mkdir(parents=True, exist_ok=True)
                import hashlib

                atomic_write_text(
                    root / f"{hashlib.sha256(lookup.url.encode()).hexdigest()}.json",
                    json.dumps(result),
                )
            return result

        self._work(research, self._show)

    def _research(self) -> None:
        row = self._selected()
        if row and row.get("sha256") and row["identity_status"] == "verified":
            self._lookup_source(Lookup("civitai", row["sha256"]))
        else:
            self.status.set("Verify the selected asset's byte identity before hash lookup.")

    def _research_hf(self) -> None:
        try:
            self._lookup_source(
                Lookup("huggingface", self.repo.get().strip(), self.revision.get().strip())
            )
        except ValueError as exc:
            self.status.set(str(exc))

    def _import(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Import reviewed model_evidence_catalog/1 (advisory claims)",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return

        def load(
            cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> EvidenceCatalog:
            imported = EvidenceCatalog.load(Path(path))
            records = {r.record_id: r for r in (*self.catalog.records, *imported.records)}
            merged = EvidenceCatalog(tuple(records.values()))
            if cancelled():
                raise InterruptedError("Catalog selection cancelled; previous revision preserved")
            select_operator_catalog(merged, operator_catalog_root())
            return merged

        def loaded(catalog: EvidenceCatalog) -> None:
            self.catalog = catalog
            self.status.set(
                "Reviewed catalog imported. Existing Custom, Learning, favorites and startup defaults were not written."
            )
            self._selected_model_changed()

        self._work(load, loaded)

    def _inspect_active(self) -> None:
        controller = self.owner.learning_controller
        experiment = controller.learning_state.current_experiment
        if not experiment:
            self.status.set("Open a saved experiment first.")
            return
        plan = copy.deepcopy(controller.learning_state.plan)
        experiment = copy.deepcopy(experiment)

        def inspect(
            _cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> dict[str, Any]:
            writer = controller._learning_record_writer
            ratings = (
                writer.get_rating_details_for_experiment(experiment.experiment_id) if writer else {}
            )
            return inspect_experiment(experiment, plan, ratings)

        self._work(inspect, self._show)

    def _export(self) -> None:
        directory = filedialog.askdirectory(
            parent=self, title="Export relative-path evidence report"
        )
        if directory:
            controller = self.owner.learning_controller
            experiment = copy.deepcopy(controller.learning_state.current_experiment)
            plan = copy.deepcopy(controller.learning_state.plan)

            def export(_cancelled: Callable[[], bool], _progress: Callable[[str], None]) -> Any:
                outcomes = []
                if experiment and experiment.metadata.get("evidence_proposal"):
                    writer = controller._learning_record_writer
                    ratings = (
                        writer.get_rating_details_for_experiment(experiment.experiment_id)
                        if writer
                        else {}
                    )
                    outcomes.append(inspect_experiment(experiment, plan, ratings))
                return export_report(
                    Path(directory),
                    build_report(self.census, self.catalog, self.targets, self.proposals, outcomes),
                )

            self._work(
                export,
                lambda paths: self.status.set("Exported " + ", ".join(path.name for path in paths)),
            )


def open_model_evidence(owner: Any) -> ModelEvidenceWindow:
    return ModelEvidenceWindow(owner)
