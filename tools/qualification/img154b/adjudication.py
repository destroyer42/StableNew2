"""D3 (154B): response validation, telemetry-coverage and the case-result classification.

Pure apart from the lazy image decode (Pillow). Nothing here talks to a runtime. ``TECHNICAL_PASS_CONSTRAINED`` is reachable
only when the facts carry the authority of a separately authorized physical execution AND every piece of evidence is complete;
it is one constrained result for one frozen case and says nothing about general stability or production readiness.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tools.qualification.img154.core import Finding
from tools.qualification.img154.evidence import (
    AMBIGUOUS_DISPATCH,
    BOOT_CHANGED,
    INSTRUMENTATION_GAP,
    LOADER_FAILED,
    NEW_EVENTS,
    NO_NEW_EVENTS_COMPLETE_COVERAGE,
    OUTPUT_VALIDATION_FAIL,
    PREFLIGHT_REFUSED,
    RESOURCE_ABORT_REQUESTED,
    SYSTEM_OR_GPU_FAULT,
    TECHNICAL_PASS_CONSTRAINED,
    ResultFacts,
    classify_non_pass,
)
from tools.qualification.img154.manifest import QualificationManifest, build_manifest
from tools.qualification.img154b.request import verify_infotext

AUTHORITY_PHYSICAL = "owner_authorized_physical"
AUTHORITY_SYNTHETIC = "synthetic"

#: The only shutdown outcome that does not block a pass: the manager-owned stop completed and no owned process survived.
SHUTDOWN_VERIFIED = "verified_clean"
SHUTDOWN_NOT_ATTEMPTED = "not_attempted"
SHUTDOWN_UNVERIFIED = "requested_unverified"
SHUTDOWN_TIMED_OUT = "timed_out"

#: Telemetry that must have been observed for a result to be called complete (the 154A essentials plus shared memory and the
#: owned process tree). Page-input rate and board power are recorded when available and are not pass-blocking.
REQUIRED_SAMPLE_FIELDS = (
    "commit_headroom_bytes",
    "ram_available_bytes",
    "vram_used_bytes",
    "vram_total_bytes",
    "shared_vram_bytes",
    "gpu_temperature_c",
    "gpu_device_present",
    "forge_tree_private_bytes",
)
MIN_COVERAGE_FRACTION = 0.95
MIN_SAMPLES = 5
MAX_PNG_B64_CHARS = 64 * 1024 * 1024
#: A decoded image whose pixel standard deviation is at or below this is a constant image (PR-IMG-115's threshold).
NONTRIVIAL_PIXEL_STD = 2.0


# ----------------------------------------------------------------------------------------------------- response checks


@dataclass(frozen=True)
class OutputFacts:
    http_status: int | None
    images_returned: int | None
    decodable: bool
    dimensions: tuple[int, int] | None
    dimensions_ok: bool
    nontrivial: bool
    pixel_std: float | None
    seed_returned: int | None
    seed_ok: bool
    infotext_ok: bool | None
    identity_complete: bool
    sha256: str | None
    bytes_len: int | None
    problems: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        """Everything the adjudication needs from the response for a pass (identity completeness is separate)."""

        return (
            self.http_status == 200
            and self.images_returned == 1
            and self.decodable
            and self.dimensions_ok
            and self.nontrivial
            and self.seed_ok
            and self.infotext_ok is True
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "http_status": self.http_status,
            "images_returned": self.images_returned,
            "decodable": self.decodable,
            "dimensions": list(self.dimensions) if self.dimensions else None,
            "dimensions_ok": self.dimensions_ok,
            "nontrivial": self.nontrivial,
            "pixel_std": self.pixel_std,
            "seed_returned": self.seed_returned,
            "seed_ok": self.seed_ok,
            "infotext_ok": self.infotext_ok,
            "identity_complete": self.identity_complete,
            "sha256": self.sha256,
            "bytes": self.bytes_len,
            "valid": self.valid,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class ResponseValidation:
    facts: OutputFacts
    findings: tuple[Finding, ...]
    png: bytes | None = None
    info: Mapping[str, Any] = field(default_factory=dict)


def _decode_png(b64: str, width: int, height: int) -> tuple[bytes, dict[str, Any]]:
    """PR-IMG-115's validated decode (base64, full pixel decode, dimensions, pixel variation); never raises."""

    from tools.qualification.img115.run import _decode_png as decode

    return decode(b64, width, height)  # type: ignore[no-any-return]


