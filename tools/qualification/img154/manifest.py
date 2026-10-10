"""D1: the frozen, versioned, PROPOSED exact-candidate and intent manifest (data only; never applied to any runtime).

Facts are the PR-IMG-MODELS-153 candidate facts (exact bytes and full SHA-256 of the three named files and the managed Forge
pin). They identify the qualification candidate and are independent of the git commit this package is built on. A manifest is a
plan: it is never evidence of applied settings, loaded runtime state, official provenance or safety.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .core import Finding, digest, is_hex_digest

MANIFEST_SCHEMA = "stablenew.img154.manifest.v1"
POLICY_REVISION = "img154b-preflight-policy-r1"
STOP_POLICY_REVISION = "img154a-stop-policy-r1"
EVIDENCE_CONTRACT_REVISION = "img154b-evidence-contract-r1"
OPERATOR_PREFLIGHT_REVISION = "img154a-operator-preflight-r1"

FORGE_PIN = "d70373ebcf1a96d210b78cd6f77196459e783e2a"
FORGE_MARKER_STATUS_OK = "verified"

#: Intent fields whose pinned-API meaning is NOT reconciled. PR-IMG-MODELS-154A left all three open (the model card says
#: guidance 0.0, the pinned UI preset says CFG 1.0 / shift 9.0). PR-IMG-MODELS-154B reconciled them against the pinned source
#: (``tools/qualification/img154b/request.py``): the sampling VALUES are unchanged, only their API encoding is (CFG 1.0 is the
#: pinned no-guidance setting; shift travels as ``distilled_cfg_scale``; ``scheduler`` is a request key whose Beta parameters
#: are server options). The anchors are re-verified against the managed source at preflight, so this stays an empty tuple only
#: while that verification holds.
UNRECONCILED_INTENT_FIELDS: tuple[str, ...] = ()

SEMANTICS_STATUS_RECONCILED = "reconciled_pinned_forge_source"


@dataclass(frozen=True)
class AssetSpec:
    role: str
    filename: str
    size_bytes: int
    sha256: str
    models_subdir: str  # directory below the served ``forge-data/models`` root


#: Exact installed candidate. Provenance of all three files is UNVERIFIED (no official hash was available offline); these
#: are qualification candidates, not authenticated official weights.
FROZEN_ASSETS: Mapping[str, AssetSpec] = {
    "transformer": AssetSpec(
        "transformer",
        "zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors",
        6_158_115_074,
        "59610861d46ae8d5d1d371ab7b2532ce64c0835052b395551a8550fa0e3eb3cf",
        "Stable-diffusion",
    ),
    "text_encoder": AssetSpec(
        "text_encoder",
        "qwen3_4b_2964436.safetensors",
        8_044_982_048,
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        "text_encoder",
    ),
    "vae": AssetSpec(
        "vae",
        "flux1AE_v10.safetensors",
        335_304_388,
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        "VAE",
    ),
}

#: Request keys a one-case qualification request must never carry (no extras, scripts, references, upscale or hires).
FORBIDDEN_REQUEST_KEYS = (
    "alwayson_scripts",
    "script_name",
    "script_args",
    "enable_hr",
    "hr_scale",
    "hr_upscaler",
    "hr_second_pass_steps",
    "init_images",
    "mask",
    "override_settings",
    "refiner_checkpoint",
    "lora",
    "loras",
    "embedding",
    "reference_images",
    "adetailer",
    "retry",
    "replay",
)


@dataclass(frozen=True)
class FrozenIntent:
    """One txt2img, one image. The sampling values are frozen; their API encoding is reconciled in PR-154B."""

    workflow: str = "txt2img"
    width: int = 1024
    height: int = 1024
    batch_size: int = 1
    n_iter: int = 1
    seed: int = 424254
    steps: int = 9
    sampler: str = "Euler"
    scheduler: str = "Beta"
    cfg_scale: float = 1.0
    shift: float = 9.0
    negative_prompt: str = ""
    prompt: str = (
        "A ceramic teapot on a wooden table beside a window, soft daylight, studio photograph."
    )
    automatic_retry: bool = False
    automatic_replay: bool = False
    semantics_status: str = SEMANTICS_STATUS_RECONCILED

    def request_fields(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "width": self.width,
            "height": self.height,
            "batch_size": self.batch_size,
            "n_iter": self.n_iter,
            "seed": self.seed,
            "steps": self.steps,
            "sampler_name": self.sampler,
            "scheduler": self.scheduler,
            "cfg_scale": self.cfg_scale,
            "shift": self.shift,
            "negative_prompt": self.negative_prompt,
            "prompt": self.prompt,
        }


#: Planned (not implemented) telemetry fields a future harness must record; documentation of the contract only.
PLANNED_TELEMETRY_FIELDS = (
    "monotonic_s",
    "utc",
    "vram_used_bytes",
    "vram_total_bytes",
    "vram_free_bytes",
    "shared_vram_bytes",
    "gpu_utilization_percent",
    "gpu_temperature_c",
    "gpu_board_power_w",
    "commit_total_bytes",
    "commit_limit_bytes",
    "commit_headroom_bytes",
    "ram_available_bytes",
    "pagefile_status",
    "hard_fault_pages_input_per_s",
    "forge_tree_working_set_bytes",
    "forge_tree_private_commit_bytes",
    "owned_pids",
    "endpoint_status",
    "stage",
    "stage_source",
)


@dataclass(frozen=True)
class QualificationManifest:
    case_id: str = "img154-zimage-turbo-owner-case-1"
    assets: Mapping[str, AssetSpec] = field(default_factory=lambda: dict(FROZEN_ASSETS))
    forge_pin: str = FORGE_PIN
    intent: FrozenIntent = field(default_factory=FrozenIntent)
    policy_revision: str = POLICY_REVISION
    stop_policy_revision: str = STOP_POLICY_REVISION
    evidence_contract_revision: str = EVIDENCE_CONTRACT_REVISION
    operator_preflight_revision: str = OPERATOR_PREFLIGHT_REVISION

    def attempt_identity(self) -> str:
        """Owner-authorized case identity, unaffected by request or policy edits.

        Changing a case ID requires a genuinely distinct owner-authorized case, never a retry.
        Full request, asset and policy provenance remain in the append-only attempt record.
        """
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("owner-authorized case identity is required")
        return digest({"namespace": "stablenew.img154.attempt.v1", "case_id": self.case_id})

    def served_relative_paths(self) -> dict[str, str]:
        """Where each file would be SERVED under an isolated ``forge-data`` directory (posix-style, relative)."""

        return {
            role: posixpath.join("forge-data", "models", spec.models_subdir, spec.filename)
            for role, spec in self.assets.items()
        }

    def request_digest(self) -> str:
        return digest(self.intent.request_fields())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "case_id": self.case_id,
            "attempt_identity": self.attempt_identity(),
            "status": "PROPOSED_NOT_APPLIED",
            "assets": {
                role: {
                    "filename": spec.filename,
                    "size_bytes": spec.size_bytes,
                    "sha256": spec.sha256,
                    "models_subdir": spec.models_subdir,
                    "provenance": "unverified_third_party_candidate",
                }
                for role, spec in sorted(self.assets.items())
            },
            "served_relative_paths": dict(sorted(self.served_relative_paths().items())),
            "forge_pin": self.forge_pin,
            "intent": self.intent.request_fields(),
            "intent_semantics_status": self.intent.semantics_status,
            "unreconciled_intent_fields": list(UNRECONCILED_INTENT_FIELDS),
            "forbidden_request_keys": list(FORBIDDEN_REQUEST_KEYS),
            "policy_revision": self.policy_revision,
            "stop_policy_revision": self.stop_policy_revision,
            "evidence_contract_revision": self.evidence_contract_revision,
            "operator_preflight_revision": self.operator_preflight_revision,
            "planned_telemetry_fields": list(PLANNED_TELEMETRY_FIELDS),
            "request_digest": self.request_digest(),
        }

    def digest(self) -> str:
        return digest(self.as_dict())


def build_manifest() -> QualificationManifest:
    """Deterministic and independent of the git commit, the working tree and the host."""

    return QualificationManifest()


# --------------------------------------------------------------------------------------- measured file facts


@dataclass(frozen=True)
class FileMeasurement:
    """Bytes actually measured for one file. ``sha256`` is ``None`` when it was not (yet) hashed: that is NOT a match."""

    name: str
    size_bytes: int | None
    sha256: str | None
    path: str | None = None


def verify_assets(
    measured: Mapping[str, FileMeasurement | None], manifest: QualificationManifest | None = None
) -> list[Finding]:
    """Exact filename, byte size and full SHA-256 for each frozen role; any gap fails closed.

    Detects missing roles, unexpected roles, wrong filename, size or digest mismatch, unhashed files, malformed digests and
    one file (digest) standing in for two roles.
    """

    plan = manifest or build_manifest()
    findings: list[Finding] = []
    for role in measured:
        if role not in plan.assets:
            findings.append(Finding("ASSET_ROLE_UNEXPECTED", "refuse", f"unexpected role {role!r}"))
    seen_digests: dict[str, str] = {}
    for role, spec in plan.assets.items():
        item = measured.get(role)
        if item is None:
            findings.append(Finding("ASSET_MISSING", "refuse", f"{role}: not present"))
            continue
        if is_hex_digest(item.sha256):
            if item.sha256 in seen_digests:
                findings.append(
                    Finding(
                        "ASSET_ROLE_COLLISION",
                        "refuse",
                        f"{role} and {seen_digests[item.sha256]} are the same bytes",
                    )
                )
            seen_digests[item.sha256] = role
        if item.name != spec.filename:
            findings.append(
                Finding(
                    "ASSET_NAME_MISMATCH",
                    "refuse",
                    f"{role}: {item.name!r} is not {spec.filename!r}",
                )
            )
            continue
        if item.size_bytes != spec.size_bytes:
            findings.append(
                Finding(
                    "ASSET_SIZE_MISMATCH",
                    "refuse",
                    f"{role}: {item.size_bytes} bytes, frozen {spec.size_bytes}",
                )
            )
            continue
        if item.sha256 is None:
            findings.append(
                Finding("ASSET_NOT_HASHED", "inconclusive", f"{role}: SHA-256 not measured")
            )
            continue
        if not is_hex_digest(item.sha256):
            findings.append(
                Finding(
                    "ASSET_DIGEST_MALFORMED", "refuse", f"{role}: digest is not 64 lowercase hex"
                )
            )
            continue
        if item.sha256 != spec.sha256:
            findings.append(
                Finding(
                    "ASSET_SHA256_MISMATCH",
                    "refuse",
                    f"{role}: digest differs from the frozen value",
                )
            )
            continue
    return findings


def verify_served_files(
    served: Mapping[str, FileMeasurement | None],
    *,
    models_root: str,
    manifest: QualificationManifest | None = None,
) -> list[Finding]:
    """Proof about the files Forge would actually load: each served path must be measured on its own.

    A match of a SOURCE/download file never substitutes: the served entry needs its own size and SHA-256, at exactly
    ``<models_root>/<subdir>/<filename>``. A same-name file at a different path, or with different bytes, is refused.
    """

    plan = manifest or build_manifest()
    findings = verify_assets(served, plan)
    root = models_root.replace("\\", "/").rstrip("/")
    for role, spec in plan.assets.items():
        item = served.get(role)
        if item is None:
            continue
        expected = f"{root}/{spec.models_subdir}/{spec.filename}"
        actual = (item.path or "").replace("\\", "/")
        if actual != expected:
            findings.append(
                Finding(
                    "SERVED_PATH_MISMATCH",
                    "refuse",
                    f"{role}: measured file is not at the expected served path",
                )
            )
    return findings


def verify_runtime_pin(
    marker_revision: str | None,
    marker_status: str | None,
    config_revision: str | None,
    manifest: QualificationManifest | None = None,
) -> list[Finding]:
    plan = manifest or build_manifest()
    findings: list[Finding] = []
    if config_revision != plan.forge_pin:
        findings.append(
            Finding(
                "PIN_CONFIG_MISMATCH",
                "refuse",
                "managed Forge config revision is not the frozen pin",
            )
        )
    if marker_revision is None or marker_status is None:
        findings.append(
            Finding("PIN_MARKER_UNKNOWN", "inconclusive", "managed runtime marker was not read")
        )
    elif marker_revision != plan.forge_pin or marker_status != FORGE_MARKER_STATUS_OK:
        findings.append(
            Finding(
                "PIN_MARKER_MISMATCH",
                "refuse",
                "managed runtime marker is not the verified frozen pin",
            )
        )
    return findings


def verify_intent(
    presented_fields: Mapping[str, Any] | None, manifest: QualificationManifest | None = None
) -> list[Finding]:
    """The frozen request, bit-for-bit: any altered, added or forbidden field blocks the packet."""

    plan = manifest or build_manifest()
    if presented_fields is None:
        return [Finding("INTENT_NOT_PRESENTED", "inconclusive", "no frozen request was presented")]
    findings: list[Finding] = []
    for key in presented_fields:
        if key in FORBIDDEN_REQUEST_KEYS:
            findings.append(
                Finding(
                    "INTENT_FORBIDDEN_FIELD", "refuse", f"request carries forbidden field {key!r}"
                )
            )
    try:
        presented_digest = digest(dict(presented_fields))
    except (TypeError, ValueError):
        findings.append(
            Finding("INTENT_NOT_CANONICAL", "refuse", "presented request is not canonical JSON")
        )
        return findings
    if presented_digest != plan.request_digest():
        findings.append(
            Finding("INTENT_DRIFT", "refuse", "presented request differs from the frozen intent")
        )
    return findings
