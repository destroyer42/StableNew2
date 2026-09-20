"""Reference operator journey: Learning -> Designed Experiments -> LoRA Strength.

Learning tab -> Build Preview Only -> Run Experiment -> real queue/SQLite ->
PipelineRunner -> A1111 -> artifacts/manifests -> Learning Review -> ratings.

Every input goes through actual Tk widgets.  Controllers, JobService, the runner
and the backend are only *observed*.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import tkinter as tk
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk
from typing import Any

from src.learning.lora_variant import extract_lora_tokens
from src.learning.recommendation_engine import RecommendationEngine
from tools.operator_journey.capture import FaultCapture, leaked_non_daemon_threads, thread_snapshot
from tools.operator_journey.evidence import JourneyEvidence
from tools.operator_journey.fake_a1111 import FakeA1111
from tools.operator_journey.observe import (
    SubmissionObserver,
    find_artifacts,
    job_lifecycle_settled,
    read_job_rows,
    read_manifest,
    read_rating_records,
)
from tools.operator_journey.owned import OwnedResources
from tools.operator_journey.preflight import BackendInfo, fetch_progress, probe_backend
from tools.operator_journey.tk_driver import ActionTrace, JourneyTimeout, TkDriver, WidgetNotFound
from tools.operator_journey.workspace import (
    REPO_ROOT,
    AccessSpy,
    OperatorWorkspace,
    UserDataGuard,
    archive_workspace,
    repo_sha,
)

JOURNEY_ID = "learning-lora-strength"
DEFAULT_LORA = "add-detail-xl"
PHASES = (
    "preflight",
    "configure",
    "build_preview",
    "run",
    "verify_execution",
    "review_rating",
    "shutdown",
)
_BASE_PROMPT = "operator journey test, portrait of a warrior, studio lighting"
_STRENGTHS = (0.0, 1.0, 2.0)
_RATINGS = (3, 4, 5)


class JourneyAbort(RuntimeError):
    """The journey cannot continue; the message is the failed assertion."""


class JourneyHold(RuntimeError):
    """A prerequisite is unmet (not a product failure)."""


@dataclass
class JourneyConfig:
    backend: str = "fake"
    lora_name: str = DEFAULT_LORA
    seed: int = 12345
    timeout: float | None = None
    evidence_root: Path = REPO_ROOT / "reports" / "operator_journeys"
    webui_url: str | None = None
    stop_after: str | None = None  # test hook: last phase to execute
    discard_workspace: bool = False
    steps: int = 8
    width: int = 512
    height: int = 512
    show_window: bool = True
    fake_options: dict[str, Any] = field(default_factory=dict)
    # How long to wait for StableNew to connect to WebUI (its normal startup takes
    # ~15-30 s) before the projection is considered unavailable.
    startup_wait: float | None = None
    # Real mode keeps production timing (None); fake mode skips the probe grace.
    startup_grace_sec: float | None = None

    @property
    def run_timeout(self) -> float:
        return self.timeout or (900.0 if self.backend == "real" else 120.0)

    @property
    def connect_timeout(self) -> float:
        return self.startup_wait or (120.0 if self.backend == "real" else 45.0)

    @property
    def grace_sec(self) -> float | None:
        if self.startup_grace_sec is not None:
            return self.startup_grace_sec
        return 0.0 if self.backend == "fake" else None


def _resolve_webui_url(config: JourneyConfig) -> str:
    if config.webui_url:
        return config.webui_url
    settings = REPO_ROOT / "presets" / "settings.json"  # read-only
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        if data.get("webui_base_url"):
            return str(data["webui_base_url"])
    except (OSError, ValueError):
        pass
    return os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")


def _create_root() -> tk.Tk:
    import sys

    if sys.platform.startswith("win"):
        base = os.path.dirname(os.path.abspath(tk.__file__))
        for name, sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
            candidate = os.path.join(base, "tcl", sub)
            if os.path.isdir(candidate):
                os.environ.setdefault(name, candidate)
    return tk.Tk()


_HASH_SUFFIX = re.compile(r"\s*\[[0-9a-fA-F]+\]\s*$")


def model_base(name: Any) -> str:
    """A checkpoint's comparable name: A1111 titles carry a trailing ``[hash]``."""

    return _HASH_SUFFIX.sub("", str(name or "")).strip().casefold()


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _weight_of(value: Any) -> float | None:
    try:
        return float(value["weight"])
    except (KeyError, TypeError, ValueError):
        return None