def _bad(
    status: int | None, problems: Sequence[str], findings: Sequence[Finding], **kw: Any
) -> ResponseValidation:
    facts = OutputFacts(
        http_status=status,
        images_returned=kw.get("images"),
        decodable=False,
        dimensions=None,
        dimensions_ok=False,
        nontrivial=False,
        pixel_std=None,
        seed_returned=None,
        seed_ok=False,
        infotext_ok=None,
        identity_complete=False,
        sha256=None,
        bytes_len=None,
        problems=tuple(problems),
    )
    return ResponseValidation(facts, tuple(findings))


def validate_response(
    http_status: int | None,
    body: object,
    manifest: QualificationManifest | None = None,
) -> ResponseValidation:
    """Exactly one decodable 1024x1024 non-constant image with the requested seed and the frozen effective parameters."""

    plan = manifest or build_manifest()
    intent = plan.intent
    findings: list[Finding] = []
    if http_status != 200:
        return _bad(
            http_status,
            [f"http status {http_status}"],
            [Finding("RESPONSE_STATUS", "refuse", f"generation returned {http_status}")],
        )
    if not isinstance(body, Mapping):
        return _bad(
            http_status,
            ["body not an object"],
            [Finding("RESPONSE_SHAPE", "refuse", "response body is not an object")],
        )
    images = body.get("images")
    if not isinstance(images, list):
        return _bad(
            http_status,
            ["no image list"],
            [Finding("RESPONSE_SHAPE", "refuse", "response has no image list")],
        )
    if len(images) != 1:
        return _bad(
            http_status,
            [f"{len(images)} images"],
            [
                Finding(
                    "RESPONSE_IMAGE_COUNT",
                    "refuse",
                    f"{len(images)} images returned, exactly 1 expected",
                )
            ],
            images=len(images),
        )
    encoded = images[0]
    if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_PNG_B64_CHARS:
        return _bad(
            http_status,
            ["image is not a bounded base64 string"],
            [Finding("RESPONSE_IMAGE_ENCODING", "refuse", "image is not a bounded base64 string")],
            images=1,
        )
    raw, decoded = _decode_png(encoded, intent.width, intent.height)
    size = decoded.get("size")
    decodable = bool(decoded.get("decode_error") is None and size)
    if not decodable:
        findings.append(
            Finding(
                "IMAGE_NOT_DECODABLE",
                "refuse",
                str(decoded.get("decode_error", "undecodable"))[:120],
            )
        )
    if decodable and not decoded.get("dimensions_ok"):
        findings.append(
            Finding("IMAGE_DIMENSIONS", "refuse", f"{size} is not {intent.width}x{intent.height}")
        )
    if decodable and not decoded.get("non_constant"):
        findings.append(Finding("IMAGE_TRIVIAL", "refuse", "decoded image is constant"))
    info_raw = body.get("info")
    info: Mapping[str, Any] = {}
    if isinstance(info_raw, str):
        try:
            parsed = json.loads(info_raw)
            info = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            info = {}
    elif isinstance(info_raw, Mapping):
        info = info_raw
    seed = info.get("seed")
    all_seeds = info.get("all_seeds")
    seed_ok = (
        isinstance(seed, int)
        and not isinstance(seed, bool)
        and seed == intent.seed
        and isinstance(all_seeds, list)
        and all_seeds == [intent.seed]
    )
    if not seed_ok:
        findings.append(
            Finding(
                "SEED_NOT_CONFIRMED",
                "refuse" if seed is not None else "inconclusive",
                "returned seed differs or is absent",
            )
        )
    infotexts = info.get("infotexts")
    infotext = (
        infotexts[0]
        if isinstance(infotexts, list) and infotexts and isinstance(infotexts[0], str)
        else None
    )
    info_findings, info_facts = verify_infotext(infotext, plan)
    findings.extend(info_findings)
    refused = any(item.severity == "refuse" for item in info_findings)
    infotext_ok: bool | None = False if refused else (True if not info_findings else None)
    identity_complete = (
        infotext is not None
        and bool(info_facts.get("model_hash_reported"))
        and info_facts.get("modules_reported") == 2
        and not info_findings
    )
    digest = hashlib.sha256(raw).hexdigest() if raw else None
    facts = OutputFacts(
        http_status=http_status,
        images_returned=1,
        decodable=decodable,
        dimensions=tuple(size) if decodable and size else None,  # type: ignore[arg-type]
        dimensions_ok=bool(decodable and decoded.get("dimensions_ok")),
        nontrivial=bool(decodable and decoded.get("non_constant")),
        pixel_std=decoded.get("pixel_std"),
        seed_returned=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        seed_ok=seed_ok,
        infotext_ok=infotext_ok,
        identity_complete=identity_complete,
        sha256=digest,
        bytes_len=len(raw) if raw else None,
        problems=tuple(item.code for item in findings),
    )
    return ResponseValidation(facts, tuple(findings), raw if decodable else None, info)


