"""Explicit operator catalog journey. Workers return data; only Tk callbacks touch widgets.

The window lists every cached checkpoint with what StableNew already knows about it (byte identity, registry
family, past queue runs, catalog-derived experiments) and the one next step for it. Opening it reads only the
persisted registry cache; the library-wide assessment and run-history summary run on a background worker and are
read-only. Hashing happens only through Scan & Verify Library or Verify Selected, and each finished hash is persisted
by the AssetRegistry, so a later session reuses it. Nothing here generates, applies or publishes.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from src.assets.checkpoint_structure import checkpoint_variant_from_metadata
from src.assets.evidence_census import CensusBudget, refresh_census
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
from src.gui.controllers.model_evidence_next_test import (
    assess_model,
    capture_services,
    revalidate,
)
from src.gui.controllers.model_evidence_proposals import (
    capture_resources,
    preview_selected,
    save_drafts,
)
from src.gui.views.model_evidence_proposals_dialog import (
    ModelEvidenceProposalsDialog,
    choose_prompt_context,
)
from src.gui.views.next_test_dialog import NextTestDialog
from src.gui_v2.next_test_view import build_view, route_for
from src.image_backends.image_backend_types import normalize_image_backend_options
from src.image_backends.model_policy import RegistryFamilyLookup
from src.image_backends.model_readiness_probe import checkpoint_key
from src.learning.evidence_autopilot import (
    EvidenceProposalPlanner,
    ProposalPlan,
    ProposalPlanningContext,
)
from src.learning.evidence_proposals import (
    ExperimentProposal,
    evidence_gaps,
)
from src.learning.intelligence_contracts import (
    WORKFLOW_CATALOG_RESEARCH,
    WORKFLOW_DRAFT_PREPARATION,
    WORKFLOW_IDENTITY_VERIFICATION,
    WORKFLOW_LEARNING_REVIEW,
    WORKFLOW_PROPOSED_EXPERIMENTS,
    WORKFLOW_RECOMMENDATION_APPLY,
    IntelligenceReport,
)
from src.learning.model_run_history import ModelRunSummary, read_run_history
from src.learning.qualification_batch import BatchOutcome
from src.learning.setting_evidence import inspect_experiment
from src.utils.atomic_io import atomic_write_text
from src.utils.thread_registry import get_thread_registry

logger = logging.getLogger(__name__)

CHECKPOINT_ROOT_LABEL = "models/Stable-diffusion"
#: Scan & Verify Library hashes the whole library in one explicit, cancellable pass. Every finished file is
#: persisted as it completes, so cancelling keeps the work done; these limits only stop a runaway pass.
VERIFY_BUDGET = CensusBudget(max_assets=4096, max_hash_bytes=16 * 1024**4, max_seconds=24 * 3600.0)
SCOPE_SELECTION, SCOPE_LIBRARY = "selection", "library"
#: Fields compared between catalog claims and what past runs actually used.
_COMPARED_FIELDS = (
    ("steps", "steps"),
    ("cfg_scale", "cfg_scale"),
    ("sampler_name", "sampler_name"),
)
HOW_TO = (
    "1  Scan & Verify Library (once; hashes are saved and reused next session)   "
    "2  Select a checkpoint to see its identity, past runs and catalog evidence   "
    "3  Proposed Experiments saves, previews or queues the ones marked ready. Nothing generates without your confirmation."
)


@dataclass(frozen=True)
class RowAssessment:
    """Display-only summary of one checkpoint. Actions always replan from fresh inputs."""

    identity: str
    family: str
    ready: int | None
    next_step: str
    lines: tuple[str, ...] = ()
    catalog_claims: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def display_name(row: Mapping[str, Any]) -> str:
    relative = str(row.get("relative", ""))
    prefix = CHECKPOINT_ROOT_LABEL + "/"
    return relative[len(prefix) :] if relative.startswith(prefix) else relative


def _identity_label(row: Mapping[str, Any], target: Any | None) -> str:
    if target is not None and target.identity.sha256:
        return "Verified"
    if row.get("identity_status") == "verified" and row.get("sha256"):
        # This file is hashed, but its name is shared with a different file, so the name is not one identity.
        return "Ambiguous name"
    return "Not verified"


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def assess_row(
    row: Mapping[str, Any],
    *,
    resolver: Any,
    catalog: EvidenceCatalog,
    planning: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
) -> RowAssessment:
    """Identity, family, catalog claims and the planner's verdict for one checkpoint (pure; no I/O beyond the resolver)."""
    name = Path(str(row.get("relative", ""))).name
    target = resolver.resolve(name)
    identity = _identity_label(row, target)
    family = target.identity.family
    if not target.policy.qualified and family not in ("unknown", "sdxl"):
        family = f"{family} (not qualified)"
    variant = str((row.get("header") or {}).get("checkpoint_variant") or "")
    claims: dict[str, list[str]] = {}
    # The header names the subtype ("turbo"); the catalog keys its publisher recipe by lineage ("sdxl_turbo").
    claim_variant = (
        "sdxl_turbo" if variant == "turbo" and target.identity.family == "sdxl" else variant
    )
    for coverage in catalog.coverage(target.identity, variant=claim_variant):
        for claim in coverage.claims:
            claims.setdefault(coverage.field, []).append(
                f"{claim.value} ({claim.classification}, {claim.confidence})"
            )
    lines = [
        f"Identity: {identity}"
        + (f" — SHA-256 {target.identity.sha256[:12]}…" if target.identity.sha256 else ""),
        f"Family: {target.identity.family}; policy {target.policy.policy_id}"
        + (" (qualified)" if target.policy.qualified else ""),
    ]
    if target.unverified_reason:
        lines.append(f"  {target.unverified_reason}")
    if variant:
        lines.append(f"Variant from file header: {variant}")
    ready: int | None = None
    if identity == "Ambiguous name":
        next_step = (
            "Two different files share this name; rename one so its identity is unambiguous."
        )
    elif identity == "Not verified":
        next_step = "Verify Selected (or Scan & Verify Library) to identify this file."
    else:
        next_step = ""
    if planning is not None and identity == "Verified":
        baseline, resources = planning
        safe = copy.deepcopy(dict(baseline))
        safe["backend_options"] = normalize_image_backend_options(
            safe.get("backend_options"), model_name=target.identity.display_name
        )
        try:
            plan = EvidenceProposalPlanner().plan(
                ProposalPlanningContext(target, catalog, safe, resources, variant=variant)
            )
        except (ValueError, KeyError, TypeError) as exc:
            next_step = f"Cannot plan with the current Learning baseline: {_short(str(exc))}"
        else:
            proposals = plan.proposals
            ready = sum(p.runnable for p in proposals)
            lines.append("Catalog-derived experiments:")
            for proposal in proposals:
                document = proposal.document
                state = "READY" if proposal.runnable else str(document["status"]).upper()
                lines.append(
                    f"  [{state}] {document['variable']}: {_short(document['objective'], 120)}"
                )
                if not proposal.runnable:
                    lines.extend(
                        f"      why not: {_short(reason, 140)}"
                        for reason in document.get("blocked_reasons", [])[:2]
                    )
            if ready:
                next_step = (
                    f"{ready} experiment{'s' if ready != 1 else ''} ready: Proposed Experiments."
                )
            else:
                metadata = [p for p in proposals if p.document["status"] == "metadata_only"]
                blocked = [p for p in proposals if p.document["status"] == "blocked"]
                if target.identity.family == "unknown":
                    next_step = (
                        "File verified, but StableNew cannot classify its family yet; no experiment can be "
                        "proposed until it is identified."
                    )
                elif metadata and not blocked and not target.policy.qualified:
                    next_step = (
                        f"{target.identity.family} is not a qualified family in StableNew, so no experiment "
                        "is proposed; see past runs below."
                    )
                elif metadata and not blocked:
                    next_step = _short(
                        "Nothing to vary yet: " + metadata[0].document["blocked_reasons"][0], 110
                    )
                elif blocked:
                    next_step = _short(
                        "Blocked: " + blocked[0].document["blocked_reasons"][-1], 110
                    )
                else:
                    next_step = "No experiment derived for this checkpoint."
    elif planning is None and identity == "Verified":
        gaps = evidence_gaps(catalog, target, variant=variant)
        next_step = _short(gaps[0].reason, 110) if gaps else "Open Proposed Experiments."
    return RowAssessment(
        identity,
        family,
        ready,
        next_step,
        tuple(lines),
        {key: tuple(value) for key, value in claims.items()},
    )


