"""The bounded physical comparison protocol: stages, limits, stop rules, preconditions and the authorization binding.

Pure data and pure checks. Nothing here executes a runtime. Historical Forge evidence can support a capability
comparison, but matched physical performance comparison requires a separately approved contemporary Forge baseline.

Every numeric limit below is PROPOSED. It is part of the digest the owner binds an authorization to, so changing any
value invalidates an existing authorization; the owner reviews them by authorizing (or not) a specific digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .comfy_graphs import build_graph, graph_digest, required_models
from .spec import K1, K2, K3, PACKAGE_ID, S1, S2, S3, Workload, digest, spec_digest

PROTOCOL_REVISION = "1"
QUAL_COMFY_PORT = (
    8196  # outside 7860-7899 (WebUI family, prior qualifications) and the Comfy default 8188
)
RISK_ID = "DIAG-GPU-130"
MAX_AUTH_VALIDITY = timedelta(hours=24)
ACTION = "comfy_still_image_qualification_stage"

GPU_TOTAL_MIB = 12_282  # RTX 4070 Ti, the qualified card (config/managed_forge_runtime.json)


@dataclass(frozen=True)
class Limits:
    max_generation_requests: int
    retries: int
    case_wall_seconds: int
    stage_wall_seconds: int
    startup_seconds: int


@dataclass(frozen=True)
class StopRules:
    vram_stop_mib: int  # whole-GPU used
    temp_stop_c: int
    ram_floor_gb: float  # available host RAM
    ram_floor_samples: int  # consecutive samples below the floor
    sample_interval_s: float
    stderr_markers: tuple[str, ...]


@dataclass(frozen=True)
class Preconditions:
    total_ram_gb_min: float
    available_ram_gb_min: float
    gpu_vram_used_mib_max: int
    gpu_temp_c_max: int
    require_clean_repository: bool = True
    require_free_qualification_port: bool = True
    require_exact_models: bool = True


@dataclass(frozen=True)
class Case:
    case_id: str
    workload_id: str
    role: str  # cold | warm | switch | first
    graph_sha256: str
    models: tuple[tuple[str, str], ...]  # (folder, file name)


@dataclass(frozen=True)
class Stage:
    stage_id: str
    purpose: str
    cases: tuple[Case, ...]
    limits: Limits
    preconditions: Preconditions

    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases)


STOP_RULES = StopRules(
    vram_stop_mib=GPU_TOTAL_MIB - 300,
    temp_stop_c=84,
    ram_floor_gb=0.5,
    ram_floor_samples=5,
    sample_interval_s=0.5,
    stderr_markers=(
        "out of memory",
        "cuda error",
        "device-side assert",
        "illegal memory access",
        "device lost",
    ),
)

#: Stage 1/2 (SDXL): Comfy start ~1.9 GB + a 6.9 GB checkpoint. Stage 3 (Klein): 12.4 GB of weights; the Forge Klein run
#: reached 26.3 GiB of private memory on this 34 GB host, so a larger headroom is required before anything is loaded.
_SDXL_PRE = Preconditions(
    total_ram_gb_min=32.0, available_ram_gb_min=18.0, gpu_vram_used_mib_max=3_000, gpu_temp_c_max=60
)
_KLEIN_PRE = Preconditions(
    total_ram_gb_min=32.0, available_ram_gb_min=24.0, gpu_vram_used_mib_max=3_000, gpu_temp_c_max=60
)


def _case(case_id: str, workload: Workload, role: str, filenames: Mapping[str, str]) -> Case:
    graph = build_graph(workload, prefix=f"qual100_{case_id.lower()}", filenames=filenames)
    models = tuple(
        (folder, name)
        for folder, names in sorted(required_models(graph).items())
        for name in sorted(set(names))
    )
    return Case(case_id, workload.workload_id, role, graph_digest(graph), models)


def build_stages(
    workloads: Mapping[str, Workload], *, filenames: Mapping[str, str]
) -> tuple[Stage, ...]:
    def c(case_id: str, wid: str, role: str) -> Case:
        return _case(case_id, workloads[wid], role, filenames)

    return (
        Stage(
            "stage1_sdxl",
            "SDXL baseline cold + warm latency and determinism, then the LoRA workload in the same warm process",
            (c("S1-cold", S1, "cold"), c("S1-warm", S1, "warm"), c("S3-lora", S3, "warm")),
            Limits(
                max_generation_requests=3,
                retries=0,
                case_wall_seconds=300,
                stage_wall_seconds=1_200,
                startup_seconds=120,
            ),
            _SDXL_PRE,
        ),
        Stage(
            "stage2_openpose",
            "SDXL with the pre-rendered OpenPose map (the PR-IMG-CNET-210 workload)",
            (c("S2-openpose", S2, "cold"),),
            Limits(
                max_generation_requests=1,
                retries=0,
                case_wall_seconds=300,
                stage_wall_seconds=900,
                startup_seconds=120,
            ),
            _SDXL_PRE,
        ),
        Stage(
            "stage3_klein",
            "Klein 4B FP8 text-to-image (cold load), a second 1024 text-to-image, then single-reference edit",
            (c("K1-first", K1, "cold"), c("K2-warm", K2, "warm"), c("K3-edit", K3, "warm")),
            Limits(
                max_generation_requests=3,
                retries=0,
                case_wall_seconds=600,
                stage_wall_seconds=2_100,
                startup_seconds=180,
            ),
            _KLEIN_PRE,
        ),
    )


EVIDENCE_PER_CASE = (
    "graph_sha256 and the exact request body hash",
    "client-chosen prompt_id and the server's accepted response",
    "/history/<prompt_id> record (status, outputs, durations)",
    "output file sha256, size, decoded dimensions and pixel statistics",
    "submit-to-completion wall time and process-start-to-ready time",
    "telemetry CSV (VRAM, temperature, power, clocks, available RAM) at the stop-rule interval",
    "stderr/stdout tail and any stop-rule marker hits",
    "model file identities (size + SHA-256) as served",
    "process tree before start, during, and after stop (survivor check)",
)


def build_protocol(
    workloads: Mapping[str, Workload], *, filenames: Mapping[str, str], comfy_revision: str
) -> dict[str, Any]:
    stages = build_stages(workloads, filenames=filenames)
    body: dict[str, Any] = {
        "package": PACKAGE_ID,
        "protocol_revision": PROTOCOL_REVISION,
        "spec_digest": spec_digest(dict(workloads)),
        "comfy_revision": comfy_revision,
        "qualification_port": QUAL_COMFY_PORT,
        "stop_rules": asdict(STOP_RULES),
        "stages": [asdict(stage) for stage in stages],
        "evidence_per_case": list(EVIDENCE_PER_CASE),
        "forge_leg": "reuse accepted evidence; no Forge generation is part of this protocol",
        "accepted_risk": RISK_ID,
    }
    for stage in body["stages"]:
        stage["stage_digest"] = digest(
            {
                "package": PACKAGE_ID,
                "protocol_revision": PROTOCOL_REVISION,
                "comfy_revision": comfy_revision,
                "stage": {k: v for k, v in stage.items() if k != "stage_digest"},
                "stop_rules": body["stop_rules"],
            }
        )
    body["protocol_digest"] = digest(body)
    return body


def stage_by_id(protocol: Mapping[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in protocol["stages"]:
        if stage["stage_id"] == stage_id:
            return dict(stage)
    raise KeyError(f"unknown stage {stage_id!r}")


# ---- pure checks -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    check: str
    ok: bool
    detail: str


def evaluate_preconditions(
    pre: Mapping[str, Any],
    *,
    host: Mapping[str, Any],
    repository_clean: bool,
    qualification_port_free: bool,
    models_exact: bool,
) -> list[Finding]:
    """One finding per precondition; the stage may start only when every finding is ``ok``."""

    gpu = host.get("gpu") or {}
    findings = [
        Finding(
            "gpu_fault_cleared",
            host.get("gpu_fault_active") is False,
            "explicit fault-clearance evidence required; current incident remains active",
        ),
        Finding(
            "total_ram",
            float(host.get("ram_total_gb", 0)) >= float(pre["total_ram_gb_min"]),
            f"{host.get('ram_total_gb')} GB (needs {pre['total_ram_gb_min']})",
        ),
        Finding(
            "available_ram",
            float(host.get("ram_available_gb", 0)) >= float(pre["available_ram_gb_min"]),
            f"{host.get('ram_available_gb')} GB (needs {pre['available_ram_gb_min']})",
        ),
        Finding(
            "gpu_present", bool(gpu), "nvidia-smi answered" if gpu else "no GPU telemetry; refuse"
        ),
    ]
    if gpu:
        findings += [
            Finding(
                "gpu_vram_idle",
                int(gpu.get("vram_used_mib", 10**9)) <= int(pre["gpu_vram_used_mib_max"]),
                f"{gpu.get('vram_used_mib')} MiB used (max {pre['gpu_vram_used_mib_max']})",
            ),
            Finding(
                "gpu_temp",
                int(gpu.get("temp_c", 10**3)) <= int(pre["gpu_temp_c_max"]),
                f"{gpu.get('temp_c')} C (max {pre['gpu_temp_c_max']})",
            ),
        ]
    if pre.get("require_clean_repository", True):
        findings.append(
            Finding("repository_clean", repository_clean, "tracked tree clean at the bound SHA")
        )
    if pre.get("require_free_qualification_port", True):
        findings.append(
            Finding("qualification_port_free", qualification_port_free, f"port {QUAL_COMFY_PORT}")
        )
    if pre.get("require_exact_models", True):
        findings.append(
            Finding("models_exact", models_exact, "every model file matches its frozen identity")
        )
    return findings


def preconditions_hold(findings: list[Finding]) -> bool:
    return bool(findings) and all(item.ok for item in findings)


def evaluate_sample(
    rules: Mapping[str, Any],
    *,
    vram_mib: int,
    temp_c: int,
    ram_available_gb: float,
    low_ram_streak: int,
) -> tuple[str | None, int]:
    """(stop_reason or None, new low-RAM streak) for one telemetry sample."""

    streak = low_ram_streak + 1 if ram_available_gb < float(rules["ram_floor_gb"]) else 0
    if vram_mib >= int(rules["vram_stop_mib"]):
        return f"vram {vram_mib} MiB >= {rules['vram_stop_mib']}", streak
    if temp_c >= int(rules["temp_stop_c"]):
        return f"temperature {temp_c} C >= {rules['temp_stop_c']}", streak
    if streak >= int(rules["ram_floor_samples"]):
        return f"available RAM < {rules['ram_floor_gb']} GB for {streak} samples", streak
    return None, streak


def stderr_marker(rules: Mapping[str, Any], lines: list[str]) -> str | None:
    for line in lines:
        lowered = line.lower()
        for marker in rules["stderr_markers"]:
            if marker in lowered:
                return str(marker)
    return None


class AuthorizationError(ValueError):
    """The owner authorization is absent, malformed, expired or not for this stage/digest/source."""


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    """Reject altered protocol/stage data; a matching stored digest alone is not validation."""
    body = {k: v for k, v in protocol.items() if k != "protocol_digest"}
    if protocol.get("protocol_digest") != digest(body):
        raise AuthorizationError("protocol digest mismatch")
    for stage in protocol.get("stages", ()):
        expected = digest(
            {
                "package": protocol["package"],
                "protocol_revision": protocol["protocol_revision"],
                "comfy_revision": protocol["comfy_revision"],
                "stage": {k: v for k, v in stage.items() if k != "stage_digest"},
                "stop_rules": protocol["stop_rules"],
            }
        )
        if stage.get("stage_digest") != expected:
            raise AuthorizationError("stage digest mismatch")


def verify_authorization(
    record: Mapping[str, Any],
    *,
    stage: Mapping[str, Any],
    protocol_digest: str,
    protocol: Mapping[str, Any],
    source_sha: str,
    now: datetime | None = None,
) -> None:
    """Raise unless ``record`` is a current owner authorization bound to exactly this stage, protocol and source.

    This is record-format validation, not proof of human approval or permission to execute. The calling future
    workflow must obtain explicit owner authorization separately. This package contains no execution driver.
    """

    moment = now or datetime.now(UTC)
    validate_protocol(protocol)
    if protocol_digest != protocol["protocol_digest"] or dict(stage) != stage_by_id(
        protocol, str(stage["stage_id"])
    ):
        raise AuthorizationError("stage or protocol binding mismatch")
    required = (
        "owner",
        "action",
        "stage_id",
        "stage_digest",
        "protocol_digest",
        "source_sha",
        "issued_at",
        "expires_at",
        "accepted_risk",
    )
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise AuthorizationError(f"authorization record is missing {missing}")
    expectations = {
        "owner": "Rob",
        "action": ACTION,
        "stage_id": stage["stage_id"],
        "stage_digest": stage["stage_digest"],
        "protocol_digest": protocol_digest,
        "source_sha": source_sha,
        "accepted_risk": RISK_ID,
    }
    for key, wanted in expectations.items():
        if record.get(key) != wanted:
            raise AuthorizationError(f"authorization {key} does not match this stage")
    try:
        issued = datetime.fromisoformat(str(record["issued_at"]))
        expires = datetime.fromisoformat(str(record["expires_at"]))
    except ValueError as exc:
        raise AuthorizationError("authorization timestamps are not ISO-8601") from exc
    if issued.tzinfo is None or expires.tzinfo is None:
        raise AuthorizationError("authorization timestamps must be timezone-aware")
    if issued > moment:
        raise AuthorizationError("authorization is not yet valid")
    if expires <= moment:
        raise AuthorizationError("authorization has expired")
    if expires - issued > MAX_AUTH_VALIDITY:
        raise AuthorizationError("authorization validity exceeds 24 hours")