# ------------------------------------------------------------------------------------------------ telemetry coverage


@dataclass(frozen=True)
class TelemetryCoverage:
    complete: bool
    samples: int
    fractions: Mapping[str, float]
    missing_fields: tuple[str, ...]
    max_gap_s: float | None
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "samples": self.samples,
            "fractions": {k: round(v, 3) for k, v in self.fractions.items()},
            "missing_fields": list(self.missing_fields),
            "max_gap_s": self.max_gap_s,
            "reasons": list(self.reasons),
        }


def evaluate_telemetry_coverage(
    records: Sequence[Mapping[str, Any]],
    *,
    required: Sequence[str] = REQUIRED_SAMPLE_FIELDS,
    min_fraction: float = MIN_COVERAGE_FRACTION,
    min_samples: int = MIN_SAMPLES,
    max_gap_s: float = 3.0,
) -> TelemetryCoverage:
    """Whether the persisted sample stream covers the required fields densely enough to call the run instrumented.

    A field counts as observed only with ``status == "ok"``. A missing ``sample_seq`` range (lost records), a wall of unknowns, a
    non-monotonic clock or a gap above ``max_gap_s`` all make the stream incomplete: nothing is inferred across a gap.
    """

    samples = [r for r in records if isinstance(r, Mapping) and r.get("kind") == "sample"]
    reasons: list[str] = []
    if len(samples) < min_samples:
        reasons.append("too_few_samples")
    fractions: dict[str, float] = {}
    for name in required:
        # a field that was not applicable at that moment (no owned process yet) is neither a hit nor a miss; a field that was
        # never applicable has no coverage at all
        applicable = [
            r
            for r in samples
            if not (
                isinstance(r.get("status"), Mapping) and r["status"].get(name) == "not_applicable"
            )
        ]
        ok = sum(
            1
            for r in applicable
            if isinstance(r.get("status"), Mapping) and r["status"].get(name) == "ok"
        )
        fractions[name] = ok / len(applicable) if applicable else 0.0
    missing = tuple(name for name, fraction in fractions.items() if fraction < min_fraction)
    if missing:
        reasons.append("field_coverage_below_threshold")
    seqs = [r.get("sample_seq") for r in samples]
    if any(not isinstance(s, int) or isinstance(s, bool) for s in seqs):
        reasons.append("sequence_invalid")
    else:
        if seqs != sorted(set(seqs)) or (seqs and seqs[-1] - seqs[0] + 1 != len(seqs)):
            reasons.append("sequence_gap_or_disorder")
    monos = [r.get("mono_s") for r in samples]
    largest: float | None = None
    if all(isinstance(m, int | float) and not isinstance(m, bool) for m in monos) and monos:
        steps = [b - a for a, b in zip(monos, monos[1:], strict=False)]
        if any(step < 0 for step in steps):
            reasons.append("clock_not_monotonic")
        largest = max(steps) if steps else 0.0
        if largest > max_gap_s:
            reasons.append("sampling_gap")
    elif samples:
        reasons.append("clock_invalid")
    return TelemetryCoverage(not reasons, len(samples), fractions, missing, largest, tuple(reasons))


# ------------------------------------------------------------------------------------------------- case classification


@dataclass(frozen=True)
class CaseFacts:
    """Everything the classification may use. Every field defaults to the unfavorable value."""

    authority: str = AUTHORITY_SYNTHETIC
    preflight_prepared: bool = False
    claimed: bool = False
    startup_observed: bool = False
    selection_confirmed: bool = False
    dispatched: bool = False
    response_received: bool = False
    loader_failed: bool = False
    monitor_codes: tuple[str, ...] = ()
    monitor_latched: str = "NONE"
    shutdown: str = SHUTDOWN_NOT_ATTEMPTED
    unexplained_survivors: bool | None = None
    telemetry_complete: bool = False
    fault_status: str = "UNKNOWN_COVERAGE_GAP"
    output_valid: bool | None = None
    identity_complete: bool = False
    ledger_terminal_recorded: bool = False
    evidence_complete: bool = False


@dataclass(frozen=True)
class CaseResult:
    result_class: str
    also: tuple[str, ...]
    reasons: tuple[str, ...]
    #: Never a general-stability or production-qualification claim; only ``TECHNICAL_PASS_CONSTRAINED`` carries any meaning.
    statement: str

    @property
    def is_pass(self) -> bool:
        return self.result_class == TECHNICAL_PASS_CONSTRAINED

    def as_dict(self) -> dict[str, Any]:
        return {
            "result_class": self.result_class,
            "also": list(self.also),
            "reasons": list(self.reasons),
            "statement": self.statement,
        }