def compare_with_history(
    claims: Mapping[str, tuple[str, ...]], history: ModelRunSummary | None
) -> list[str]:
    """Side-by-side note of catalog claims and the values past runs used; descriptive only."""
    if history is None or not history.completed:
        return []
    used = dict(history.settings)
    lines = []
    for field_name, label in _COMPARED_FIELDS:
        values = used.get(field_name) or ()
        source = claims.get(label) or ()
        if values and source:
            lines.append(
                f"  {label}: catalog says {', '.join(source[:2])}; your completed runs mostly used {values[0][0]}"
            )
    if lines:
        lines.insert(
            0, "Catalog vs. your runs (a mismatch can explain artifacts; not a recommendation):"
        )
    return lines


class ModelEvidenceWindow(tk.Toplevel):
    def __init__(self, owner: Any) -> None:
        super().__init__(owner)
        self.owner = owner
        self.title("Model Evidence Catalog")
        self.geometry(
            f"{min(1240, self.winfo_screenwidth() - 24)}x{min(760, self.winfo_screenheight() - 96)}"
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
        self._next_dialog: NextTestDialog | None = None
        self._next_report: IntelligenceReport | None = None
        self._next_when_ready = False
        self._rows: dict[str, dict[str, Any]] = {}
        #: Absolute file per row ``relative``; kept out of rows so exports stay path-free.
        self._paths: dict[str, Path] = {}
        self._assessments: dict[str, RowAssessment] = {}
        self._history: dict[str, ModelRunSummary] | None = None
        self._history_note = "Past runs: reading job history…"
        self._history_state = "loading"  # loading | ready | unavailable
        self._details_mode = "summary"
        self._sort: tuple[str, bool] = ("#0", False)
        self._events: queue.Queue[tuple[int, str, Any, Any]] = queue.Queue(maxsize=64)
        self._cancel = threading.Event()
        self._bg_cancel = threading.Event()
        self._busy, self._closed, self._generation, self._bg_generation = False, False, 0, 0
        self._work_scope = SCOPE_SELECTION
        self._replan_after_work = False
        self._lookup = EvidenceRefresh()

        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        self.scan_button = ttk.Button(
            bar, text="Scan & Verify Library", command=lambda: self._refresh(True)
        )
        self.scan_button.pack(side="left")
        self.verify_button = ttk.Button(
            bar, text="Verify Selected", command=self._verify_selected, state="disabled"
        )
        self.verify_button.pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self._cancel_work).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self._reload).pack(side="left", padx=4)
        self.evidence_menu = tk.Menu(bar, tearoff=False)
        evidence = ttk.Menubutton(bar, text="More…", menu=self.evidence_menu)
        evidence.pack(side="right")
        for label, command in (
            ("Quick scan (no hashing; header-only)", lambda: self._refresh(False)),
            (None, None),
            ("Look up selected model on Civitai (sends its SHA-256)…", self._research),
            ("Look up exact Hugging Face revision…", self._hf_dialog),
            ("Import reviewed evidence catalog…", self._import),
            ("Export evidence report…", self._export),
            (None, None),
            ("Inspect active Learning experiment", self._inspect_active),
            ("Raw scan data (JSON)", lambda: self._show(self.census)),
        ):
            if label is None:
                self.evidence_menu.add_separator()
            else:
                self.evidence_menu.add_command(label=label, command=command)
        ttk.Button(bar, text="Experiment Library", command=owner._on_open_experiment_library).pack(
            side="right", padx=4
        )
        ttk.Label(self, text=HOW_TO, wraplength=1180, padding=(6, 0)).pack(anchor="w")
        self.status = tk.StringVar(
            value=catalog_error
            + "Showing saved identities from earlier scans. Nothing is hashed or generated until you ask."
        )
        self.summary = tk.StringVar(value="Assessing checkpoints…")
        ttk.Label(self, textvariable=self.summary, wraplength=1180, padding=(6, 2)).pack(fill="x")
        ttk.Label(self, textvariable=self.status, wraplength=1180, padding=(6, 2)).pack(fill="x")
        search = ttk.Frame(self, padding=(6, 0))
        search.pack(fill="x")
        ttk.Label(search, text="Search").pack(side="left")
        self.filter = tk.StringVar()
        ttk.Entry(search, textvariable=self.filter).pack(side="left", fill="x", expand=True, padx=4)
        self.filter.trace_add("write", lambda *_: self._render_assets())
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=6, pady=4)
        table = ttk.Frame(panes)
        self.tree = ttk.Treeview(
            table,
            columns=("identity", "family", "runs", "last_run", "ready", "next"),
            height=14,
        )
        for key, title, width in (
            ("#0", "Checkpoint", 330),
            ("identity", "Identity", 100),
            ("family", "Family", 120),
            ("runs", "Past runs", 120),
            ("last_run", "Last run", 85),
            ("ready", "Ready", 55),
            ("next", "Next step", 400),
        ):
            self.tree.heading(key, text=title, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=width, stretch=key in ("#0", "next"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selected_model_changed())
        panes.add(table, weight=3)
        self._details_host = ttk.Frame(panes)
        self.details = ScrolledText(self._details_host, height=10, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True)
        panes.add(self._details_host, weight=2)
        actions = ttk.Frame(self, padding=6)
        actions.pack(fill="x")
        self.proposed_button = ttk.Button(
            actions,
            text="Proposed Experiments (select a model)",
            command=self._plan,
            state="disabled",
        )
        self.proposed_button.pack(side="left")
        self.next_button = ttk.Button(
            actions,
            text="What Should I Test Next?",
            command=self._test_next,
            state="disabled",
        )
        self.next_button.pack(side="left", padx=4)
        ttk.Button(actions, text="Raw Evidence (JSON)", command=self._inspect_asset).pack(
            side="left", padx=4
        )
        self.repo, self.revision = tk.StringVar(), tk.StringVar()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._poll_id = self.after(75, self._poll)
        self._load_cached_assets()
        self._show(
            mode="summary",
            data="Select a checkpoint to see what is known about it.\n\n"
            "Identity — Verified means the file's SHA-256 is known (saved from an earlier scan and still matching "
            "its size and date).\nPast runs — jobs that already ran through the queue with this checkpoint "
            "(observational; never used as a recommendation).\nReady — experiments the evidence catalog can "
            "propose right now with your current Learning baseline.\nNext step — the one thing to do for this "
            "checkpoint.",
        )
        self._start_assessment(read_history=True)

    # ----------------------------------------------------------------- lifecycle and workers

    def _close(self) -> None:
        self._closed = True
        self._next_when_ready = False
        self._cancel.set()
        self._bg_cancel.set()
        self.after_cancel(self._poll_id)
        self.destroy()

    def _on_destroy(self, event: Any) -> None:
        if event.widget is self:
            self._closed = True
            self._cancel.set()
            self._bg_cancel.set()

    def bring_to_front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _show(self, data: Any, *, mode: str = "raw") -> None:
        self._details_mode = mode
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert(
            "1.0", data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
        )
        self.details.configure(state="disabled")

    def _cancel_work(self) -> None:
        self._cancel.set()
        if self._busy:
            self.status.set("Cancelling… files already verified stay saved.")

    def _work(
        self,
        action: Callable[[Callable[[], bool], Callable[[str], None]], Any],
        success: Callable[[Any], None],
        *,
        scope: str = SCOPE_SELECTION,
    ) -> None:
        if self._busy:
            self.status.set(
                "Another operation is running (see progress above). Wait for it, or press Cancel."
            )
            return
        self._busy = True
        self._work_scope = scope
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
            self._deliver(event)

        get_thread_registry().spawn(
            target=run, name="model-evidence", purpose="bounded operator evidence lookup"
        )

    def _deliver(self, event: tuple[int, str, Any, Any]) -> None:
        # A closing view must not strand a worker on a full result queue.
        while not self._closed:
            try:
                self._events.put(event, timeout=0.1)
                break
            except queue.Full:
                continue

    def _poll(self) -> None:
        for _ in range(64):
            try:
                generation, kind, value, callback = self._events.get_nowait()
            except queue.Empty:
                break
            if self._closed:
                continue
            if kind.startswith("bg-"):
                if generation == self._bg_generation:
                    callback(value)
                continue
            if generation != self._generation:
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
                        "Operation cancelled. Verified files, saved drafts and any confirmed admissions remain; inspect exact jobs before retrying."
                    )
                else:
                    callback(value)
                if self._replan_after_work and not self._busy:
                    self._replan_after_work = False
                    self._selected_model_changed()
        self._poll_id = self.after(75, self._poll)

    # ----------------------------------------------------------------- library assessment (background, read-only)

    def _planning_inputs_for_library(self) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
        controller = getattr(self.owner, "learning_controller", None)
        if controller is None:
            return None
        try:
            baseline = copy.deepcopy(
                controller.authoring_baseline() or controller._get_baseline_config()
            )
            getter = getattr(controller.app_controller, "get_current_global_prompt_policy", None)
            policy = getter() if callable(getter) else None
            if isinstance(policy, dict):
                from src.pipeline.global_prompt_policy import apply_global_prompt_policy

                baseline = apply_global_prompt_policy(baseline, **policy)
            return baseline, capture_resources(controller)
        except Exception:  # noqa: BLE001 - a missing baseline only hides the Ready column
            logger.debug("Library assessment has no Learning baseline", exc_info=True)
            return None

    def _history_repository(self) -> Any | None:
        controller = getattr(self.owner, "learning_controller", None)
        service = getattr(getattr(controller, "app_controller", None), "job_service", None)
        repository = getattr(service, "history_store", None)
        return repository if callable(getattr(repository, "read_run_evidence_page", None)) else None

    def _start_assessment(self, *, read_history: bool = False) -> None:
        """Assess every listed checkpoint (and optionally summarize job history) without blocking actions."""
        rows = [copy.deepcopy(row) for row in self._checkpoint_rows()]
        planning = self._planning_inputs_for_library()
        repository = self._history_repository() if read_history else None
        if read_history and repository is None:
            self._history_note = "Past runs: job history is not available in this window."
            self._history_state = "unavailable"
        elif read_history:
            self._history_state, self._history = "loading", None
        catalog = self.catalog
        self._bg_cancel.set()
        self._bg_cancel = threading.Event()
        self._bg_generation += 1
        generation, cancel = self._bg_generation, self._bg_cancel

        def run() -> None:
            try:
                resolver = self._library_resolver()
                assessed: dict[str, RowAssessment] = {}
                for row in rows:
                    if cancel.is_set():
                        return
                    try:
                        assessed[row["relative"]] = assess_row(
                            row, resolver=resolver, catalog=catalog, planning=planning
                        )
                    except Exception as exc:  # noqa: BLE001 - one bad row must not hide the others
                        logger.debug("Assessment failed for a checkpoint", exc_info=True)
                        assessed[row["relative"]] = RowAssessment(
                            "?",
                            str(row.get("family", "unknown")),
                            None,
                            f"Could not assess: {type(exc).__name__}",
                        )
                self._deliver((generation, "bg-assessed", assessed, self._assessed))
                if repository is not None and not cancel.is_set():
                    try:
                        history: Any = read_run_history(repository, cancelled=cancel.is_set)
                    except InterruptedError:
                        return
                    except Exception as exc:  # noqa: BLE001 - history is optional context
                        logger.warning("Run history summary failed: %s", exc)
                        history = exc
                    self._deliver((generation, "bg-history", history, self._history_ready))
            except Exception:  # noqa: BLE001 - never let a background summary crash the app
                logger.exception("Model evidence library assessment failed")

        get_thread_registry().spawn(
            target=run, name="model-evidence-library", purpose="read-only checkpoint assessment"
        )

    def _library_resolver(self) -> ModelIdentityResolver:
        # Its own registry instance: never shares in-memory cache state with a running scan or selection worker.
        registry = AssetRegistry()
        return ModelIdentityResolver(
            family_lookup=RegistryFamilyLookup(registry),
            sha_lookup=RegistryShaLookup(registry),
        )

    def _assessed(self, assessed: dict[str, RowAssessment]) -> None:
        self._assessments = assessed
        self._render_assets()
        self._update_summary_status()
        if self._details_mode == "summary":
            self._render_details()

    def _history_ready(self, history: Any) -> None:
        if isinstance(history, Exception):
            self._history = {}
            self._history_note = (
                f"Past runs: job history could not be read ({type(history).__name__})."
            )
        else:
            self._history = history
            runs = sum(summary.total for summary in history.values())
            self._history_note = f"Past runs: {runs} jobs across {len(history)} checkpoint names."
        self._history_state = "ready"
        self._render_assets()
        self._update_summary_status()
        if self._details_mode == "summary":
            self._render_details()

    def _update_summary_status(self) -> None:
        rows = self._checkpoint_rows()
        verified = sum(
            self._assessments.get(row["relative"], RowAssessment("", "", None, "")).identity
            == "Verified"
            for row in rows
        )
        ready = sum(
            1
            for row in rows
            if (self._assessments.get(row["relative"]) or RowAssessment("", "", 0, "")).ready
        )
        self.summary.set(
            f"{len(rows)} checkpoints: {verified} verified, {len(rows) - verified} need verification; "
            f"{ready} with experiments ready. {self._history_note}"
        )

    def _reload(self) -> None:
        self._load_cached_assets()
        self._start_assessment(read_history=True)

    # ----------------------------------------------------------------- rows

    def _checkpoint_rows(self) -> list[dict[str, Any]]:
        return [row for row in self.census.get("assets", []) if row.get("kind") == "checkpoint"]

    def _history_for(self, row: Mapping[str, Any]) -> ModelRunSummary | None:
        if self._history is None:
            return None
        return self._history.get(checkpoint_key(Path(str(row.get("relative", ""))).name))

    def _row_values(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        assessment = self._assessments.get(row["relative"])
        history = self._history_for(row)
        if self._history_state == "unavailable":
            runs, last = "n/a", ""
        elif self._history is None:
            runs, last = "…", ""
        elif history is None:
            runs, last = "none", ""
        else:
            runs, last = history.runs_label(), history.last_run
        warning = (
            "Never completed in past runs (see details). "
            if history is not None and history.failed and not history.completed
            else ""
        )
        if assessment is None:
            identity = (
                "Verified file" if row.get("identity_status") == "verified" else "Not verified"
            )
            return (identity, row.get("family", "unknown"), runs, last, "…", warning + "Assessing…")
        ready = "" if assessment.ready is None else str(assessment.ready)
        return (
            assessment.identity,
            assessment.family,
            runs,
            last,
            ready,
            warning + assessment.next_step,
        )

    def _render_assets(self) -> None:
        selected_row = self._selected()
        selected_relative = selected_row["relative"] if selected_row else None
        query = self.filter.get().casefold()
        self._rows = {}
        entries = []
        for i, row in enumerate(self.census.get("assets", [])):
            if row["kind"] != "checkpoint":
                continue
            if query not in (row["relative"] + " " + row["kind"] + " " + row["family"]).casefold():
                continue
            entries.append((str(i), row, self._row_values(row)))
        column, reverse = self._sort
        if column != "#0" or reverse:
            index = (
                ("identity", "family", "runs", "last_run", "ready", "next").index(column)
                if column != "#0"
                else -1
            )

            def sort_key(entry: tuple[str, dict[str, Any], tuple[str, ...]]) -> Any:
                text = display_name(entry[1]) if index < 0 else entry[2][index]
                head = text.split(" ", 1)[0]
                return (
                    (0, float(head), text)
                    if head.replace(".", "", 1).isdigit()
                    else (1, 0.0, text.casefold())
                )

            entries.sort(key=sort_key, reverse=reverse)
        if [key for key, _row, _values in entries] == list(self.tree.get_children()):
            # Same rows in the same order: update in place so the selection (and its event) is untouched.
            for key, row, values in entries:
                self._rows[key] = row
                self.tree.item(key, text=display_name(row), values=values)
            return
        self.tree.delete(*self.tree.get_children())
        for key, row, values in entries:
            self._rows[key] = row
            self.tree.insert("", "end", iid=key, text=display_name(row), values=values)
            if row["relative"] == selected_relative:
                self.tree.selection_set(key)

    def _sort_by(self, column: str) -> None:
        current, reverse = self._sort
        self._sort = (
            column,
            not reverse if current == column else column in ("runs", "last_run", "ready"),
        )
        self._render_assets()

    def _selected(self) -> dict[str, Any] | None:
        selection = self.tree.selection()
        return self._rows.get(selection[0]) if selection else None

    def _resolver(self) -> ModelIdentityResolver:
        return ModelIdentityResolver(
            family_lookup=RegistryFamilyLookup(self.registry),
            sha_lookup=RegistryShaLookup(self.registry),
        )

    def _render_details(self) -> None:
        row = self._selected()
        if row is None:
            return
        path = self._paths.get(row["relative"])
        lines = [display_name(row), ""]
        assessment = self._assessments.get(row["relative"])
        if assessment is None:
            lines.append("Assessing… (identity, family and catalog experiments)")
        else:
            lines.append(f"NEXT STEP: {assessment.next_step}")
            lines.append("")
            lines.extend(assessment.lines)
        lines.append("")
        lines.append("PAST RUNS (observational; never used as a recommendation)")
        history = self._history_for(row)
        if self._history is None or self._history_state != "ready":
            lines.append("  " + self._history_note)
        elif history is None:
            lines.append("  No jobs in history for this checkpoint name.")
        else:
            lines.extend("  " + line for line in history.describe())
            if assessment is not None:
                lines.extend(compare_with_history(assessment.catalog_claims, history))
        if assessment is not None and assessment.catalog_claims:
            lines.append("")
            lines.append("CATALOG CLAIMS (advisory; source class and confidence in brackets)")
            for name, values in sorted(assessment.catalog_claims.items()):
                lines.append(f"  {name}: {'; '.join(values[:3])}")
        if path is not None and "Not Working" in Path(display_name(row)).parts:
            lines.append("")
            lines.append(
                "This file is in your 'Not Working' folder. Compare the catalog claims with the settings your "
                "past runs used above: a sampler/steps/CFG mismatch or a missing component often explains artifacts."
            )
        self._show("\n".join(lines), mode="summary")

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
        """Rows from the persisted registry cache: one per real file, with its saved identity (never hashes)."""
        rows: list[dict[str, Any]] = []
        self._paths = {}
        seen: dict[str, int] = {}
        missing = 0
        verified_sha256 = getattr(self.registry, "verified_sha256", None)
        supported = getattr(self.registry, "supported_roots", None)
        roots = []
        for kind, root in supported() if callable(supported) else ():
            if kind is AssetKind.CHECKPOINT:
                try:
                    roots.append(root.resolve())
                except OSError:
                    continue
        for record in self.registry.cached_snapshot().records_for(AssetKind.CHECKPOINT):
            for location in record.locations:
                if location.kind != AssetKind.CHECKPOINT:
                    continue
                try:
                    resolved = location.path.resolve()
                    real = os.path.normcase(str(resolved))
                    exists = location.path.is_file()
                    # Relative to the configured checkpoint folder, so subfolders such as "Not Working" show.
                    relative = (
                        next(
                            (
                                resolved.relative_to(root).as_posix()
                                for root in roots
                                if resolved.is_relative_to(root)
                            ),
                            None,
                        )
                        or location.path.relative_to(location.root).as_posix()
                    )
                except (ValueError, OSError):
                    continue
                if not exists:
                    missing += 1
                    continue
                digest = verified_sha256(location.path) if callable(verified_sha256) else None
                verified = bool(digest) and digest == record.sha256
                family = (
                    record.compatibility.family.value
                    if record.compatibility and record.compatibility.family
                    else "unknown"
                )
                row = {
                    "kind": "checkpoint",
                    "relative": f"{CHECKPOINT_ROOT_LABEL}/{relative}",
                    "family": family,
                    "identity_status": "verified" if verified else "pending",
                    "size": location.byte_size,
                    "sha256": record.sha256 if verified else None,
                    "header": {
                        "checkpoint_variant": checkpoint_variant_from_metadata(
                            record.embedded_metadata
                        )
                    },
                }
                if real in seen:  # the same file reached through a link and its real folder
                    if verified and rows[seen[real]]["identity_status"] != "verified":
                        rows[seen[real]] = row
                    continue
                seen[real] = len(rows)
                rows.append(row)
                self._paths[row["relative"]] = location.path
        rows.sort(key=lambda item: display_name(item).casefold())
        self.census = {"assets": rows, "complete": False, "errors": [], "cached": True}
        if missing:
            self.status.set(
                f"{missing} saved entr{'y points' if missing == 1 else 'ies point'} to a file that no longer exists (ignored). "
                + self.status.get()
            )
        self._render_assets()

    # ----------------------------------------------------------------- scanning and verification

    def _refresh(self, verify: bool) -> None:
        def finished(result: Any) -> None:
            census, self.targets = result
            self.census = census
            webui = getattr(self.registry, "webui_root", None)
            self._paths = (
                {row["relative"]: Path(webui) / row["relative"] for row in census["assets"]}
                if webui
                else {}
            )
            checkpoints = [row for row in census["assets"] if row["kind"] == "checkpoint"]
            pending = sum(row["identity_status"] != "verified" for row in checkpoints)
            self.status.set(
                f"{'Complete' if census['complete'] else 'Partial'}: {len(census['assets'])} files, "
                f"{census['verified']} verified ({census['unchanged']} reused from earlier scans); "
                f"{pending} checkpoints still unverified; {len(census['errors'])} errors."
                + (
                    ""
                    if verify
                    else " Quick scan does not hash: use Scan & Verify Library to identify files."
                )
            )
            self._render_assets()
            self._start_assessment()

        def scan(cancelled: Callable[[], bool], progress: Callable[[str], None]) -> Any:
            census = refresh_census(
                self.registry,
                verify=verify,
                budget=VERIFY_BUDGET if verify else CensusBudget(),
                cancelled=cancelled,
                progress=progress,
            )
            resolver = self._resolver()
            targets = [
                resolver.resolve(Path(row["relative"]).name)
                for row in census["assets"]
                if row["kind"] == "checkpoint"
            ]
            return census, targets

        self.status.set(
            "Scanning and verifying the library. Each finished file is saved; Cancel keeps them."
            if verify
            else "Quick scan (no hashing)…"
        )
        self._work(scan, finished, scope=SCOPE_LIBRARY)

    def _verify_selected(self) -> None:
        row = self._selected()
        path = self._paths.get(row["relative"]) if row else None
        if row is None or path is None:
            self.status.set("Select a checkpoint from the list first.")
            return

        def verify(cancelled: Callable[[], bool], progress: Callable[[str], None]) -> str:
            def on_bytes(_path: Path, done: int, total: int) -> None:
                progress(f"Verifying {display_name(row)}: {done / 1e9:.1f} of {total / 1e9:.1f} GB")

            self.registry.refresh(checkpoint_paths=[path], cancelled=cancelled, progress=on_bytes)
            return str(self.registry.verified_sha256(path) or "")

        def done(digest: str) -> None:
            if digest:
                row.update(identity_status="verified", sha256=digest)
                self.status.set(
                    f"Verified {display_name(row)} (SHA-256 {digest[:12]}…). Saved for next session."
                )
            else:
                self.status.set(f"{display_name(row)} could not be verified.")
            self._start_assessment()

        self._work(verify, done, scope=SCOPE_LIBRARY)

    # ----------------------------------------------------------------- selection

    def _selected_model_changed(self) -> None:
        if self._busy and self._work_scope == SCOPE_LIBRARY:
            # A scan, verification or save keeps running; this selection is planned once it finishes.
            self._replan_after_work = True
        else:
            self._cancel.set()
            self._generation += 1
            self._busy = False
        self.proposal_plan = self.planning_context = None
        self.proposals = []
        if self._proposal_dialog is not None and self._proposal_dialog.winfo_exists():
            self._proposal_dialog.refuse_stale()
        row = self._selected()
        assessment = self._assessments.get(row["relative"]) if row else None
        ready = f" ({assessment.ready})" if assessment and assessment.ready is not None else ""
        self.proposed_button.configure(
            text=f"Proposed Experiments{ready or ' (checking…)'}"
            if row
            else "Proposed Experiments (select a model)",
            state="disabled",
        )
        self.verify_button.configure(state="normal" if row else "disabled")
        self.next_button.configure(state="disabled")
        self._next_report = None
        follow = self._next_dialog is not None and self._next_dialog.winfo_exists()
        if follow:
            self._next_dialog.mark_stale(
                "The selected model changed. Updating for the new selection…"
                if row
                else "The selected model changed. Refresh from the new selection."
            )
        self._render_details()
        if row and getattr(self.owner, "learning_controller", None) is not None and not self._busy:
            self._next_when_ready = self._next_when_ready or follow
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
            self.next_button.configure(state="normal")
            current_row = self._selected()
            if current_row is not None and target.identity.sha256:
                current_row.update(identity_status="verified", sha256=target.identity.sha256)
            if count:
                summary = (
                    f"{count} experiment{'s' if count != 1 else ''} ready for this checkpoint."
                )
            else:
                summary = "No experiment is ready for this checkpoint; the details below say why."
            self.status.set(summary + " Planning used no prompt, network lookup or generation.")
            if open_dialog:
                self._proposal_dialog = ModelEvidenceProposalsDialog(self, self.proposal_plan)
                self._keep_in_front(self._proposal_dialog)
            if self._next_when_ready:
                self._next_when_ready = False
                self._test_next()

        self._work(planned, show)

    def _keep_in_front(self, dialog: tk.Toplevel) -> None:
        """A child dialog stays above this window, and closing it returns here, not to the main window."""
        try:
            dialog.transient(self)
        except tk.TclError:
            return

        def returned(event: Any) -> None:
            if event.widget is dialog and not self._closed:
                self.after_idle(self.bring_to_front)

        dialog.bind("<Destroy>", returned, add="+")

    def request_next_test(self, model_name: str) -> None:
        """Entry from Learning results: select the experiment's checkpoint, then open the suggestion."""
        wanted = checkpoint_key(Path(str(model_name or "")).name)
        key = next(
            (
                k
                for k, row in self._rows.items()
                if wanted and checkpoint_key(Path(row["relative"]).name) == wanted
            ),
            None,
        )
        if key is None:
            self.status.set(
                "The current model is not in the cached checkpoint list. Select a checkpoint, "
                "or run Scan & Verify Library first."
            )
            return
        self._next_when_ready = True
        self.tree.selection_set(key)
        self.tree.see(key)

    def _test_next(self) -> None:
        row = self._selected()
        if not row or row["kind"] != "checkpoint":
            self.status.set("Select a checkpoint first.")
            return
        try:
            inputs, services = self._capture_planning_inputs(), capture_services(self.owner)
        except (ValueError, AttributeError) as exc:
            self.status.set(f"Cannot assess this model yet: {exc}")
            return
        self.status.set("Reading saved evidence… no generation, network or AI is used.")

        def assess_work(_cancelled: Callable[[], bool], _progress: Callable[[str], None]) -> Any:
            return assess_model(self._context(inputs), services)

        def show(report: IntelligenceReport) -> None:
            self._next_report = report
            geometry = None
            if self._next_dialog is not None and self._next_dialog.winfo_exists():
                geometry = self._next_dialog.geometry()
                self._next_dialog.close()
            self._next_dialog = NextTestDialog(
                self,
                build_view(report),
                on_open=self._open_next_action,
                on_refresh=self._test_next,
            )
            if geometry:
                self._next_dialog.geometry(geometry)
            self._keep_in_front(self._next_dialog)
            self.status.set(
                "What Should I Test Next? is ready and follows your selection. Nothing was started."
            )

        self._work(assess_work, show)

    def _open_next_action(self, action_id: str) -> None:
        """Revalidate against current evidence on the worker, then use an existing workflow."""
        if self._busy:
            self.status.set("Wait for the current bounded operation, then choose the action again.")
            return
        inputs, services = self._capture_planning_inputs(), capture_services(self.owner)

        def check(_cancelled: Callable[[], bool], _progress: Callable[[str], None]) -> Any:
            return revalidate(action_id, self._context(inputs), services)

        def route(result: Any) -> None:
            if result is None:
                message = (
                    "Evidence changed since this suggestion. Refresh What Should I Test Next?."
                )
                if self._next_dialog is not None and self._next_dialog.winfo_exists():
                    self._next_dialog.mark_stale(message)
                self.status.set(message)
                return
            self._route_next(route_for(result[0]), result[0].executable)

        self._work(check, route)

    def _route_next(self, route: Any, executable: bool) -> None:
        """Open the existing operator workflow only. No setting changes and no job admission here."""
        if route.workflow == WORKFLOW_IDENTITY_VERIFICATION:
            # The step is "verify this file": do it, for the selected checkpoint only (hash, persist; no generation).
            if self._paths.get((self._selected() or {}).get("relative", "")) is not None:
                self._verify_selected()
            else:
                self.status.set(
                    route.guidance
                    or "Run Scan & Verify Library to identify this checkpoint's file."
                )
        elif route.workflow == WORKFLOW_CATALOG_RESEARCH:
            self.status.set(
                "Use More… > Look up selected model on Civitai, or import a reviewed catalog. "
                "Lookups ask before sending anything."
            )
        elif route.workflow == WORKFLOW_PROPOSED_EXPERIMENTS and executable:
            self._plan()
        elif route.workflow == WORKFLOW_DRAFT_PREPARATION and executable:
            self.owner._on_open_experiment_library()
            self.status.set(
                "Open the saved draft in the Experiment Library; Run stays an explicit step."
            )
        elif route.workflow == WORKFLOW_LEARNING_REVIEW and executable:
            identity = route.target_id

            def loaded(payload: Any) -> None:
                if payload and self.owner._restore_from_store_payload(
                    payload, experiment_id=identity
                ):
                    self.status.set("Opened the experiment in Learning. Rate or inspect it there.")
                else:
                    self.status.set("That saved experiment could not be opened.")

            self._work(lambda _c, _p: self.owner.experiment_store.load_session(identity), loaded)
        elif route.workflow == WORKFLOW_RECOMMENDATION_APPLY and executable:
            panel = getattr(self.owner, "review_panel", None)
            if panel is not None:
                panel.show_recommendations()
            self.status.set(
                "Recommendations are shown in Learning. Apply still asks for your confirmation."
            )
        else:
            self.status.set(route.guidance or "Nothing can be opened for this suggestion.")

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
            scope=SCOPE_LIBRARY,
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
            scope=SCOPE_LIBRARY,
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
                scope=SCOPE_LIBRARY,
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
                scope=SCOPE_LIBRARY,
            )

        self._work(
            lambda _cancelled, _p: service.saved_prompt_context(ids),
            context_ready,
            scope=SCOPE_LIBRARY,
        )

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
        self._keep_in_front(window)
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

        self._work(research, self._show, scope=SCOPE_LIBRARY)

    def _research(self) -> None:
        row = self._selected()
        if row and row.get("sha256") and row["identity_status"] == "verified":
            self._lookup_source(Lookup("civitai", row["sha256"]))
        else:
            self.status.set(
                "Verify the selected checkpoint (Verify Selected) before a hash lookup."
            )

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

        self._work(load, loaded, scope=SCOPE_LIBRARY)

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

        self._work(inspect, self._show, scope=SCOPE_LIBRARY)

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
                scope=SCOPE_LIBRARY,
            )


def open_model_evidence(owner: Any) -> ModelEvidenceWindow:
    """One catalog window per owner: a second request brings the open window forward with its state intact."""
    existing = getattr(owner, "_model_evidence_window", None)
    if isinstance(existing, ModelEvidenceWindow) and not existing._closed:
        try:
            if existing.winfo_exists():
                existing.bring_to_front()
                return existing
        except tk.TclError:
            pass
    window = ModelEvidenceWindow(owner)
    try:
        owner._model_evidence_window = window
    except AttributeError:
        pass
    return window
