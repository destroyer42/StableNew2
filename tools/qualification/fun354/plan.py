"""The frozen Fun Control 5B qualification plan (proposal only; physical execution is NOT authorized).

The plan pins exact asset hashes, the immutable graph digest, the runtime commit, the driving/reference inputs, three phases
(Q0 offline readiness, Q1 smallest legal generation, Q2 product envelope) and every stop condition.  Any change to any of them
changes ``digest``, so an authorization for one plan can never be reused for another.  Thresholds below are proposals: the owner
may change them before authorizing, which mints a new digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_catalog_fun_control import FUN_ASSETS, FUN_ID, FUN_REVISION
from src.video.workflow_frame_count import frame_count_policy, legal_frame_counts

SCHEMA = "stablenew.fun-control-qualification-plan.v1"
WORKFLOW_VERSION = "1.0.0"
#: PR-VID-MOTION-430: the owner-authorized experimental trial (the identical graph under an enforced VRAM floor).  A plan for
#: it is a separate proposal with its own digest; the 1.0.0 plan and its recorded evidence are read exactly as before.
TRIAL_VERSION = "1.1.0"
#: The ``resource_readiness.qualification_status`` each plannable version must still declare.
EXPECTED_STATUS = {WORKFLOW_VERSION: "not_qualified", TRIAL_VERSION: "trial_unqualified"}
RUNTIME_COMMIT = "6b747c0428c343e1417219641db93a4fb7cb69ae"  # managed ComfyUI v0.38.0 (VID-FUN-352)
REQUIRED_LAUNCH_FLAGS = ("--disable-pinned-memory", "--disable-auto-launch")
BASELINE_WORKFLOW = ("wan22_ti2v_5b_i2v_v1", "1.3.0")
SEEDS = (424242, 424243)
GEOMETRY = (480, 832)  # portrait; the product's source-aware default
OUTPUT_RESERVE_BYTES = 2 * 1024**3

PHASE_Q0, PHASE_Q1, PHASE_Q1C, PHASE_Q2 = "Q0", "Q1", "Q1C", "Q2"
PROMPT = (
    "A full-body woman in navy athletic clothing moves naturally. Static camera, continuous natural movement, "
    "same person and clothing, softly lit abstract background."
)
ROLE_DRIVING, ROLE_Q2_DRIVING, ROLE_REFERENCE = "driving_clip", "q2_driving_clip", "reference_image"
CASE_Q1 = "q1_forward_walk_17_s424242"
CASE_Q2_A = "q2_forward_walk_49_s424242"
CASE_Q2_B = "q2_forward_walk_49_s424243"
CASE_Q2_CANCEL = "q2_cancel_release_49"

STOP_DEVICE_LOSS = "device_loss"
STOP_ALLOCATION = "allocation_failure"
STOP_COMMIT = "host_commit_pressure"
STOP_LOW_RAM = "low_available_ram"
STOP_IDENTITY = "identity_mismatch"
STOP_TIMEOUT = "timeout"
STOP_TEARDOWN = "unsafe_teardown"
STOP_TELEMETRY = "telemetry_gap"
STOP_OPERATOR = "operator_cancel"

#: Stops that, with complete telemetry and verified identity, are a definitive resource refusal of the tested envelope.
RESOURCE_STOPS = frozenset({STOP_DEVICE_LOSS, STOP_ALLOCATION, STOP_COMMIT, STOP_LOW_RAM})


@dataclass(frozen=True)
class AssetPin:
    name: str
    folder: str
    size: int
    sha256: str


@dataclass(frozen=True)
class InputPin:
    role: str
    sha256: str  # "" when the owner has not chosen the file yet (Q0 then blocks)
    size: int = 0


@dataclass(frozen=True)
class CoverageEntry:
    """One driving clip of the source-type coverage phase (Q1C): which kind of source motion it stands for."""

    role: str
    source_type: str
    label: str


@dataclass(frozen=True)
class StopCondition:
    code: str
    trigger: str
    threshold: str
    action: str


@dataclass(frozen=True)
class CasePlan:
    case_id: str
    frames: int
    seed: int
    purpose: str
    cancel_after_seconds: int = 0
    driving_role: str = "driving_clip"


@dataclass(frozen=True)
class PhasePlan:
    phase_id: str
    purpose: str
    physical: bool
    wall_limit_seconds: int
    requires: tuple[str, ...]
    cases: tuple[CasePlan, ...] = ()


@dataclass(frozen=True)
class QualificationPlan:
    workflow_id: str
    workflow_version: str
    graph_sha256: str
    runtime_commit: str
    launch_flags: tuple[str, ...]
    assets: tuple[AssetPin, ...]
    inputs: tuple[InputPin, ...]
    width: int
    height: int
    fps: int
    phases: tuple[PhasePlan, ...]
    stops: tuple[StopCondition, ...]
    telemetry: tuple[str, ...]
    baseline: tuple[str, str]
    prompt: str = ""
    negative_prompt: str = ""
    coverage: tuple[CoverageEntry, ...] = ()
    #: Trial plans only: the exact resource policy the catalog entry carries (``None`` keeps a 1.0.0 record, and its digest,
    #: byte-for-byte what it always was).
    resource_policy: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "workflow": {
                "id": self.workflow_id,
                "version": self.workflow_version,
                "graph_sha256": self.graph_sha256,
            },
            "runtime": {"commit": self.runtime_commit, "launch_flags": list(self.launch_flags)},
            "assets": [asdict(a) for a in self.assets],
            "inputs": [asdict(i) for i in self.inputs],
            "geometry": {"width": self.width, "height": self.height, "fps": self.fps},
            "phases": [asdict(p) for p in self.phases],
            "stops": [asdict(s) for s in self.stops],
            "telemetry": list(self.telemetry),
            "baseline": list(self.baseline),
            "request": {"prompt": self.prompt, "negative_prompt": self.negative_prompt},
            "coverage": [asdict(c) for c in self.coverage],
            "physical_execution": "NOT AUTHORIZED",
            "frozen_catalog_entry": "unchanged; qualification never edits the immutable 1.0.0 spec",
        } | self._candidate_record()

    def _candidate_record(self) -> dict[str, Any]:
        if self.resource_policy is None:
            return {}
        policy_blob = json.dumps(self.resource_policy, sort_keys=True, separators=(",", ":"))
        return {
            "frozen_catalog_entry": (
                f"unchanged; qualification never edits a published spec (1.0.0 stays blocked, "
                f"{self.workflow_version} stays the owner-authorized trial)"
            ),
            "candidate": {
                "workflow_version": self.workflow_version,
                "resource_policy": dict(self.resource_policy),
                "resource_policy_sha256": hashlib.sha256(policy_blob.encode("ascii")).hexdigest(),
                "policy_status": (
                    "provisional floors taken from the TI2V-5B figures; this plan measures them, it does not "
                    "change them, and a changed policy is a new plan and an owner decision"
                ),
                "preparation": [
                    "driving clips are Prepare Motion Source derivatives: exact frames at 24 FPS for the case length",
                    "MP4 drivers are pre-scaled to the plan geometry before pinning; Canny runs at the prepared size "
                    "and 4K drivers failed (memory, time-out) in VID-MOTION-354 runs 1 and 2",
                    "one concrete seed per case; per-job experimental consent is recorded by the app, not by this harness",
                ],
                "evidence_scope": [
                    "VID-MOTION-354 run 3 (14 cases FEASIBLE) is historical technical feasibility on 1.0.0's graph; it "
                    "is not a qualification of 1.1.0, of its resource policy or of the application path",
                    "a verdict from this plan is feasibility under this plan only; qualification needs the owner-accepted "
                    "ledger entry",
                ],
                "telemetry_not_captured": [
                    "cold-start and generation durations separately (only wall time per case is recorded)",
                    "Comfy allocator state",
                    "driver recovery beyond the Windows event-log fault scan",
                ],
            },
        }

    @property
    def digest(self) -> str:
        blob = json.dumps(
            self.to_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(blob.encode("ascii")).hexdigest()

    def phase(self, phase_id: str) -> PhasePlan:
        return next(p for p in self.phases if p.phase_id == phase_id)

    @property
    def physical_cases(self) -> tuple[CasePlan, ...]:
        return tuple(c for p in self.phases if p.physical for c in p.cases)


class PlanError(ValueError):
    pass


def fun_control_spec(version: str = WORKFLOW_VERSION) -> Any:
    for spec in build_builtin_workflow_specs():
        if spec.workflow_id == FUN_ID and spec.workflow_version == version:
            return spec
    raise PlanError(f"The Fun Control {version} catalog entry is not registered.")


STOPS = (
    StopCondition(
        STOP_DEVICE_LOSS,
        "Driver reports device lost / CUDA error / device-side assert",
        "any",
        "stop; no GPU recovery",
    ),
    StopCondition(
        STOP_ALLOCATION,
        "Comfy or the host reports an out-of-memory / allocation / commit failure",
        "any",
        "stop; no retry",
    ),
    StopCondition(
        STOP_COMMIT,
        "Host commit charge reaches this fraction of the commit limit",
        ">= 0.95",
        "stop the owned runtime cleanly",
    ),
    StopCondition(
        STOP_LOW_RAM,
        "Available host RAM stays below this for 10 consecutive seconds",
        "< 1024 MiB",
        "stop the owned runtime cleanly",
    ),
    StopCondition(
        STOP_IDENTITY,
        "Runtime commit, graph digest, model/input hash or launch flags differ from the plan",
        "any",
        "stop before dispatch",
    ),
    StopCondition(
        STOP_TIMEOUT,
        "A case exceeds its phase wall-clock limit",
        "per phase",
        "cancel through the existing owner path",
    ),
    StopCondition(
        STOP_TEARDOWN,
        "An owned process or VRAM allocation remains after the 60 s grace period",
        "60 s",
        "stop; report; never kill an unowned process",
    ),
    StopCondition(
        STOP_TELEMETRY,
        "The telemetry sampler is silent for more than 5 s",
        "5 s",
        "stop; verdict cannot be better than INCONCLUSIVE",
    ),
    StopCondition(STOP_OPERATOR, "The operator cancels", "any", "stop; verdict INCONCLUSIVE"),
)

TELEMETRY = (
    "host_commit_fraction_peak",
    "host_available_ram_min_mib",
    "gpu_vram_peak_mib",
    "device_loss_events",
    "wall_seconds",
    "frames_delivered",
    "teardown_clean",
    "runtime_identity",
    "owner_visual_rating_via_vid_quality_351",
)
#: Trial plans add what the executor really records: decimal GPU temperature and the minimum VRAM headroom.
TRIAL_TELEMETRY = (*TELEMETRY, "gpu_temperature_peak_c", "gpu_vram_headroom_min_mib")


def build_plan(
    *,
    driving_clip_sha256: str = "",
    driving_clip_size: int = 0,
    reference_sha256: str = "",
    reference_size: int = 0,
    extra_inputs: Sequence[InputPin] = (),
    coverage: Sequence[CoverageEntry] = (),
    workflow_version: str = WORKFLOW_VERSION,
) -> QualificationPlan:
    """Freeze the proposal from the catalog.  Raises ``PlanError`` if the catalog no longer matches what was reviewed."""

    if workflow_version not in EXPECTED_STATUS:
        raise PlanError(f"No qualification plan is written for Fun Control {workflow_version}.")
    spec = (
        fun_control_spec()
        if workflow_version == WORKFLOW_VERSION
        else fun_control_spec(workflow_version)
    )
    provenance = spec.backend_defaults.get("provenance") or {}
    integrity = spec.backend_defaults.get("asset_integrity") or {}
    readiness = spec.backend_defaults.get("resource_readiness") or {}
    expected = EXPECTED_STATUS[workflow_version]
    if readiness.get("qualification_status") != expected:
        raise PlanError(
            f"The catalog entry is no longer marked {expected}; this proposal was written for that policy."
        )
    trial = workflow_version != WORKFLOW_VERSION
    if integrity.get("revision") != FUN_REVISION:
        raise PlanError("The pinned upstream revision changed.")
    policy = frame_count_policy(spec)
    legal = legal_frame_counts(spec)
    if policy is None or 17 not in legal or 49 not in legal:
        raise PlanError("Fun Control no longer accepts 17 and 49 frames.")
    graph = str(provenance.get("qualified_graph_sha256") or "")
    if len(graph) != 64:
        raise PlanError("The catalog does not record a graph digest.")

    q1 = CasePlan(
        CASE_Q1, 17, SEEDS[0], "Smallest legal generation: does the allocation complete at all"
    )
    q2_role = (
        ROLE_Q2_DRIVING if any(i.role == ROLE_Q2_DRIVING for i in extra_inputs) else ROLE_DRIVING
    )
    q2 = (
        CasePlan(
            CASE_Q2_A, 49, SEEDS[0], "Product-envelope length, first seed", driving_role=q2_role
        ),
        CasePlan(
            CASE_Q2_B,
            49,
            SEEDS[1],
            "Product-envelope length, second seed (repeatability)",
            driving_role=q2_role,
        ),
        CasePlan(
            CASE_Q2_CANCEL,
            49,
            SEEDS[0],
            "Cancel mid-generation; owned runtime and VRAM must release",
            cancel_after_seconds=20,
            driving_role=q2_role,
        ),
    )
    q1c = tuple(
        CasePlan(
            f"q1c_{entry.role}",
            17,
            SEEDS[0],
            f"{entry.source_type}: {entry.label}",
            driving_role=entry.role,
        )
        for entry in coverage
    )
    phases = (
        PhasePlan(
            PHASE_Q0,
            "Offline readiness: pinned weights, inputs, runtime identity and host facts; no GPU, no runtime",
            False,
            0,
            (),
        ),
        PhasePlan(
            PHASE_Q1,
            "One minimal physical generation with full telemetry",
            True,
            900,
            (PHASE_Q0,),
            (q1,),
        ),
        *(
            (
                PhasePlan(
                    PHASE_Q1C,
                    "Source-type coverage at the smallest legal length: each kind of source motion, 2-3 clips",
                    True,
                    900,
                    (PHASE_Q0, PHASE_Q1),
                    q1c,
                ),
            )
            if q1c
            else ()
        ),
        PhasePlan(
            PHASE_Q2,
            "Envelope length, repeatability and cancellation/release",
            True,
            1800,
            (PHASE_Q0, PHASE_Q1),
            q2,
        ),
    )
    return QualificationPlan(
        workflow_id=FUN_ID,
        workflow_version=workflow_version,
        graph_sha256=graph,
        runtime_commit=RUNTIME_COMMIT,
        launch_flags=REQUIRED_LAUNCH_FLAGS,
        assets=tuple(
            AssetPin(name, a["folder"], int(a["size"]), a["sha256"])
            for name, a in FUN_ASSETS.items()
        ),
        inputs=(
            InputPin(ROLE_DRIVING, driving_clip_sha256, driving_clip_size),
            InputPin(ROLE_REFERENCE, reference_sha256, reference_size),
            *extra_inputs,
        ),
        width=GEOMETRY[0],
        height=GEOMETRY[1],
        fps=int(policy["fps"]),
        phases=phases,
        stops=STOPS,
        telemetry=TRIAL_TELEMETRY if trial else TELEMETRY,
        baseline=BASELINE_WORKFLOW,
        prompt=PROMPT,
        negative_prompt=str(spec.backend_defaults.get("default_negative_prompt") or ""),
        coverage=tuple(coverage),
        resource_policy=dict(readiness) if trial else None,
    )
