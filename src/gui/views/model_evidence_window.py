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
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.assets.evidence_census import refresh_census
from src.assets.registry import AssetRegistry
from src.generation_profiles.evidence_catalog import (
    EvidenceCatalog,
    load_operator_catalog,
    operator_catalog_root,
    select_operator_catalog,
)
from src.generation_profiles.evidence_refresh import EvidenceRefresh, Lookup
from src.generation_profiles.evidence_report import build_report, export_report
from src.generation_profiles.identity import ModelIdentityResolver, RegistryShaLookup
from src.image_backends.model_policy import RegistryFamilyLookup
from src.learning import baseline_authoring as authoring
from src.learning.evidence_proposals import (
    ExperimentProposal,
    evidence_gaps,
    propose,
    save_proposal,
)
from src.learning.resource_access import get_resource_choices
from src.learning.setting_evidence import inspect_experiment
from src.utils.atomic_io import atomic_write_text
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)


class ModelEvidenceWindow(tk.Toplevel):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner)
        self.owner = owner
        self.title("Model Evidence Catalog — research and qualification drafts")
        self.geometry("1120x780")
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
        self._rows: dict[str, dict[str, Any]] = {}
        self._events: queue.Queue[tuple[int, str, Any, Any]] = queue.Queue(maxsize=64)
        self._cancel = threading.Event()
        self._busy, self._closed, self._generation = False, False, 0
        self._lookup = EvidenceRefresh()
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        for label, command in (
            ("Observe assets", lambda: self._refresh(False)),
            ("Verify identities (bounded)", lambda: self._refresh(True)),
            ("Cancel", self._cancel.set),
            ("Import reviewed catalog", self._import),
            ("Export report", self._export),
            ("Inspect active experiment", self._inspect_active),
        ):
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=2)
        ttk.Label(
            self,
            text="No startup research or generation. Observation is provisional; only fingerprint-verified hashes identify bytes.",
            padding=6,
        ).pack(anchor="w")
        self.status = tk.StringVar(
            value=catalog_error + "Choose Observe assets or Verify identities. No scan has started."
        )
        ttk.Label(self, textvariable=self.status, wraplength=1050, padding=6).pack(fill="x")
        self.filter = tk.StringVar()
        ttk.Entry(self, textvariable=self.filter).pack(fill="x", padx=6)
        self.filter.trace_add("write", lambda *_: self._render_assets())
        self.tree = ttk.Treeview(self, columns=("kind", "identity", "family", "size"), height=9)
        self.tree.heading("#0", text="Relative location (filter above)")
        self.tree.column("#0", width=600)
        for key in ("kind", "identity", "family", "size"):
            self.tree.heading(key, text=key)
            self.tree.column(key, width=100)
        self.tree.pack(fill="both", expand=True, padx=6)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._inspect_asset())
        actions = ttk.Frame(self, padding=6)
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="Plan tests for selected checkpoint (Learning baseline, model-owned VAE)",
            command=self._plan,
        ).pack(side="left")
        ttk.Button(
            actions, text="Look up selected verified hash on Civitai...", command=self._research
        ).pack(side="left", padx=4)
        source = ttk.Frame(self, padding=6)
        source.pack(fill="x")
        ttk.Label(source, text="HF exact repository / 40-character commit:").pack(side="left")
        self.repo, self.revision = tk.StringVar(), tk.StringVar()
        ttk.Entry(source, textvariable=self.repo, width=30).pack(side="left")
        ttk.Entry(source, textvariable=self.revision, width=44).pack(side="left", padx=4)
        ttk.Button(source, text="Look up revision...", command=self._research_hf).pack(side="left")
        self.proposal_list = tk.Listbox(self, height=5, exportselection=False)
        self.proposal_list.pack(fill="x", padx=6)
        self.proposal_list.bind("<<ListboxSelect>>", lambda _event: self._show_proposal())
        proposal_actions = ttk.Frame(self, padding=6)
        proposal_actions.pack(fill="x")
        ttk.Button(
            proposal_actions,
            text="Save selected proposal to Experiment Library",
            command=self._save,
        ).pack(side="left")
        ttk.Button(
            proposal_actions, text="Open saved proposal in Learning Design", command=self._open
        ).pack(side="left", padx=4)
        ttk.Button(
            proposal_actions, text="Experiment Library", command=owner._on_open_experiment_library
        ).pack(side="left")
        self.details = ScrolledText(self, height=15, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True, padx=6, pady=6)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._poll_id = self.after(75, self._poll)

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
                event = (generation, "done", result, success)
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
                if kind == "error":
                    self.status.set(value)
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
            if query not in (row["relative"] + " " + row["kind"] + " " + row["family"]).casefold():
                continue
            key = str(i)
            self._rows[key] = row
            self.tree.insert(
                "",
                "end",
                iid=key,
                text=row["relative"],
                values=(row["kind"], row["identity_status"], row["family"], row["size"]),
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

    def _plan(self) -> None:
        row = self._selected()
        if not row or row["kind"] != "checkpoint":
            self.status.set("Select a checkpoint first. Accessories receive usage metadata.")
            return
        controller = self.owner.learning_controller
        baseline = copy.deepcopy(controller.authoring_baseline())
        experiment = controller.learning_state.current_experiment
        prompt = getattr(experiment, "prompt_text", "") or simpledialog.askstring(
            "Freeze pilot prompt", "One fixed positive prompt for these proposals:", parent=self
        )
        if not prompt:
            return
        negative = str(
            (getattr(experiment, "metadata", {}) or {}).get("selected_prompt_negative_text", "")
        )
        resources = {
            key: get_resource_choices(controller, key)[0]
            for key in ("models", "samplers", "schedulers", "vaes")
        }

        def planned(
            _cancelled: Callable[[], bool], _progress: Callable[[str], None]
        ) -> tuple[Any, list[ExperimentProposal]]:
            target = self._resolver().resolve(Path(row["relative"]).name)
            config = copy.deepcopy(baseline)
            config.setdefault("txt2img", {}).update(model=target.identity.display_name, vae="")
            authoring.align_aliases(config, "txt2img")
            section = config["txt2img"]
            alternatives = (
                ("cfg_scale", 7.0),
                ("steps", 50),
                ("sampler", "DPM++ 2M"),
                ("scheduler", "Karras"),
            )
            proposals = []
            for variable, candidate in alternatives:
                key = "sampler_name" if variable == "sampler" else variable
                control = section.get(key)
                if control is None or control == candidate:
                    continue
                proposals.append(
                    propose(
                        self.catalog,
                        target,
                        config,
                        variable=variable,
                        values=(control, candidate),
                        prompt=prompt,
                        negative_prompt=negative,
                        resources=resources,
                        variant=row["header"].get("checkpoint_variant") or "",
                    )
                )
            return target, proposals

        def show(result: Any) -> None:
            target, self.proposals = result
            if not any(t.identity == target.identity for t in self.targets):
                self.targets.append(target)
            self.proposal_list.delete(0, "end")
            for p in self.proposals:
                self.proposal_list.insert(
                    "end",
                    f"{p.document['priority']} {p.document['status'].upper()} — {p.document['name']}",
                )
            self.status.set(
                "Select a proposal to inspect its hypothesis, baseline, evidence and blocked reasons. Saving never runs it."
            )

        self._work(planned, show)

    def _proposal(self) -> ExperimentProposal | None:
        selection = self.proposal_list.tk.splitlist(
            self.proposal_list.tk.call(self.proposal_list, "curselection")
        )
        return self.proposals[int(selection[0])] if selection else None

    def _show_proposal(self) -> None:
        proposal = self._proposal()
        if proposal:
            self._show(dict(proposal.document))

    def _save(self) -> None:
        proposal = self._proposal()
        if proposal:
            self._work(
                lambda _c, _p: save_proposal(proposal, self.owner.experiment_store),
                lambda identity: self.status.set(
                    f"Saved/preserved draft {identity}; open it from the Experiment Library."
                ),
            )

    def _open(self) -> None:
        proposal = self._proposal()
        if proposal:

            def loaded(payload: Any) -> None:
                if not payload:
                    self.status.set("Save the selected runnable proposal first.")
                elif self.owner._restore_from_store_payload(
                    payload, experiment_id=proposal.proposal_id
                ):
                    self.status.set(
                        "Opened in Learning Design. Inspect, Build Preview, then explicitly Run."
                    )

            self._work(
                lambda _c, _p: self.owner.experiment_store.load_session(proposal.proposal_id),
                loaded,
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
