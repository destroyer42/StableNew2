"""D9 (154B): assembly of a live preflight from injected host readers, and the quiescent-baseline acquisition.

The readers are callables (the real ones are wired by ``physical``; tests inject fakes), so the ASSEMBLY rules are tested
without a host: section findings are never ``None`` by accident, every unobtainable reading is a non-``ok`` observation, the
resource readings are taken LAST so they are the freshest, and the baseline is a window the harness's own sampler acquired.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tools.qualification.img154.core import Finding, Observation
from tools.qualification.img154.evidence import (
    ACCEPTED_BASELINE_COVERAGE,
    FAULT_SOURCES,
    FaultSnapshot,
)
from tools.qualification.img154.isolation import (
    PortObservation,
    ProcessObservation,
    validate_endpoint,
    validate_process_conflicts,
)
from tools.qualification.img154.manifest import (
    QualificationManifest,
    build_manifest,
    verify_intent,
)
from tools.qualification.img154.preflight import (
    BASELINE_PROVIDER,
    ESSENTIAL_TELEMETRY,
    BaselineSample,
    PreflightInputs,
    QuiescentBaselineEvidence,
)
from tools.qualification.img154b.authorization import CodeRevision
from tools.qualification.img154b.case import Collected
from tools.qualification.img154b.request import (
    FrozenPayload,
    SourceReader,
    verify_payload,
    verify_pinned_semantics,
)
from tools.qualification.img154b.runtime import ServedProof
from tools.qualification.img154b.sampler import OK, Provider

#: provider field -> the observation name the 154A evaluator expects, with its units
OBSERVATION_FIELDS: Mapping[str, tuple[str, str]] = {
    "commit_headroom_bytes": ("commit_headroom_bytes", "bytes"),
    "commit_limit_bytes": ("commit_limit_bytes", "bytes"),
    "commit_total_bytes": ("commit_total_bytes", "bytes"),
    "ram_available_bytes": ("ram_available_bytes", "bytes"),
    "vram_used_bytes": ("vram_used_bytes", "bytes"),
    "vram_total_bytes": ("vram_total_bytes", "bytes"),
    "shared_vram_bytes": ("shared_vram_bytes", "bytes"),
    "gpu_temperature_c": ("gpu_temperature_c", "celsius"),
    "gpu_utilization_percent": ("gpu_utilization_percent", "percent"),
    "gpu_board_power_w": ("gpu_board_power_w", "watts"),
    "gpu_device_present": ("gpu_device_present", "boolean"),
    "hard_pages_input_per_s": ("hard_pages_input_per_s", "pages_per_second"),
}


@dataclass
class HostReaders:
    """Everything a live preflight reads. Each callable is read-only; none starts, selects, sends or stops anything."""

    code_revision: Callable[[], Mapping[str, Any]]
    read_source: SourceReader
    isolation_findings: Callable[[], list[Finding]]
    pin_findings: Callable[[], list[Finding]]
    served_proof: Callable[[], ServedProof]
    served_unchanged: Callable[[], list[Finding]]
    launch_findings: Callable[[], list[Finding]]
    storage_findings: Callable[[], list[Finding]]
    port: Callable[[], PortObservation | None]
    processes: Callable[[], list[ProcessObservation] | None]
    providers: Sequence[Provider]
    pagefile_free: Callable[[], Observation]
    evidence_free: Callable[[], Observation]
    fault_snapshot: Callable[[], FaultSnapshot | None]
    device_id: Callable[[], str | None]
    workspace_ledger_state: Callable[[], str]
    process_tree_capable: Callable[[], bool]
    evidence_dir_valid: Callable[[], bool | None]
    mono: Callable[[], float]
    utc: Callable[[], str]
    sleep: Callable[[float], None]
    environment: Callable[[], Mapping[str, Any]] = field(default=lambda: {})
    baseline_seconds: float = 25.0
    baseline_interval_s: float = 1.0


def _number(observed: Mapping[str, Observation], name: str) -> float | None:
    item = observed.get(name)
    value = item.value if item is not None and item.status == "ok" else None
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class LiveCollector:
    def __init__(
        self,
        readers: HostReaders,
        *,
        manifest: QualificationManifest | None = None,
        payload: FrozenPayload,
    ) -> None:
        self.readers = readers
        self.manifest = manifest or build_manifest()
        self.payload = payload
        self._boot_id: str | None = None
        #: the fault snapshot taken during ``collect`` (the in-run event observer diffs against exactly this one)
        self.fault_before: FaultSnapshot | None = None

    # ------------------------------------------------------------------------------------------- readings
    def _read_providers(self) -> tuple[dict[str, Observation], dict[str, Any]]:
        """One pass over the native providers. Failures become non-ok observations and ``unavailable`` coverage."""

        r = self.readers
        observations: dict[str, Observation] = {}
        raw: dict[str, Any] = {}
        for provider in r.providers:
            when, stamp = r.mono(), r.utc()
            try:
                reading = provider.read()
            except Exception as exc:  # noqa: BLE001 - recorded as a failed reading, never a guessed value
                for name in provider.fields:
                    target = OBSERVATION_FIELDS.get(name)
                    if target is not None:
                        observations[target[0]] = Observation(
                            target[0],
                            None,
                            target[1],
                            f"{provider.name} ({type(exc).__name__})",
                            when,
                            stamp,
                            "error",
                        )
                continue
            for name in provider.fields:
                target = OBSERVATION_FIELDS.get(name)
                if target is None:
                    continue
                state = reading.status.get(name, "missing")
                value = reading.values.get(name) if state == OK else None
                observations[target[0]] = Observation(
                    target[0],
                    value,
                    target[1],
                    reading.source,
                    when,
                    stamp,
                    "ok" if state == OK else state,
                )
                raw[name] = value
        return observations, raw

    def _coverage(self, observations: Mapping[str, Observation]) -> dict[str, str]:
        def available(*names: str) -> str:
            ok = all(n in observations and observations[n].status == "ok" for n in names)
            return "available" if ok else "unavailable"

        pagefile = self.readers.pagefile_free()
        return {
            "commit_headroom_bytes": available("commit_headroom_bytes", "commit_limit_bytes"),
            "ram_available_bytes": available("ram_available_bytes"),
            "vram_used_bytes": available("vram_used_bytes"),
            "vram_total_bytes": available("vram_total_bytes"),
            "gpu_temperature_c": available("gpu_temperature_c"),
            "gpu_device_present": available("gpu_device_present"),
            "pagefile_status": "available" if pagefile.status == "ok" else "unavailable",
            "forge_process_tree": "available"
            if self.readers.process_tree_capable()
            else "unavailable",
        }

    def acquire_baseline(
        self, device_id: str | None, boot_id: str | None
    ) -> QuiescentBaselineEvidence:
        """A quiescent window taken by THIS sampler (never an operator number), with runtime absence checked around it."""

        r = self.readers
        before = validate_process_conflicts(r.processes())
        samples: list[BaselineSample] = []
        end = r.mono() + r.baseline_seconds
        while True:
            now = r.mono()
            observed, _ = self._read_providers()

            samples.append(
                BaselineSample(
                    now,
                    _number(observed, "vram_used_bytes"),
                    _number(observed, "shared_vram_bytes"),
                    _number(observed, "gpu_utilization_percent"),
                )
            )
            if now >= end:
                break
            r.sleep(r.baseline_interval_s)
        after = validate_process_conflicts(r.processes())
        free = not [f for f in (*before, *after) if f.severity != "info"]
        unknown = any(f.code == "PROCESS_LIST_UNAVAILABLE" for f in (*before, *after))
        return QuiescentBaselineEvidence(
            samples=tuple(samples),
            device_id=device_id,
            boot_id=boot_id,
            acquired_by=BASELINE_PROVIDER,
            competing_runtime_free=None if unknown else free,
        )

    # --------------------------------------------------------------------------------------------- collect
    def collect(self) -> Collected:
        r = self.readers
        code = CodeRevision.from_probe(r.code_revision())
        semantics = verify_pinned_semantics(r.read_source)
        payload_findings = verify_payload(dict(self.payload.body), self.manifest)
        intent_findings = [
            *verify_intent(self.manifest.intent.request_fields(), self.manifest),
            *semantics,
            *payload_findings,
        ]
        # slow, time-insensitive evidence first (hashing the served files can take minutes)
        served = r.served_proof()
        isolation = r.isolation_findings()
        pin = r.pin_findings()
        launch = r.launch_findings()
        storage = r.storage_findings()
        fault_before = r.fault_snapshot()
        self.fault_before = fault_before
        boot_id = fault_before.boot_id if fault_before is not None else None
        self._boot_id = boot_id
        device_id = r.device_id()
        baseline = self.acquire_baseline(device_id, boot_id)
        port = validate_endpoint(r.port())
        processes = validate_process_conflicts(r.processes())
        # resource readings LAST: they are what the thresholds judge, so they must be the freshest
        observations, _ = self._read_providers()
        observations["pagefile_volume_free_bytes"] = r.pagefile_free()
        observations["evidence_volume_free_bytes"] = r.evidence_free()
        coverage = self._coverage(observations)
        fault_coverage: dict[str, str] | None = None
        if fault_before is not None:
            fault_coverage = {
                name: (
                    fault_before.sources[name].coverage
                    if name in fault_before.sources
                    else "not_collected"
                )
                for name in FAULT_SOURCES
            }
        sections: dict[str, list[Finding] | None] = {
            "assets": list(served.findings),
            "served": list(served.findings),
            "pin": pin,
            "intent": intent_findings,
            "isolation": [*isolation, *storage, *launch],
            "endpoint": port,
            "processes": processes,
        }
        inputs = PreflightInputs(
            manifest_digest=self.manifest.digest(),
            sections=sections,
            observations=observations,
            telemetry_coverage=coverage,
            fault_baseline_coverage=fault_coverage,
            residual_gpu_risk_accepted=None,
            evidence_dir_valid=r.evidence_dir_valid(),
            ledger_state=None,
            quiescent_baseline=baseline,
            launch_device_id=device_id,
            launch_boot_id=boot_id,
        )
        facts = {
            **dict(r.environment()),
            "semantics_findings": [f.code for f in semantics],
            "essential_telemetry": list(ESSENTIAL_TELEMETRY),
            "fault_baseline_accepted_coverage": list(ACCEPTED_BASELINE_COVERAGE),
            "code_state": code.state,
        }
        return Collected(
            inputs=inputs,
            code=code,
            fault_before=fault_before,
            boot_id=boot_id,
            device_id=device_id,
            workspace_ledger_state=r.workspace_ledger_state(),
            facts=facts,
        )

    def remeasure(self) -> Mapping[str, Observation]:
        """Fresh resource readings and the device identity, immediately before the claim."""

        r = self.readers
        observations, _ = self._read_providers()
        observations["pagefile_volume_free_bytes"] = r.pagefile_free()
        observations["evidence_volume_free_bytes"] = r.evidence_free()
        device = r.device_id()
        observations["gpu_device_id"] = Observation(
            "gpu_device_id",
            device,
            "id",
            "NVML board identity digest",
            r.mono(),
            r.utc(),
            "ok" if device else "missing",
        )
        return observations

    def recheck_served(self) -> list[Finding]:
        """The cheap size/mtime re-check against the full proof; unwired means refused, never silently fine."""

        return list(self.readers.served_unchanged())