NOT_A_PASS = "Not a pass. Nothing is established about stability or production use."
CONSTRAINED = (
    "One constrained technical result for the single frozen case on this host. It does not establish general stability, "
    "repeatability, production qualification or support for the model."
)

_FAULT_CODE_PREFIXES = ("GPU_FAULT_EVENT", "GPU_DEVICE_LOST")


def classify_case(facts: CaseFacts) -> CaseResult:
    """Map evidence to one of the eight result classes (the 154A order of precedence for failures).

    A pass additionally needs the physical authority, a verified selection, a verified clean owned shutdown with no unexplained
    survivor, a recorded terminal ledger entry and a fully quiet monitor; anything missing is ``INSTRUMENTATION_GAP``.
    """

    fault_event = any(code.startswith(_FAULT_CODE_PREFIXES) for code in facts.monitor_codes)
    stop = facts.monitor_latched == "REQUEST_OWNER_STOP"
    uncertain = facts.monitor_latched in ("CANNOT_VERIFY_SAFE_STATE", "HARNESS_FAULT")
    base = ResultFacts(
        preflight_prepared=facts.preflight_prepared,
        dispatched=facts.dispatched,
        outcome_recorded=facts.response_received,
        loader_failed=facts.loader_failed,
        stop_requested=stop,
        fault_status=NEW_EVENTS
        if fault_event and facts.fault_status not in (NEW_EVENTS, BOOT_CHANGED)
        else facts.fault_status,
        telemetry_complete=facts.telemetry_complete,
        output_valid=facts.output_valid,
    )
    primary, also = classify_non_pass(base)
    reasons: list[str] = []
    classes: list[str] = []
    if primary is not None:
        classes.append(primary)
        classes.extend(also)
    if uncertain and INSTRUMENTATION_GAP not in classes:
        classes.append(INSTRUMENTATION_GAP)
        reasons.append(f"monitor latched {facts.monitor_latched}")
    if facts.dispatched and not facts.response_received and AMBIGUOUS_DISPATCH not in classes:
        classes.append(AMBIGUOUS_DISPATCH)
    if classes:
        ordered = _precedence_order(classes)
        return CaseResult(ordered[0], tuple(ordered[1:]), tuple(reasons), NOT_A_PASS)
    # No failure class applies: this is a candidate pass. Every remaining requirement must hold.
    missing: list[str] = []
    if facts.authority != AUTHORITY_PHYSICAL:
        missing.append("authority_not_physical_owner_authorized")
    for name, ok in (
        ("claimed", facts.claimed),
        ("startup_observed", facts.startup_observed),
        ("selection_confirmed", facts.selection_confirmed),
        ("dispatched", facts.dispatched),
        ("response_received", facts.response_received),
        ("identity_complete", facts.identity_complete),
        ("ledger_terminal_recorded", facts.ledger_terminal_recorded),
        ("evidence_bundle_complete", facts.evidence_complete),
        ("shutdown_verified_clean", facts.shutdown == SHUTDOWN_VERIFIED),
        ("no_unexplained_survivors", facts.unexplained_survivors is False),
        (
            "fault_coverage_complete_and_clean",
            facts.fault_status == NO_NEW_EVENTS_COMPLETE_COVERAGE,
        ),
        ("monitor_quiet", facts.monitor_latched in ("NONE", "WARN")),
        ("output_valid", facts.output_valid is True),
        ("telemetry_complete", facts.telemetry_complete),
    ):
        if not ok:
            missing.append(name)
    if missing:
        return CaseResult(INSTRUMENTATION_GAP, (), tuple(missing), NOT_A_PASS)
    return CaseResult(TECHNICAL_PASS_CONSTRAINED, (), (), CONSTRAINED)


_ORDER = (
    PREFLIGHT_REFUSED,
    SYSTEM_OR_GPU_FAULT,
    AMBIGUOUS_DISPATCH,
    RESOURCE_ABORT_REQUESTED,
    LOADER_FAILED,
    INSTRUMENTATION_GAP,
    OUTPUT_VALIDATION_FAIL,
)


def _precedence_order(classes: Sequence[str]) -> list[str]:
    unique = list(dict.fromkeys(classes))
    return sorted(unique, key=lambda item: _ORDER.index(item) if item in _ORDER else len(_ORDER))