class _Journey:
    """One execution of the reference journey against a live Tk application."""

    def __init__(
        self,
        config: JourneyConfig,
        evidence: JourneyEvidence,
        workspace: OperatorWorkspace,
        fake: FakeA1111 | None,
        backend_info: BackendInfo,
    ) -> None:
        self.config = config
        self.ev = evidence
        self.ws = workspace
        self.fake = fake
        self.backend_info = backend_info
        self.trace = ActionTrace()
        self.prompt = f"{_BASE_PROMPT} <lora:{config.lora_name}:0.8>"
        self.submissions = SubmissionObserver()
        self.rows: list[dict[str, Any]] = []
        self.variants_by_weight: dict[float, Any] = {}

    # -- plumbing -------------------------------------------------------
    def check(self, phase: str, name: str, passed: bool, detail: str = "") -> bool:
        return self.ev.check(phase, name, passed, "" if passed else detail)

    def require(self, phase: str, name: str, passed: bool, detail: str = "") -> None:
        if not self.check(phase, name, passed, detail):
            raise JourneyAbort(f"{phase}/{name}: {detail}")

    def stop_here(self, phase: str) -> bool:
        return self.config.stop_after == phase

    def checkpoint(self, label: str) -> None:
        self.ev.thread_checkpoints.append(thread_snapshot(label))

    # -- the journey ----------------------------------------------------
    def run(self) -> None:
        from src.app_factory import build_v2_app

        baseline_threads = {t.name for t in __import__("threading").enumerate()}
        root = _create_root()
        if not self.config.show_window:
            root.withdraw()
        self.driver = TkDriver(root, self.trace)
        with FaultCapture(root) as faults:
            try:
                _, app_state, controller, window = build_v2_app(
                    root=root,
                    webui_manager=None,  # external A1111 is never adopted or managed
                    threaded=True,
                    config_manager=self.ws.config_manager(),
                )
                self.app_state, self.controller, self.window = app_state, controller, window
                self.driver.pump(0.5)
                self.checkpoint("app_started")
                self._preflight()
                if not self.stop_here("preflight"):
                    self._configure()
                if not self.stop_here("preflight") and not self.stop_here("configure"):
                    self._build_preview()
                if self.config.stop_after not in {"preflight", "configure", "build_preview"}:
                    self._run_experiment()
                    self._verify_execution()
                    if self.config.stop_after != "verify_execution":
                        self._review_and_rate()
            except (JourneyHold, JourneyAbort, JourneyTimeout, WidgetNotFound) as exc:
                if isinstance(exc, JourneyHold):
                    self.ev.hold_reason = str(exc)
                else:
                    self.ev.abort_reason = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # unexpected harness/product failure
                self.ev.abort_reason = f"unexpected {type(exc).__name__}: {exc}"
            finally:
                self._shutdown(faults, baseline_threads)
        self.ev.shutdown_noise = list(faults.shutdown_noise)
        self.ev.gui_errors.extend(faults.tk_errors)
        self.ev.thread_errors.extend([*faults.thread_errors, *faults.main_errors])
        self.ev.log_errors.extend(faults.error_logs())
        self.ev.action_trace = list(self.trace.entries)

    # -- phase: preflight -----------------------------------------------
    def _preflight(self) -> None:
        ph = "preflight"
        self.submissions.install(self.controller.job_service)
        self._await_webui_connection()
        card = self.window.pipeline_tab.stage_cards_panel.txt2img_card
        self.check(ph, "resource_projection_models", True)
        if self.config.backend == "real":
            self._match_active_model(card)
        self.ev.summary["model"] = str(card.model_var.get())
        self.ev.summary["lora"] = self.config.lora_name

    def _await_webui_connection(self) -> None:
        """Wait, as an operator would, for StableNew to connect to WebUI.

        StableNew suppresses resource probes during its startup grace and needs
        ~15-30 s to connect.  The operator clicks Refresh until the normal
        resource projection lists an image model, then lets it settle.
        """

        d = self.driver
        refresh = self.window.header_zone.refresh_button
        last_click = float("-inf")

        def projected() -> bool:
            nonlocal last_click
            if time.monotonic() - last_click >= 5.0:
                d.invoke(refresh, label="header Refresh")
                last_click = time.monotonic()
            return len(self.controller.state.resources.get("models", [])) > 0

        try:
            d.wait_until(
                projected,
                timeout=self.config.connect_timeout,
                description="StableNew connects to WebUI and projects at least one image model",
                evidence=lambda: {k: len(v) for k, v in self.controller.state.resources.items()},
            )
        except JourneyTimeout as exc:
            raise JourneyHold(f"no usable image model after resource refresh ({exc})") from exc
        d.pump(1.0)  # let dependent GUI projections (stage-card dropdowns) settle

    def _await_backend_idle(self) -> None:
        """Never queue behind (or interrupt) foreign work: wait for A1111 to be idle."""

        if self.config.backend != "real":
            return
        url = self.backend_info.base_url

        def idle() -> bool:
            progress = fetch_progress(url)
            return progress is not None and not progress.get("state", {}).get("job_count")

        self.driver.wait_until(
            idle,
            timeout=120,
            description="A1111 reports no active generation before Run Experiment",
            evidence=lambda: fetch_progress(url),
            poll=1.0,
        )

    def _match_active_model(self, card: Any) -> None:
        """Use the model A1111 already has loaded; never switch the operator's checkpoint."""

        active = self.backend_info.active_checkpoint
        if not active:
            raise JourneyHold(
                "A1111 reports no active checkpoint; the journey will not pick a model "
                "that could switch it"
            )
        if model_base(card.model_var.get()) == model_base(active):
            return
        combo = self.driver.find(
            self.window.pipeline_tab, ttk.Combobox, textvariable=card.model_var
        )
        for value in [str(v) for v in combo.cget("values")]:
            if model_base(value) == model_base(active):
                self.driver.select_combobox(combo, value, label="txt2img model")  # type: ignore[arg-type]
                return
        raise JourneyHold(
            f"A1111's active model {active!r} is not selectable in StableNew's model list; "
            "the journey will not switch the operator's checkpoint"
        )

    # -- phase: configure -----------------------------------------------
    def _set_toggle(self, parent: tk.Misc, text: str, wanted: bool) -> None:
        button = self.driver.find(parent, (ttk.Checkbutton, tk.Checkbutton), text=text)
        variable = str(button.cget("variable"))
        current = bool(int(self.driver.root.getvar(variable)))
        if current != wanted:
            self.driver.invoke(button, label=f"toggle {text}")

    def _configure(self) -> None:
        ph = "configure"
        d = self.driver
        window = self.window
        d.select_tab(window.center_notebook, "Pipeline")
        pipeline = window.pipeline_tab
        for text, wanted in (
            ("Enable txt2img", True),
            ("Enable img2img", False),
            ("Enable ADetailer", False),
            ("Enable upscale", False),
        ):
            self._set_toggle(pipeline, text, wanted)
        card = pipeline.stage_cards_panel.txt2img_card
        d.set_variable(card.steps_var, self.config.steps, label="txt2img steps")
        d.set_variable(card.width_var, self.config.width, label="txt2img width")
        d.set_variable(card.height_var, self.config.height, label="txt2img height")
        d.set_variable(card.seed_var, str(self.config.seed), label="txt2img seed")
        # Global prompt intent is run intent; keep the reference run neutral.
        sidebar = window.sidebar_panel_v2
        if bool(sidebar.global_positive_enabled_var.get()):
            self._set_toggle(sidebar, "Enable Global Positive", False)
        applied = card.to_config_dict().get("txt2img", {})
        self.require(
            ph,
            "baseline_from_gui",
            applied.get("seed") == self.config.seed
            and applied.get("steps") == self.config.steps
            and applied.get("width") == self.config.width,
            f"stage-card config did not reflect GUI input: {applied}",
        )
        # The LoRA selector reads LoRAs from the current Prompt workspace, so the
        # operator authors the prompt there and reuses it as the custom prompt.
        d.select_tab(window.center_notebook, "Prompt")
        d.type_in_text(window.prompt_tab.editor, self.prompt, label="Prompt tab editor")

        d.select_tab(window.center_notebook, "Learning - Adv")
        learning = window.learning_tab
        d.select_tab(learning._mode_notebook, "Designed Experiments")
        panel = learning.experiment_panel
        d.select_combobox(panel.stage_combo, "txt2img", label="target stage")
        d.select_combobox(panel.prompt_source_combo, "custom", label="prompt source")
        d.type_in_text(panel.custom_prompt_text, self.prompt, label="custom prompt")
        d.select_combobox(panel.variable_combo, "LoRA Strength", label="variable under test")
        lora_combo = d.find(panel.lora_frame, ttk.Combobox, textvariable=panel.lora_selector_var)
        try:
            d.select_combobox(lora_combo, self.config.lora_name, label="LoRA to test")  # type: ignore[arg-type]
        except WidgetNotFound as exc:
            self.require(ph, "lora_selectable", False, str(exc))
        d.set_variable(panel.lora_start_var, 0.0, label="strength start")
        d.set_variable(panel.lora_end_var, 2.0, label="strength end")
        d.set_variable(panel.lora_step_var, 1.0, label="strength step")
        d.set_variable(panel.images_var, 1, label="images per variant")
        self.check(ph, "gui_configured", True)
        self.checkpoint("configured")

    # -- phase: build preview ---------------------------------------------
    def _build_preview(self) -> None:
        ph = "build_preview"
        d = self.driver
        learning = self.window.learning_tab
        panel = learning.experiment_panel
        d.invoke(panel.build_button, label="Build Preview Only")
        state = learning.learning_controller.learning_state
        d.wait_until(
            lambda: len(state.plan) > 0
            or panel.feedback_var.get().startswith(("Validation", "Error")),
            timeout=30,
            description="Build Preview Only produces a plan",
            evidence=lambda: panel.feedback_var.get(),
        )
        self.require(
            ph,
            "preview_built",
            len(state.plan) == 3,
            f"{len(state.plan)} variants; {panel.feedback_var.get()!r}",
        )
        weights = [_weight_of(v.param_value) for v in state.plan]
        self.check(ph, "three_lora_weights", weights == list(_STRENGTHS), f"weights={weights}")
        self.check(
            ph,
            "plan_table_rows",
            len(learning.plan_table.tree.get_children()) == 3,
            "plan table does not show 3 rows",
        )
        experiment = state.current_experiment
        snapshot = json.loads(getattr(experiment, "execution_snapshot_json", "") or "{}")
        policy = snapshot.get("seed_policy") or {}
        self.check(
            ph,
            "frozen_seed_policy",
            policy.get("requested_base_seed") == self.config.seed
            and policy.get("requested_sample_count") == 1,
            f"seed policy={policy}",
        )
        self.ev.summary["experiment_id"] = experiment.experiment_id
        self.ev.summary["requested_seed"] = self.config.seed
        self.ev.summary["requested_values"] = [_canon(v.param_value) for v in state.plan]
        self.state = state
        self.checkpoint("preview_built")

    # -- phase: run -----------------------------------------------------
    def _run_experiment(self) -> None:
        ph = "run"
        d = self.driver
        panel = self.window.learning_tab.experiment_panel
        repository = Path(self.controller._job_repository_path)
        self.repository_path = repository
        self._await_backend_idle()
        d.invoke(panel.run_button, label="Run Experiment")
        self.require(
            ph, "run_accepted", "Error" not in panel.feedback_var.get(), panel.feedback_var.get()
        )

        def probe() -> bool:
            self.rows = read_job_rows(repository, self.ws.root)
            return job_lifecycle_settled(self.rows, len(self.state.plan)) and all(
                v.status in {"completed", "failed", "uncontrolled"} for v in self.state.plan
            )

        d.wait_until(
            probe,
            timeout=self.config.run_timeout,
            description="all experiment jobs reach a terminal state",
            evidence=lambda: [
                (r["variant_index"], r["status"]) for r in read_job_rows(repository, self.ws.root)
            ],
        )
        d.pump(2.0)  # settle: a duplicate/retry would appear as extra work here
        self.rows = read_job_rows(repository, self.ws.root)
        self.checkpoint("jobs_terminal")

    # -- phase: verify --------------------------------------------------
    def _verify_execution(self) -> None:
        ph = "verify_execution"
        rows, plan = self.rows, list(self.state.plan)
        seed = self.config.seed
        lora = self.config.lora_name
        calls = self.submissions.calls
        self.check(
            ph,
            "single_batch_admission",
            len(calls) == 1 and len(calls[0]) == 3,
            f"submit_njrs calls={calls}",
        )
        self.check(
            ph,
            "admitted_jobs_match_repository",
            sorted(calls[0] if calls else []) == sorted(r["job_id"] for r in rows),
            "admitted NJR ids differ from SQLite jobs",
        )
        self.check(
            ph,
            "three_independent_jobs",
            len(rows) == 3 and len({r["job_id"] for r in rows}) == 3,
            f"{len(rows)} rows",
        )
        self.check(
            ph,
            "all_jobs_completed",
            all(r["status"] == "completed" for r in rows),
            str([r["status"] for r in rows]),
        )
        self.check(
            ph,
            "no_retry_or_replay",
            all(r["retry_attempts"] == 0 and not r["return_to_queue_count"] for r in rows)
            and len(rows) == 3,
            "retry/requeue evidence present",
        )
        experiment_id = self.ev.summary.get("experiment_id", "")
        self.check(
            ph,
            "learning_lineage",
            all(str(r["learning_context"].get("experiment_id", "")) == experiment_id for r in rows),
            "job rows do not carry the experiment id",
        )
        images, manifests = find_artifacts(rows)
        self.check(
            ph,
            "three_image_artifacts",
            len(images) == 3 and all(p.exists() for p in images),
            f"images={images}",
        )
        self.check(
            ph,
            "three_manifests",
            len(manifests) == 3 and all(p.exists() for p in manifests),
            f"manifests={manifests}",
        )
        parents = {p.parent.resolve() for p in images}
        self.check(
            ph,
            "one_experiment_output_group",
            len(parents) == 1 and experiment_id[:8] in next(iter(parents)).name
            if parents
            else False,
            f"output groups={sorted(str(p) for p in parents)}",
        )
        profiles: set[str] = set()
        by_job = {r["job_id"]: r for r in rows}
        for variant in plan:
            weight = _weight_of(variant.param_value)
            row = by_job.get(variant.job_id, {})
            manifest_path = next(
                (
                    m
                    for m in manifests
                    if row
                    and any(str(m) == ref or Path(ref) == m for ref in row["artifact_references"])
                ),
                None,
            )
            manifest = (
                read_manifest(manifest_path) if manifest_path and manifest_path.exists() else {}
            )
            executed = str(
                manifest.get("final_prompt")
                or variant.execution_metadata.get("executed_final_prompt")
                or ""
            )
            tokens = [
                (n, w) for n, w in extract_lora_tokens(executed) if n.casefold() == lora.casefold()
            ]
            expected = [] if weight == 0.0 else [str(weight)]
            self.check(
                ph,
                f"executed_lora_tokens[{weight}]",
                [w for _, w in tokens] == expected,
                f"executed prompt selected-LoRA tokens={tokens} expected={expected} prompt={executed!r}",
            )
            self.check(
                ph,
                f"no_stale_baseline_token[{weight}]",
                weight == 0.8 or f"{lora}:0.8" not in executed,
                f"stale baseline token in {executed!r}",
            )
            njr_tokens = [
                w
                for n, w in extract_lora_tokens(row.get("njr_positive_prompt", ""))
                if n.casefold() == lora.casefold()
            ]
            self.check(
                ph,
                f"njr_matches_execution[{weight}]",
                njr_tokens == expected,
                f"NJR tokens={njr_tokens}",
            )
            others = Counter(
                (n.casefold(), w)
                for n, w in extract_lora_tokens(executed)
                if n.casefold() != lora.casefold()
            )
            self.check(
                ph,
                f"unrelated_loras_unchanged[{weight}]",
                not others,
                f"unexpected LoRA tokens {dict(others)}",
            )
            self.check(
                ph,
                f"manifest_seed[{weight}]",
                manifest.get("requested_seed") == seed and manifest.get("all_seeds") == [seed],
                f"requested={manifest.get('requested_seed')} all_seeds={manifest.get('all_seeds')}",
            )
            meta = dict(variant.execution_metadata or {})
            self.check(
                ph,
                f"controlled_evidence[{weight}]",
                meta.get("controlled_evidence_valid") is True
                and meta.get("seed_validation_reason") == "valid"
                and meta.get("variable_validation_reason") == "valid",
                f"status={variant.status} meta={ {k: meta.get(k) for k in ('controlled_evidence_valid', 'seed_validation_reason', 'variable_validation_reason')} }",
            )
            profile = str(meta.get("runtime_launch_profile") or "")
            if profile:
                profiles.add(profile)
            self.ev.variants.append(
                {
                    "value": _canon(variant.param_value),
                    "job_id": variant.job_id,
                    "job_status": row.get("status"),
                    "variant_status": variant.status,
                    "requested_seed": seed,
                    "actual_all_seeds": meta.get("actual_all_seeds"),
                    "executed_final_prompt": executed,
                    "njr_positive_prompt": row.get("njr_positive_prompt"),
                    "selected_lora_tokens": [w for _, w in tokens],
                    "controlled_evidence_valid": meta.get("controlled_evidence_valid"),
                    "seed_validation_reason": meta.get("seed_validation_reason"),
                    "variable_validation_reason": meta.get("variable_validation_reason"),
                    "runtime_launch_profile": profile,
                    "artifact": next(
                        (
                            str(p)
                            for p in images
                            if p.parent and row and str(p) in row["artifact_references"]
                        ),
                        "",
                    ),
                    "manifest": str(manifest_path) if manifest_path else "",
                }
            )
            self.variants_by_weight[weight if weight is not None else -1.0] = variant
        self.check(
            ph,
            "no_backend_restart_boundary",
            len(profiles) <= 1,
            f"launch profiles seen={sorted(profiles)}",
        )
        if self.fake is not None:
            payloads = self.fake.txt2img_payloads
            self.check(
                ph,
                "backend_received_three_generations",
                len(payloads) == 3,
                f"{len(payloads)} txt2img POSTs",
            )
            self.check(
                ph,
                "backend_seed_sent",
                all(p.get("seed") == seed for p in payloads),
                str([p.get("seed") for p in payloads]),
            )
            self.check(
                ph,
                "backend_endpoints_all_handled",
                not self.fake.unhandled,
                str(self.fake.unhandled),
            )
        # Learning Review projects every completed variant (workspace list).
        review = self.window.learning_tab.review_panel
        tree = self.window.learning_tab.plan_table.tree
        kids = tree.get_children()
        if kids:
            tree.selection_set(kids[0])
            tree.event_generate("<<TreeviewSelect>>")
            self.driver.pump(0.5)
        self.check(
            ph,
            "review_projects_all_variants",
            review.variant_summary_list.size() == 3,
            f"review workspace lists {review.variant_summary_list.size()} variants",
        )
        self.ev.summary["artifact_group"] = str(next(iter(parents))) if parents else ""
        self.checkpoint("verified")

    # -- phase: review & ratings ---------------------------------------------
    def _review_and_rate(self) -> None:
        ph = "review_rating"
        d = self.driver
        learning = self.window.learning_tab
        review = learning.review_panel
        tree = learning.plan_table.tree
        feedback: list[str] = []
        for index, rating in enumerate(_RATINGS):
            kids = tree.get_children()
            tree.selection_set(kids[index])
            tree.event_generate("<<TreeviewSelect>>")
            d.pump(0.4)
            d.wait_until(
                lambda: review.image_listbox.size() >= 1,
                timeout=15,
                description=f"review shows the images of variant {index}",
            )
            d.select_listbox_row(review.image_listbox, 0, label="review image list")
            d.invoke(review.rating_buttons[rating - 1], label=f"rating {rating}")
            d.invoke(review.rate_button, label="Save Rating")
            feedback.append(str(review.feedback_label.cget("text")))
        errors = [f for f in feedback if f.startswith("Error")]
        self.check(ph, "gui_rating_feedback", not errors, f"Save Rating feedback: {errors}")
        records = read_rating_records(self.ws.records_path)
        self.check(
            ph,
            "ratings_persisted_isolated",
            len(records) == 3,
            f"{len(records)} rating records in isolated store",
        )
        by_weight = {_weight_of((r["metadata"] or {}).get("variant_value")): r for r in records}
        for weight, rating in zip(_STRENGTHS, _RATINGS, strict=True):
            record = by_weight.get(weight)
            metadata = (record or {}).get("metadata") or {}
            variant = self.variants_by_weight.get(weight)
            frozen = metadata.get("frozen_experiment") or {}
            self.check(
                ph,
                f"rating_lineage[{weight}]",
                record is not None
                and metadata.get("user_rating_raw") == rating
                and metadata.get("experiment_id") == self.ev.summary.get("experiment_id")
                and metadata.get("job_id") == getattr(variant, "job_id", None)
                and Path(str(metadata.get("image_path"))).exists()
                and metadata.get("variable_under_test") == "LoRA Strength"
                and frozen.get("controlled_evidence_valid") is True
                and frozen.get("variable_validation_reason") == "valid",
                f"record={ {k: metadata.get(k) for k in ('experiment_id', 'job_id', 'image_path', 'user_rating_raw', 'variable_under_test')} }",
            )
        contexts = {
            _canon(
                {
                    k: (dict(v.executed_config).get("txt2img") or {}).get(k)
                    for k in (
                        "model",
                        "steps",
                        "cfg_scale",
                        "sampler_name",
                        "scheduler",
                        "vae",
                        "seed",
                    )
                }
            )
            for v in self.state.plan
        }
        self.check(
            ph,
            "only_lora_strength_varies",
            len(contexts) == 1,
            f"fixed context differs across variants: {sorted(contexts)}",
        )
        conclusion = learning.learning_controller.get_experiment_conclusion()
        self.check(
            ph,
            "conclusion_scoped_to_lora_strength",
            conclusion.get("controlled_valid") is True
            and conclusion.get("sufficient_evidence") is True
            and _weight_of(conclusion.get("best_value")) == _STRENGTHS[-1]
            and {_weight_of(row["value"]) for row in conclusion.get("values", [])}
            == set(_STRENGTHS),
            f"conclusion={conclusion.get('message')} best={conclusion.get('best_value')}",
        )
        # Recommendations: shown by the GUI and computed by the production engine
        # over the isolated records.  Only the tested variable may be recommended.
        shown = str(review.recommendations_text.get("1.0", "end"))
        shown_params = re.findall(r"^([a-z_]+): ", shown, flags=re.MULTILINE)
        best = {"name": self.config.lora_name, "weight": _STRENGTHS[-1]}
        self.check(
            ph,
            "gui_recommendations_only_lora_strength",
            shown_params == ["lora_strength"] and self.config.lora_name in shown,
            f"review panel recommendation parameters={shown_params} text={shown[:300]!r}",
        )
        engine_set = RecommendationEngine(self.ws.records_path).recommend(self.prompt, "txt2img")
        engine_params = {r.parameter_name: r.recommended_value for r in engine_set.recommendations}
        self.check(
            ph,
            "engine_recommends_structured_lora_value_only",
            engine_params == {"lora_strength": best},
            f"engine recommendations={engine_params}",
        )
        self.checkpoint("rated")

    # -- shutdown ---------------------------------------------------------
    def _shutdown(self, faults: FaultCapture, baseline_threads: set[str]) -> None:
        ph = "shutdown"
        d = self.driver
        root = d.root
        try:
            self.submissions.uninstall()
        except Exception:
            pass
        try:
            self.checkpoint("before_shutdown")
            faults.begin_shutdown()
            d.close_via_window_manager()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    root.update()
                    root.winfo_exists()  # raises once the application is destroyed
                except tk.TclError:
                    break
                time.sleep(0.02)
            else:
                self.check(
                    ph,
                    "graceful_close",
                    False,
                    "Tk root still alive 15s after close "
                    f"(close_in_progress={getattr(self.window, '_close_in_progress', '?')}, "
                    f"disposed={getattr(self.window, '_disposed', '?')})",
                )
        except tk.TclError:
            pass  # already destroyed
        deadline = time.monotonic() + 10
        leaked: list[str] = leaked_non_daemon_threads(baseline_threads)
        while leaked and time.monotonic() < deadline:
            time.sleep(0.1)
            leaked = leaked_non_daemon_threads(baseline_threads)
        self.check(ph, "no_leaked_threads", not leaked, f"non-daemon threads still alive: {leaked}")
        self.ev.thread_checkpoints.append(thread_snapshot("after_shutdown"))
        _ = faults


