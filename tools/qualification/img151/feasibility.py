"""PR-IMG-MODELS-151, read-only feasibility phase: can the installed FLUX.2 Klein Base 9B BF16 candidate be qualified safely?

Qualification-only, never production code. It answers one question from evidence, without loading a model, launching or
restarting Forge, writing to any runtime, downloading, copying a weight or changing any setting:

    NO_GO_RESOURCE_RISK | NO_GO_PINNED_FORGE | MISSING_DEPENDENCY | IDENTITY_PENDING | INCONCLUSIVE |
    ELIGIBLE_FOR_OWNER_AUTHORIZATION

Everything is separated into *measured* (file sizes, structural headers, host telemetry), *documented* (the one prior
qualification baseline, PR-IMG-115), *estimated* (derived from measured/documented values) and *assumed* (stated policy
numbers). Anything not established stays unknown, and incomplete telemetry yields ``INCONCLUSIVE`` rather than a guess.
It reuses the PR-IMG-MODELS-150 structural evidence (``component_evidence``) and ``read_host_memory``.

Side effects are bounded by construction: the only subprocesses are the allow-listed read-only queries in
``READ_ONLY_COMMANDS``; the only network activity is an optional TCP connect (no HTTP) to the endpoint ports; the only
writes are the report file the caller names. Hashing (``--hash``) only reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.assets.component_evidence import ComponentEvidence, inspect_component_file  # noqa: E402
from src.image_backends.forge_klein_readiness import (  # noqa: E402
    HostMemorySnapshot,
    read_host_memory,
)

GIB = 1024**3
GB = 1_000_000_000

NO_GO_RESOURCE_RISK = "NO_GO_RESOURCE_RISK"
NO_GO_PINNED_FORGE = "NO_GO_PINNED_FORGE"
MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
IDENTITY_PENDING = "IDENTITY_PENDING"
INCONCLUSIVE = "INCONCLUSIVE"
ELIGIBLE = "ELIGIBLE_FOR_OWNER_AUTHORIZATION"
VERDICTS = (NO_GO_RESOURCE_RISK, NO_GO_PINNED_FORGE, MISSING_DEPENDENCY, IDENTITY_PENDING, INCONCLUSIVE, ELIGIBLE)

# Fact kinds: what a finding stands on.
MEASURED, DOCUMENTED, ESTIMATED, ASSUMED = "measured", "documented", "estimated", "assumed"

TRANSFORMER_NAME = "flux-2-klein-base-9b.safetensors"
ENCODER_NAME = "qwen_3_8b.safetensors"
VAE_NAME = "flux2-vae.safetensors"
PINNED_REVISION = "d70373ebcf1a96d210b78cd6f77196459e783e2a"

#: Allow-list of the only subprocesses this tool may start: argv heads plus a fixed argument shape. All are read-only
#: queries; nothing can start, stop, write to or configure anything.
READ_ONLY_COMMANDS: Mapping[str, tuple[str, ...]] = {
    "nvidia_smi": (
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,driver_version",
        "--format=csv,noheader,nounits",
    ),
    "pagefile": (
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage | ConvertTo-Json -Compress",
    ),
    "processes": (
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 Name,WorkingSet64 | ConvertTo-Json -Compress",
    ),
    "gpu_shared_memory": (
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "(Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage' -ErrorAction Stop).CounterSamples | "
        "Measure-Object CookedValue -Sum | Select-Object -ExpandProperty Sum",
    ),
}

#: Documented, owner-reviewed context about this workstation (never an attribution; see the cited records).
KNOWN_GPU_RISK_CONTEXT = {
    "source": "docs/Subsystems/Runtime/DIAG-GPU-130_Post_5600_Black_Screen_Recurrence.md",
    "status": "XMP-OFF RECURRENCE - ACTIVE OBSERVATION / EXIT CRITERION NOT MET",
    "summary": (
        "An unresolved display/live-kernel hard-failure family (black screen, WER 141/1B8, unexpected restart) has recurred "
        "on this workstation after GPU workloads. No component or workload is attributed; it is aggravating context for "
        "any heavy GPU/host-memory exposure."
    ),
}

#: The only physical baseline on this machine class (PR-IMG-115, Klein 4B FP8 + BF16 Qwen3-4B + VAE, pinned Forge).
IMG115_BASELINE = {
    "source": "docs/Subsystems/Image/PR-IMG-115_FLUX2_Klein_4B_FP8_Target_Hardware_Qualification.md",
    "weights_bytes": 12_451_817_860,
    "forge_tree_private_peak_gib": 26.3,
    "dedicated_vram_peak_mib": 9696,
    "min_host_ram_available_gb": 0.01,
    "steps": 4,
    "cfg": 1.0,
}


# ---------------------------------------------------------------------------------------------------- data model


@dataclass(frozen=True)
class CandidateFile:
    role: str
    name: str
    present: bool
    size_bytes: int | None = None
    evidence: ComponentEvidence | None = None
    sha256: str | None = None
    #: How the bytes relate to a recorded source (``same_file``/``same_size``/``unknown``); never "official".
    provenance: str = "unknown"

    def fact(self, key: str, default: Any = None) -> Any:
        return self.evidence.fact(key, default) if self.evidence else default


@dataclass(frozen=True)
class CandidateSet:
    transformer: CandidateFile
    text_encoder: CandidateFile
    vae: CandidateFile
    #: Other files that look interchangeable but are NOT (F16/quantized/4B encoders, other VAEs): never substituted.
    alternates: tuple[CandidateFile, ...] = ()
    source: Mapping[str, Any] = field(default_factory=dict)
    #: True only when a caller established byte equality with the official weights (hash comparison against an official
    #: record). Never inferred from a name, a size or a mirror's README; the offline collectors leave it False.
    official_identity_verified: bool = False


@dataclass(frozen=True)
class PinEvidence:
    expected_revision: str = PINNED_REVISION
    marker_revision: str | None = None
    marker_status: str | None = None
    source_scanned: bool = False
    supports_flux2_9b: bool | None = None
    supports_qwen3_8b: bool | None = None
    supported_dtypes: tuple[str, ...] = ()
    memory_usage_factor: float | None = None


@dataclass(frozen=True)
class HostTelemetry:
    total_ram_bytes: int | None = None
    available_ram_bytes: int | None = None
    commit_headroom_bytes: int | None = None
    pagefile_allocated_bytes: int | None = None
    vram_total_bytes: int | None = None
    vram_used_bytes: int | None = None
    vram_free_bytes: int | None = None
    gpu_name: str | None = None
    gpu_temperature_c: float | None = None
    shared_gpu_memory_bytes: int | None = None
    competing_processes: tuple[tuple[str, int], ...] = ()  # (name, working-set bytes); no paths, no command lines
    forge_endpoint_listening: bool | None = None
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assumptions:
    """Stated policy numbers (assumptions, not measurements); changing one changes the verdict transparently."""

    host_reserve_bytes: int = 4 * GIB  # OS + desktop + tools that must stay resident
    vram_activation_reserve_bytes: int = int(2.5 * GIB)  # latents/activations/VAE decode at 1024-class
    commit_margin: float = 0.8  # estimated peak may use at most this share of the commit headroom
    scaled_peak_factor: float = IMG115_BASELINE["forge_tree_private_peak_gib"] * GIB / IMG115_BASELINE["weights_bytes"]
    official_steps: int = 50  # official FLUX.2 Klein Base 9B reference settings (undistilled)
    official_cfg: float = 4.0


@dataclass(frozen=True)
class Finding:
    code: str
    kind: str  # measured / documented / estimated / assumed
    detail: str
    blocking: bool = False


@dataclass(frozen=True)
class FeasibilityReport:
    verdict: str
    findings: tuple[Finding, ...]
    next_recommendation: str
    measured: Mapping[str, Any]
    estimated: Mapping[str, Any]
    assumptions: Mapping[str, Any]
    candidate: Mapping[str, Any] = field(default_factory=dict)
    pin: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
            "findings": [asdict(item) for item in self.findings],
            "next_recommendation": self.next_recommendation,
            "measured": dict(self.measured),
            "estimated": dict(self.estimated),
            "assumptions": dict(self.assumptions),
            "candidate": dict(self.candidate),
            "pin": dict(self.pin),
            "context": dict(self.context),
        }


# ---------------------------------------------------------------------------------------------------- evaluator


def _gib(value: int | float | None) -> float | None:
    return None if value is None else round(float(value) / GIB, 2)


def evaluate(
    candidate: CandidateSet,
    pin: PinEvidence,
    telemetry: HostTelemetry,
    assumptions: Assumptions | None = None,
    *,
    expected_hidden_size: int = 4096,
) -> FeasibilityReport:
    """Pure verdict. Precedence: MISSING_DEPENDENCY > NO_GO_PINNED_FORGE > NO_GO_RESOURCE_RISK > INCONCLUSIVE >
    IDENTITY_PENDING > ELIGIBLE_FOR_OWNER_AUTHORIZATION. Non-blocking findings are always reported alongside."""

    policy = assumptions or Assumptions()
    findings: list[Finding] = []
    missing: list[Finding] = []
    nogo_pin: list[Finding] = []
    nogo_resource: list[Finding] = []
    inconclusive: list[Finding] = []
    identity: list[Finding] = []

    # -- 1. exact candidate files and structure (measured) -----------------------------------------------------------
    transformer, encoder, vae = candidate.transformer, candidate.text_encoder, candidate.vae
    for item in (transformer, encoder, vae):
        if not item.present:
            missing.append(Finding(f"{item.role.upper()}_FILE_MISSING", MEASURED, f"{item.name} is not installed.", True))
    if transformer.present:
        ev = transformer.evidence
        if ev is None or ev.error or not ev.dependency_bearing or ev.architecture != "flux2_dit":
            missing.append(Finding("TRANSFORMER_NOT_FLUX2_STRUCTURE", MEASURED,
                                   "The transformer header is not a FLUX.2 transformer-only signature.", True))
        elif (
            transformer.fact("hidden_size") != expected_hidden_size
            or transformer.fact("required_text_encoder_hidden_size") != expected_hidden_size
        ):
            missing.append(Finding("TRANSFORMER_NOT_9B_CLASS", MEASURED,
                                   f"Hidden size {transformer.fact('hidden_size')} is not the 9B class ({expected_hidden_size}).", True))
        elif transformer.fact("dtype") != "BF16":
            missing.append(Finding("TRANSFORMER_NOT_BF16", MEASURED,
                                   f"The transformer is stored as {transformer.fact('dtype')}, not the BF16 candidate.", True))
    if encoder.present:
        ev = encoder.evidence
        if ev is None or ev.error or ev.architecture != "qwen3":
            missing.append(Finding("ENCODER_NOT_QWEN3_STRUCTURE", MEASURED, "The encoder is not a Qwen3 text encoder.", True))
        elif encoder.fact("quantized"):
            missing.append(Finding("ENCODER_QUANTIZED", MEASURED, "A quantized encoder is not the plain BF16 candidate.", True))
        elif encoder.fact("hidden_size") != transformer.fact("required_text_encoder_hidden_size"):
            missing.append(Finding("ENCODER_HIDDEN_SIZE_MISMATCH", MEASURED,
                                   f"Encoder hidden size {encoder.fact('hidden_size')} != the {transformer.fact('required_text_encoder_hidden_size')} "
                                   "the transformer's header requires (a 4B-class encoder never substitutes for the 9B).", True))
        elif encoder.fact("dtype") != "BF16":
            missing.append(Finding("ENCODER_NOT_BF16", MEASURED,
                                   f"The named encoder is stored as {encoder.fact('dtype')}; an alternate file is never substituted.", True))
    if vae.present:
        ev = vae.evidence
        if ev is None or ev.error or ev.role != "vae":
            missing.append(Finding("VAE_NOT_RECOGNIZED", MEASURED, "The VAE header is not recognized.", True))
        elif vae.fact("latent_channels") != transformer.fact("required_vae_latent_channels"):
            missing.append(Finding("VAE_LATENT_CHANNEL_MISMATCH", MEASURED,
                                   f"VAE latent channels {vae.fact('latent_channels')} != required "
                                   f"{transformer.fact('required_vae_latent_channels')}.", True))
    if candidate.alternates:
        findings.append(Finding(
            "ALTERNATE_COMPONENT_FILES_PRESENT", MEASURED,
            "Other encoder/VAE files exist (" + ", ".join(sorted(f"{a.name}[{a.fact('dtype')}]" for a in candidate.alternates))
            + "). They are different assets (F16, quantized, 4B-class or a different key format) and are never substituted.",
        ))

    # -- 2. identity / provenance (measured vs unknown) --------------------------------------------------------------
    for item in (transformer, encoder, vae):
        if item.present and not item.sha256:
            identity.append(Finding(f"{item.role.upper()}_SHA256_PENDING", MEASURED,
                                    f"No byte identity (SHA-256) was computed for {item.name}.", True))
    matched = [i for i in (transformer, encoder, vae)
               if i.provenance in ("same_file_as_recorded_source", "same_bytes_as_recorded_source")]
    if matched:
        findings.append(Finding(
            "BYTES_MATCH_RECORDED_SOURCE_CACHE", MEASURED,
            "Byte equality (SHA-256) with the locally cached download was established for: "
            + ", ".join(i.name for i in matched) + ". That ties the installed files to what was downloaded, not to the "
            "official weights."))
    if not candidate.official_identity_verified:
        identity.append(Finding(
            "OFFICIAL_IDENTITY_UNVERIFIED", ASSUMED,
            "Equality with the official black-forest-labs weights is not established: the installed transformer is a "
            "single-file packaging of a mirror whose own README does not state its derivation, and no official hash is "
            "available offline. A name or a matching size is not byte identity.", True))

    # -- 3. pinned Forge compatibility -------------------------------------------------------------------------------
    if pin.marker_revision != pin.expected_revision or pin.marker_status != "verified":
        nogo_pin.append(Finding("PIN_NOT_VERIFIED", MEASURED,
                                f"Managed Forge marker revision {pin.marker_revision!r} / status {pin.marker_status!r} does not "
                                f"verify the pinned {pin.expected_revision[:8]}.", True))
    if not pin.source_scanned:
        inconclusive.append(Finding("PIN_SOURCE_NOT_READ", MEASURED, "The pinned Forge source could not be inspected.", True))
    else:
        if pin.supports_flux2_9b is False:
            nogo_pin.append(Finding("PIN_LACKS_FLUX2_9B", MEASURED, "The pinned Forge has no Flux.2 Klein 9B model definition.", True))
        if pin.supports_qwen3_8b is False:
            nogo_pin.append(Finding("PIN_LACKS_QWEN3_8B", MEASURED, "The pinned Forge cannot load a Qwen3 8B text encoder.", True))
        if pin.supports_flux2_9b and pin.supports_qwen3_8b:
            findings.append(Finding("PIN_SUPPORTS_9B_SOFTWARE", MEASURED,
                                    "The pinned Forge defines Flux2K9B (hidden 4096) and loads a Qwen3 8B encoder: software "
                                    "support exists; this says nothing about resource fit."))

    # -- 4. resource feasibility -------------------------------------------------------------------------------------
    sizes = [item.size_bytes for item in (transformer, encoder, vae) if item.size_bytes]
    weights = sum(sizes) if len(sizes) == 3 else None
    estimated: dict[str, Any] = {}
    needed = {"total_ram_bytes": telemetry.total_ram_bytes, "vram_total_bytes": telemetry.vram_total_bytes}
    for name, value in needed.items():
        if value is None:
            inconclusive.append(Finding(f"TELEMETRY_{name.upper()}_MISSING", MEASURED,
                                        f"{name} could not be measured; resource fit cannot be decided.", True))
    if weights is not None:
        estimated["weights_bytes"] = weights
        estimated["host_peak_best_case_bytes"] = weights  # resident exactly once; no process overhead
        estimated["host_peak_scaled_bytes"] = int(weights * policy.scaled_peak_factor)
        estimated["scaled_peak_factor"] = round(policy.scaled_peak_factor, 3)
        estimated["runtime_cost_ratio_vs_klein4b_distilled"] = round(
            (policy.official_steps / IMG115_BASELINE["steps"]) * 2.25, 1
        )  # steps ratio x parameter ratio (9B/4B): a rough compute multiple, for scale only
    if weights is not None and telemetry.total_ram_bytes is not None:
        usable = telemetry.total_ram_bytes - policy.host_reserve_bytes
        estimated["usable_physical_bytes"] = usable
        if weights > usable:
            nogo_resource.append(Finding(
                "HOST_RESIDENT_WEIGHTS_EXCEED_PHYSICAL", ESTIMATED,
                f"The three files total {_gib(weights)} GiB; after a {_gib(policy.host_reserve_bytes)} GiB reserve only "
                f"{_gib(usable)} GiB of the {_gib(telemetry.total_ram_bytes)} GiB physical RAM is usable. Even the best case "
                "(each file resident exactly once, no process overhead) does not fit, so loading would force sustained paging.", True))
        peak = estimated["host_peak_scaled_bytes"]
        if telemetry.commit_headroom_bytes is not None and peak > telemetry.commit_headroom_bytes * policy.commit_margin:
            nogo_resource.append(Finding(
                "HOST_PEAK_EXCEEDS_COMMIT_HEADROOM", ESTIMATED,
                f"Scaling the PR-IMG-115 Forge-tree peak ({IMG115_BASELINE['forge_tree_private_peak_gib']} GiB for "
                f"{_gib(IMG115_BASELINE['weights_bytes'])} GiB of weights) gives about {_gib(peak)} GiB; the commit headroom is "
                f"{_gib(telemetry.commit_headroom_bytes)} GiB (policy allows {int(policy.commit_margin * 100)}%).", True))
        elif telemetry.commit_headroom_bytes is None:
            inconclusive.append(Finding("TELEMETRY_COMMIT_HEADROOM_MISSING", MEASURED,
                                        "System commit headroom could not be measured.", True))
    if transformer.size_bytes and telemetry.vram_total_bytes is not None:
        resident_limit = telemetry.vram_total_bytes - policy.vram_activation_reserve_bytes
        estimated["vram_resident_limit_bytes"] = resident_limit
        if transformer.size_bytes > resident_limit:
            nogo_resource.append(Finding(
                "VRAM_TRANSFORMER_EXCEEDS_DEDICATED", ESTIMATED,
                f"The BF16 transformer alone is {_gib(transformer.size_bytes)} GiB against {_gib(telemetry.vram_total_bytes)} GiB of "
                f"dedicated VRAM ({_gib(policy.vram_activation_reserve_bytes)} GiB reserved for activations). It cannot be resident, "
                "so it would need block offload/swap, which is outside the PR-IMG-115 envelope and would add host-memory and "
                "shared-GPU-memory spill. Precision, offload and loading strategy are not altered to make a test fit.", True))
    if telemetry.shared_gpu_memory_bytes is None:
        findings.append(Finding("SHARED_GPU_MEMORY_NOT_MEASURED", MEASURED,
                                "Shared GPU memory usage was not available from the counters; spill cannot be baselined."))
    if telemetry.forge_endpoint_listening:
        findings.append(Finding("FORGE_ENDPOINT_ALREADY_LISTENING", MEASURED,
                                "A Forge-class endpoint is already listening; a qualification could not own its lifecycle."))
    if telemetry.available_ram_bytes is not None:
        findings.append(Finding("AVAILABLE_RAM_RECORDED", MEASURED,
                                f"{_gib(telemetry.available_ram_bytes)} GiB physical RAM was available at measurement time "
                                "(observational; the decision uses totals and headroom, not a momentary reading)."))
    findings.append(Finding(
        "OFFICIAL_BASE_SETTINGS_DIFFER_FROM_KLEIN4B_PROFILE", DOCUMENTED,
        f"The undistilled Base 9B reference uses about {policy.official_steps} steps at guidance {policy.official_cfg}, not the "
        f"distilled 4B profile ({IMG115_BASELINE['steps']} steps, CFG {IMG115_BASELINE['cfg']}); the 4B profile and its qualification "
        "do not transfer. Settings are not changed here."))
    findings.append(Finding("KNOWN_GPU_RISK_CONTEXT", DOCUMENTED, KNOWN_GPU_RISK_CONTEXT["summary"]))

    # -- 5. verdict ---------------------------------------------------------------------------------------------------
    if missing:
        verdict = MISSING_DEPENDENCY
        nxt = "Install/identify the missing or mismatched exact components; nothing is substituted. No further action here."
    elif nogo_pin:
        verdict = NO_GO_PINNED_FORGE
        nxt = "Close as no-go for the pinned Forge; a Forge pin change is a separate architecture decision."
    elif nogo_resource:
        verdict = NO_GO_RESOURCE_RISK
        nxt = ("Close PR-IMG-MODELS-151 as a documented no-go for this workstation: no model load, no generation. Revisit only "
               "with materially different hardware (larger VRAM/RAM) or an owner-approved smaller exact candidate "
               "(for example a quantized-transformer 9B) that gets its own feasibility evaluation.")
    elif inconclusive:
        verdict = INCONCLUSIVE
        nxt = "Re-run with complete telemetry (total RAM, commit headroom, VRAM) and a readable pinned Forge source."
    elif identity:
        verdict = IDENTITY_PENDING
        nxt = "Compute SHA-256 for the three exact files (--hash) and establish provenance before any owner authorization."
    else:
        verdict = ELIGIBLE
        nxt = "Stop and obtain a separate owner authorization for a single controlled GPU qualification."

    findings = [*missing, *nogo_pin, *nogo_resource, *inconclusive, *identity, *findings]
    measured = {
        "candidate_sizes_bytes": {i.role: i.size_bytes for i in (transformer, encoder, vae)},
        "telemetry": {k: v for k, v in asdict(telemetry).items() if k != "competing_processes"},
        "competing_processes_top_working_set": [
            {"name": n, "working_set_gib": _gib(b)} for n, b in telemetry.competing_processes
        ],
    }
    return FeasibilityReport(
        verdict=verdict,
        findings=tuple(findings),
        next_recommendation=nxt,
        measured=measured,
        estimated=estimated,
        assumptions={**asdict(policy), "baseline": dict(IMG115_BASELINE)},
        candidate={
            "transformer": _describe(transformer), "text_encoder": _describe(encoder), "vae": _describe(vae),
            "alternates": [_describe(a) for a in candidate.alternates], "source": dict(candidate.source),
        },
        pin=asdict(pin),
        context={"known_gpu_risk": dict(KNOWN_GPU_RISK_CONTEXT)},
    )


def _describe(item: CandidateFile) -> dict[str, Any]:
    return {
        "name": item.name, "present": item.present, "size_bytes": item.size_bytes, "sha256": item.sha256,
        "provenance": item.provenance,
        "role": item.evidence.role if item.evidence else None,
        "architecture": item.evidence.architecture if item.evidence else None,
        "facts": dict(item.evidence.facts) if item.evidence else {},
        "error": item.evidence.error if item.evidence else None,
    }


# ---------------------------------------------------------------------------------------------------- collectors

CommandRunner = Callable[[Sequence[str]], str | None]


def run_read_only(argv: Sequence[str]) -> str | None:
    """Run one allow-listed read-only query; ``None`` when it fails. Anything not on the list is refused."""

    if tuple(argv) not in set(READ_ONLY_COMMANDS.values()):
        raise PermissionError("command is not an allow-listed read-only query")
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=20, check=False)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _json(text: str | None) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def collect_telemetry(
    *,
    runner: CommandRunner = run_read_only,
    memory_probe: Callable[[], HostMemorySnapshot] = read_host_memory,
    port_probe: Callable[[int], bool] | None = None,
    ports: Sequence[int] = (7861, 7860),
) -> HostTelemetry:
    missing: list[str] = []
    total = available = headroom = None
    try:
        snapshot = memory_probe()
        total, available, headroom = snapshot.total_bytes, snapshot.available_bytes, snapshot.commit_headroom_bytes
    except Exception:  # noqa: BLE001 - recorded as missing, never guessed
        missing.append("host_memory")
    pagefile = None
    page = _json(runner(READ_ONLY_COMMANDS["pagefile"]))
    if isinstance(page, dict):
        page = [page]
    if isinstance(page, list) and page:
        pagefile = int(sum(int(p.get("AllocatedBaseSize") or 0) for p in page) * 1024 * 1024)
    else:
        missing.append("pagefile")
    vram = (None, None, None, None, None)
    smi = runner(READ_ONLY_COMMANDS["nvidia_smi"])
    if smi:
        parts = [p.strip() for p in smi.strip().splitlines()[0].split(",")]
        try:
            vram = (parts[0], int(float(parts[1])) * 1024 * 1024, int(float(parts[2])) * 1024 * 1024,
                    int(float(parts[3])) * 1024 * 1024, float(parts[4]))
        except (IndexError, ValueError):
            missing.append("vram")
    else:
        missing.append("vram")
    shared = None
    raw_shared = runner(READ_ONLY_COMMANDS["gpu_shared_memory"])
    if raw_shared and raw_shared.strip():
        try:
            shared = int(float(raw_shared.strip()))
        except ValueError:
            missing.append("shared_gpu_memory")
    else:
        missing.append("shared_gpu_memory")
    procs: list[tuple[str, int]] = []
    listing = _json(runner(READ_ONLY_COMMANDS["processes"]))
    if isinstance(listing, dict):
        listing = [listing]
    if isinstance(listing, list):
        procs = [(str(p.get("Name")), int(p.get("WorkingSet64") or 0)) for p in listing if isinstance(p, dict)]
    else:
        missing.append("processes")
    probe = port_probe or _tcp_listening
    listening = None
    try:
        listening = any(probe(port) for port in ports)
    except Exception:  # noqa: BLE001
        missing.append("endpoint_probe")
    return HostTelemetry(
        total_ram_bytes=total, available_ram_bytes=available, commit_headroom_bytes=headroom,
        pagefile_allocated_bytes=pagefile, vram_total_bytes=vram[1], vram_used_bytes=vram[2], vram_free_bytes=vram[3],
        gpu_name=vram[0], gpu_temperature_c=vram[4], shared_gpu_memory_bytes=shared,
        competing_processes=tuple(procs), forge_endpoint_listening=listening, missing=tuple(missing),
    )


def _tcp_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def collect_pin(install_dir: Path, *, expected: str = PINNED_REVISION) -> PinEvidence:
    """Read-only inspection of the managed Forge marker and the pinned source's own model definitions."""

    marker: dict[str, Any] = {}
    try:
        marker = json.loads((install_dir / ".stablenew-managed-forge.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    source = install_dir / "source"
    model_list = source / "modules_forge" / "packages" / "huggingface_guess" / "model_list.py"
    loader = source / "backend" / "loader.py"
    try:
        guess = model_list.read_text(encoding="utf-8", errors="replace")
        loading = loader.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return PinEvidence(expected, marker.get("revision"), marker.get("status"))
    block = re.search(r"class Flux2K9B\(.*?(?=\nclass |\Z)", guess, re.S)
    factor = re.search(r"memory_usage_factor\s*=\s*([0-9.]+)", block.group(0)) if block else None
    dtypes = re.findall(r"torch\.(bfloat16|float16|float32)", block.group(0)) if block else []
    return PinEvidence(
        expected_revision=expected,
        marker_revision=marker.get("revision"),
        marker_status=marker.get("status"),
        source_scanned=True,
        supports_flux2_9b=bool(block and "4096" in block.group(0)),
        supports_qwen3_8b="Qwen3_8B" in loading,
        supported_dtypes=tuple(dtypes),
        memory_usage_factor=float(factor.group(1)) if factor else None,
    )


def sha256_file(path: Path, *, chunk: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _candidate_file(
    role: str, path: Path, *, hash_it: bool, reference: Path | None = None
) -> CandidateFile:
    if not path.is_file():
        return CandidateFile(role, path.name, present=False)
    size = path.stat().st_size
    provenance = "unknown"
    digest = sha256_file(path) if hash_it else None
    if reference is not None and reference.is_file():
        try:
            if os.path.samefile(path, reference):
                provenance = "same_file_as_recorded_source"
            elif hash_it and reference.stat().st_size == size:
                # Byte equality needs both reads; a matching size alone is never reported as equality.
                provenance = "same_bytes_as_recorded_source" if sha256_file(reference) == digest else "differs_from_recorded_source"
            elif reference.stat().st_size == size:
                provenance = "same_size_as_recorded_source"
            else:
                provenance = "differs_from_recorded_source"
        except OSError:
            pass
    return CandidateFile(role, path.name, True, size, inspect_component_file(path), digest, provenance)


def collect_candidate(
    webui_root: Path,
    *,
    hf_cache: Path | None = None,
    hash_files: bool = False,
) -> CandidateSet:
    models = webui_root / "models"
    repack = encoder_ref = vae_ref = transformer_ref = None
    source: dict[str, Any] = {}
    if hf_cache is not None:
        mirror = _first_snapshot(hf_cache / "models--darknight9121--FLUX.2-klein-base-9B-bucket-uncensored")
        repack = _first_snapshot(hf_cache / "models--Comfy-Org--vae-text-encorder-for-flux-klein-9b")
        if mirror:
            transformer_ref = mirror / TRANSFORMER_NAME
            source["transformer"] = _front_matter(mirror / "README.md") | {"repository_cache": mirror.parent.parent.name}
        if repack:
            encoder_ref = repack / "split_files" / "text_encoders" / ENCODER_NAME
            vae_ref = repack / "split_files" / "vae" / VAE_NAME
            source["modules"] = _front_matter(repack / "README.md") | {"repository_cache": repack.parent.parent.name}
    transformer = _candidate_file("transformer", models / "Stable-diffusion" / TRANSFORMER_NAME,
                                  hash_it=hash_files, reference=transformer_ref)
    encoder = _candidate_file("text_encoder", models / "text_encoder" / ENCODER_NAME, hash_it=hash_files, reference=encoder_ref)
    vae = _candidate_file("vae", models / "VAE" / VAE_NAME, hash_it=hash_files, reference=vae_ref)
    alternates: list[CandidateFile] = []
    for folder, role in ((models / "text_encoder", "text_encoder"), (models / "VAE", "vae")):
        for path in sorted(folder.glob("*.safetensors")) if folder.is_dir() else []:
            if path.name in (ENCODER_NAME, VAE_NAME):
                continue
            found = inspect_component_file(path)
            if found.architecture in ("qwen3", "flux_vae"):
                alternates.append(CandidateFile(role, path.name, True, path.stat().st_size, found))
    return CandidateSet(transformer, encoder, vae, tuple(alternates), source)


def _first_snapshot(repo_cache: Path) -> Path | None:
    snapshots = repo_cache / "snapshots"
    if not snapshots.is_dir():
        return None
    folders = sorted(p for p in snapshots.iterdir() if p.is_dir())
    return folders[0] if folders else None


def _front_matter(readme: Path) -> dict[str, Any]:
    try:
        head = readme.read_text(encoding="utf-8", errors="replace").split("---")[1]
    except (OSError, IndexError):
        return {}
    wanted = {}
    for key in ("license", "license_name", "base_model"):
        found = re.search(rf"^{key}:\s*(.+)$", head, re.M)
        if found:
            wanted[key] = found.group(1).strip()
    return wanted


# ---------------------------------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webui-root", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True, help="the managed Forge neo-<rev8> directory (read only)")
    parser.add_argument("--hf-cache", type=Path, default=None)
    parser.add_argument("--hash", action="store_true", help="read the three files once to compute SHA-256 (no writes)")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate(
        collect_candidate(args.webui_root, hf_cache=args.hf_cache, hash_files=args.hash),
        collect_pin(args.install_dir),
        collect_telemetry(),
    )
    payload = report.as_dict() | {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(report.verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