def run_journey(config: JourneyConfig) -> JourneyEvidence:
    """Execute the reference journey and return its evidence (also written to disk)."""

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path(config.evidence_root) / f"{stamp}_{JOURNEY_ID}_{config.backend}"
    evidence = JourneyEvidence(journey_id=JOURNEY_ID, backend_mode=config.backend)
    evidence.repository_sha = repo_sha()
    evidence.started_at = evidence.now()
    evidence.summary["evidence_dir"] = str(run_dir)
    guard = UserDataGuard()
    guard.capture()
    fake: FakeA1111 | None = None
    owned = OwnedResources()
    try:
        if config.backend == "fake":
            fake = FakeA1111(loras=(config.lora_name,), **config.fake_options)
            fake.start()
            owned.register("fake-a1111", fake.stop)
            url = fake.base_url
            # No HTTP probe: it would start the fake's warm-up clock before StableNew does.
            info = BackendInfo(
                base_url=url,
                reachable=True,
                models=list(fake.model_names),
                loras=list(fake.loras),
                active_checkpoint=fake.title(fake.model),
                version="operator-journey-fake",
            )
        else:
            url = _resolve_webui_url(config)
            info = probe_backend(url)
            if not info.reachable:
                raise JourneyHold(f"A1111 is not reachable at {url}: {info.error}")
            if not info.models:
                raise JourneyHold(f"A1111 at {url} reports no image models")
            if config.lora_name not in info.loras:
                raise JourneyHold(
                    f"LoRA {config.lora_name!r} is not installed in A1111 "
                    f"({len(info.loras)} LoRAs available)"
                )
        evidence.summary["backend"] = info.as_dict()
        # A short root keeps Learning artifact paths under the Windows MAX_PATH limit.
        workspace = OperatorWorkspace(
            root=Path(tempfile.mkdtemp(prefix="opj_")),
            webui_base_url=url,
            startup_grace_sec=config.grace_sec,
        )
        evidence.summary["workspace"] = str(workspace.root)
        spy = AccessSpy(allowed=(workspace.root,))
        with workspace.activate(), spy:
            _Journey(config, evidence, workspace, fake, info).run()
        after = probe_backend(url)
        evidence.summary["active_checkpoint_before"] = info.active_checkpoint
        evidence.summary["active_checkpoint_after"] = after.active_checkpoint
        evidence.check(
            "shutdown",
            "backend_active_model_unchanged",
            model_base(after.active_checkpoint) == model_base(info.active_checkpoint),
            f"the journey changed the backend's active checkpoint from "
            f"{info.active_checkpoint!r} to {after.active_checkpoint!r}",
        )
        evidence.isolation_violations.extend(spy.violations())
        evidence.summary["operator_output_files_read_by_app_scan"] = len(set(spy.read_outputs))
        archive_workspace(workspace, evidence, run_dir, discard=config.discard_workspace)
    except JourneyHold as exc:
        evidence.hold_reason = str(exc)
    except Exception as exc:
        evidence.abort_reason = f"harness error {type(exc).__name__}: {exc}"
    finally:
        if fake is not None:
            evidence.summary["backend_requests_rejected_while_starting"] = (
                fake.rejected_while_starting
            )
        owned.cleanup()
        evidence.isolation_violations.extend(guard.violations())
        evidence.completed_at = evidence.now()
        evidence.write(run_dir)
    return evidence
