"""D10 (154B): the ONLY module that can reach a real runtime. DISABLED BY DEFAULT.

* ``preflight`` is read-only: it assembles the live preflight (native counters, the served-file proof, a 25-second quiescent
  window) and prints a disposition. It starts nothing, selects nothing, sends nothing and consumes no case.
* ``materialize`` copies the three verified files into the isolated layout (filesystem only; no process, no GPU).
* ``execute`` is the single-case physical run. It refuses unless EVERY activation gate holds (platform, not a test runner, an
  explicit environment opt-in, the exact case identity argument, an interactive terminal, a bound and unexpired owner
  authorization at the stable record location) and then still requires the operator to type the exact case phrase.

No other module imports this one; importing it performs no I/O. Nothing in this package writes the owner authorization.
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.qualification.img154 import probes
from tools.qualification.img154.core import Finding, Observation, digest
from tools.qualification.img154.evidence import (
    DurableJsonlWriter,
    FaultSnapshot,
    hash_files,
    redact_value,
)
from tools.qualification.img154.isolation import QUALIFICATION_PORT, RealFs, validate_isolation
from tools.qualification.img154.manifest import (
    QualificationManifest,
    build_manifest,
    verify_runtime_pin,
)
from tools.qualification.img154.preflight import PREPARED, PreflightPolicy, evaluate_preflight
from tools.qualification.img154b import collector as co
from tools.qualification.img154b import runtime as rt
from tools.qualification.img154b import sampler as sp
from tools.qualification.img154b.authorization import (
    OwnerAuthorization,
    read_authorization_text,
)
from tools.qualification.img154b.bundle import EvidenceBundle
from tools.qualification.img154b.case import (
    CaseConfig,
    CaseCoordinator,
    CasePorts,
    ClockPort,
    HttpResult,
    mint_physical_authority,
)
from tools.qualification.img154b.fence import (
    CaseFence,
    stable_record_root,
    workspace_ledger_state,
)
from tools.qualification.img154b.request import (
    OPTIONS_ENDPOINT,
    PROGRESS_ENDPOINT,
    TXT2IMG_ENDPOINT,
    FrozenPayload,
    build_txt2img_payload,
    forge_source_reader,
)

ACTIVATION_ENV = "STABLENEW_IMG154B_PHYSICAL"
ACTIVATION_VALUE = "ONE-CASE"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
ALLOWED_GET_PATHS = (OPTIONS_ENDPOINT, PROGRESS_ENDPOINT)
POST_BUDGET = {OPTIONS_ENDPOINT: 1, TXT2IMG_ENDPOINT: 1}
AUTHORIZATION_SUFFIX = ".owner-authorization.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------------------------------------- activation


@dataclass(frozen=True)
class ActivationRequest:
    platform: str
    env: Mapping[str, str]
    attempt_identity_arg: str | None
    expected_identity: str
    stdin_tty: bool
    stdout_tty: bool
    under_test_runner: bool
    authorization_present: bool


def evaluate_activation(request: ActivationRequest) -> list[str]:
    """Every reason the physical path must refuse. Empty means the gates pass; it is never a permission by itself."""

    reasons: list[str] = []
    if request.platform != "win32":
        reasons.append("PLATFORM_NOT_WINDOWS")
    if request.under_test_runner:
        reasons.append("UNDER_TEST_RUNNER")
    if request.env.get(ACTIVATION_ENV) != ACTIVATION_VALUE:
        reasons.append("ENVIRONMENT_OPT_IN_ABSENT")
    if request.attempt_identity_arg != request.expected_identity:
        reasons.append("ATTEMPT_IDENTITY_ARGUMENT_MISMATCH")
    if not (request.stdin_tty and request.stdout_tty):
        reasons.append("NOT_AN_INTERACTIVE_TERMINAL")
    if not request.authorization_present:
        reasons.append("OWNER_AUTHORIZATION_RECORD_ABSENT")
    return reasons


def under_test_runner(
    env: Mapping[str, str] | None = None, modules: Mapping[str, Any] | None = None
) -> bool:
    return "PYTEST_CURRENT_TEST" in (os.environ if env is None else env) or "pytest" in (
        sys.modules if modules is None else modules
    )


# ------------------------------------------------------------------------------------------------------------- HTTP


class HttpRefused(RuntimeError):
    """A request outside the single allowed set, or a repeat of a request whose budget is spent."""


class HttpClientPort:
    """Loopback-only HTTP with NO retry: a fresh connection per request, no redirects, no pooling, a hard request budget."""

    def __init__(
        self,
        port: int = QUALIFICATION_PORT,
        *,
        connection_factory: Callable[..., Any] = http.client.HTTPConnection,
        budget: Mapping[str, int] | None = None,
    ) -> None:
        if not 1024 <= int(port) <= 65535:
            raise ValueError("the qualification port must be in the user range")
        self.port = int(port)
        self._factory = connection_factory
        self._budget = dict(POST_BUDGET if budget is None else budget)
        self.sent: list[tuple[str, str]] = []

    def _exchange(self, method: str, path: str, body: bytes | None, timeout_s: float) -> HttpResult:
        started = time.monotonic()
        connection = self._factory("127.0.0.1", self.port, timeout=timeout_s)
        try:
            headers = {"Connection": "close", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE_BYTES + 1)
            elapsed = time.monotonic() - started
            if len(data) > MAX_RESPONSE_BYTES:
                return HttpResult(response.status, None, "response_too_large", elapsed)
            try:
                parsed = json.loads(data.decode("utf-8")) if data else None
            except (ValueError, UnicodeDecodeError):
                return HttpResult(response.status, None, "invalid_json", elapsed)
            return HttpResult(response.status, parsed, None, elapsed)
        except (OSError, http.client.HTTPException) as exc:
            return HttpResult(None, None, type(exc).__name__, time.monotonic() - started)
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass

    def get_json(self, path: str, *, timeout_s: float = 10.0) -> HttpResult:
        base = path.split("?", 1)[0]
        if base not in ALLOWED_GET_PATHS:
            raise HttpRefused(f"GET {base} is not an allowed observation")
        self.sent.append(("GET", base))
        return self._exchange("GET", path, None, timeout_s)

    def post_json(self, path: str, body: bytes, *, timeout_s: float) -> HttpResult:
        remaining = self._budget.get(path, 0)
        if remaining <= 0:
            raise HttpRefused(f"POST {path} is not allowed, or its single use is spent")
        self._budget[path] = (
            remaining - 1
        )  # spent BEFORE the send: an uncertain send is never re-attempted
        self.sent.append(("POST", path))
        return self._exchange("POST", path, body, timeout_s)


# ----------------------------------------------------------------------------------------------------- host readers


@dataclass
class HostConfig:
    root: Path
    install: Path
    models_root: Path | None
    reserve: tuple[str, ...] = ()
    manifest: QualificationManifest = field(default_factory=build_manifest)
    record_root: Path = field(default_factory=stable_record_root)


def environment_snapshot() -> dict[str, Any]:
    offset = datetime.now().astimezone().utcoffset()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timezone_utc_offset_minutes": int(offset.total_seconds() // 60)
        if offset is not None
        else None,
        "ci": bool(os.environ.get("CI")),
        "test_runner_active": under_test_runner(),
    }


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "StableNew" / "Qualification" / "IMG154B_ZIMAGE_TURBO_FP8"


def default_install() -> Path:
    from src.utils.managed_forge_runtime import load_manifest, managed_install_dir

    return managed_install_dir(load_manifest())


def harness_revision() -> dict[str, Any]:
    """154A's read-only Git/source identity extended with the 154B sources that actually execute."""

    info = dict(probes.collect_code_revision())
    harness = sorted(Path(__file__).parent.rglob("*.py"))
    hashes = {
        str(path.relative_to(REPO_ROOT)).replace("\\", "/"): hash_files([path])[path.name]
        for path in harness
    }
    info["source_sha256"] = digest({"img154": info.get("source_hashes", {}), "img154b": hashes})
    info["harness_hashes"] = hashes
    return info


def build_host_readers(
    config: HostConfig,
    payload: FrozenPayload,
    *,
    owned_pids: Callable[[], Sequence[int]] = lambda: (),
) -> tuple[co.HostReaders, rt.RuntimeLayout, sp.NvmlProvider, Callable[[], rt.ServedProof | None]]:
    """The real, read-only readers. Constructing them starts, selects and sends nothing."""

    plan = config.manifest
    layout = rt.plan_runtime_layout(config.root, plan)
    clocks = probes.Clocks()
    providers, nvml = sp.build_native_providers(owned_pids)
    proof_box: dict[str, rt.ServedProof] = {}

    def served_proof() -> rt.ServedProof:
        proof_box["proof"] = rt.verify_served_layout(layout, plan)
        return proof_box["proof"]

    def served_unchanged() -> list[Finding]:
        proof = proof_box.get("proof")
        if proof is None:
            return [Finding("SERVED_PROOF_MISSING", "refuse", "no served-file proof was made")]
        return rt.served_unchanged(proof, layout, plan)

    def isolation() -> list[Finding]:
        reserved = {
            "repository": str(REPO_ROOT),
            "managed_forge_install": str(config.install),
            "case_records": str(config.record_root),
        }
        if config.models_root is not None:
            reserved["model_library"] = str(config.models_root)
        reserved.update({f"reserved_{i}": value for i, value in enumerate(config.reserve)})
        return validate_isolation(str(config.root), reserved, RealFs(), manifest=plan)

    def pin() -> list[Finding]:
        marker: dict[str, Any] = {}
        try:
            marker = json.loads(
                (config.install / ".stablenew-managed-forge.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError):
            pass
        revision: str | None = None
        python_minor: str | None = None
        try:
            contract = json.loads(
                (REPO_ROOT / "config" / "managed_forge_runtime.json").read_text(encoding="utf-8")
            )
            revision = str(contract["upstream"]["revision"])
            python_minor = str(contract["python"]["minor"])
        except (OSError, ValueError, KeyError):
            pass
        findings = verify_runtime_pin(marker.get("revision"), marker.get("status"), revision, plan)
        if python_minor is None or str(marker.get("python")) != python_minor:
            findings.append(
                Finding(
                    "PIN_PYTHON_MISMATCH",
                    "refuse",
                    "the managed runtime marker's Python is not the contract's",
                )
            )
        return findings

    def launch() -> list[Finding]:
        from src.utils.managed_forge_runtime import load_manifest

        contract = load_manifest()
        profile = rt.build_isolated_launch_profile(layout, config.install, contract=contract)
        return rt.validate_launch(
            profile,
            layout,
            str(config.install),
            forbidden_fragments=tuple(
                contract["launch_policy"].get("forbidden_flag_fragments", ())
            ),
        )

    def storage() -> list[Finding]:
        if all(os.path.lexists(path) for path in layout.served_paths.values()):
            return []
        anchor = next((p for p in (config.root, *config.root.parents) if p.exists()), None)
        if anchor is None:
            return [
                Finding("STORAGE_FREE_UNKNOWN", "inconclusive", "no existing ancestor of the root")
            ]
        import shutil

        return rt.assess_storage(shutil.disk_usage(anchor).free, plan)

    def pagefile_free() -> Observation:
        found = {o.name: o for o in probes.probe_pagefile(clocks, probes.run_allow_listed)}
        return found.get(
            "pagefile_volume_free_bytes",
            Observation(
                "pagefile_volume_free_bytes", None, "bytes", "pagefile probe", None, None, "missing"
            ),
        )

    def evidence_dir_valid() -> bool | None:
        findings = isolation()
        if any(f.severity == "refuse" for f in findings):
            return False
        return (
            None if any(f.code == "ISOLATION_RESERVED_SET_INCOMPLETE" for f in findings) else True
        )

    def process_tree_capable() -> bool:
        try:
            from tools.qualification.vid160c.win_memory import read_process_memory

            return read_process_memory(os.getpid()) is not None
        except Exception:  # noqa: BLE001
            return False

    def device_id() -> str | None:
        try:
            return nvml.identify()
        except Exception:  # noqa: BLE001
            return None

    readers = co.HostReaders(
        code_revision=harness_revision,
        read_source=forge_source_reader(config.install / "source"),
        isolation_findings=isolation,
        pin_findings=pin,
        served_proof=served_proof,
        served_unchanged=served_unchanged,
        launch_findings=launch,
        storage_findings=storage,
        port=lambda: probes.probe_port(),
        processes=lambda: probes.probe_processes(),
        providers=providers,
        pagefile_free=pagefile_free,
        evidence_free=lambda: probes.probe_evidence_volume(clocks, layout.evidence_dir),
        fault_snapshot=lambda: probes.collect_fault_snapshot(clocks, probes.run_allow_listed),
        device_id=device_id,
        workspace_ledger_state=lambda: workspace_ledger_state(
            Path(layout.evidence_dir) / "dispatch-ledger.jsonl", plan
        ),
        process_tree_capable=process_tree_capable,
        evidence_dir_valid=evidence_dir_valid,
        mono=time.monotonic,
        utc=lambda: datetime.now(UTC).isoformat(),
        sleep=time.sleep,
        environment=environment_snapshot,
    )
    return readers, layout, nvml, lambda: proof_box.get("proof")


# --------------------------------------------------------------------------------------------------- read-only commands


def run_preflight(config: HostConfig) -> dict[str, Any]:
    """Assemble and evaluate the live preflight. Read-only; the case is not claimed and nothing is started."""

    payload = build_txt2img_payload(config.manifest)
    readers, layout, _, _ = build_host_readers(config, payload)
    collector = co.LiveCollector(readers, manifest=config.manifest, payload=payload)
    collected = collector.collect()
    inputs = collected.inputs
    fence = CaseFence(config.manifest, config.record_root, workspace_root=config.root)
    ledger = fence.state().preflight_state()
    inputs = replace(
        inputs,
        ledger_state=ledger
        if collected.workspace_ledger_state == "none"
        else collected.workspace_ledger_state,
    )
    decision = evaluate_preflight(
        inputs,
        now_mono_s=time.monotonic(),
        now_utc=datetime.now(UTC).isoformat(),
        policy=PreflightPolicy(),
        manifest=config.manifest,
    )
    return dict(
        redact_value(
            {
                "mode": "live_read_only_preflight",
                "decision": decision.decision,
                "prepared": decision.decision == PREPARED,
                "reason_codes": list(decision.reason_codes),
                "measurements": dict(decision.measurements),
                "pending_owner_decisions": list(decision.pending_owner_decisions),
                "code_revision": {"state": collected.code.state, "sha": collected.code.sha},
                "payload_digest": payload.payload_digest,
                "attempt_identity": config.manifest.attempt_identity(),
                "manifest_digest": config.manifest.digest(),
                "claimed": False,
                "started_anything": False,
                "statement": "A read-only observation. PREPARED_FOR_OWNER_REVIEW is not permission to run.",
            }
        )
    )


def run_materialize(config: HostConfig) -> list[dict[str, Any]]:
    """Copy the three verified files into the isolated layout (no process, no GPU). Refuses an unfit root first."""

    if config.models_root is None:
        raise rt.RuntimePathError("--models-root is required")
    plan = config.manifest
    layout = rt.plan_runtime_layout(config.root, plan)
    readers, _, _, _ = build_host_readers(config, build_txt2img_payload(plan))
    findings = [f for f in readers.isolation_findings() if f.severity == "refuse"]
    if findings:
        raise rt.RuntimePathError("isolation refused: " + ", ".join(f.code for f in findings))
    sources = {
        role: config.models_root / spec.models_subdir / spec.filename
        for role, spec in plan.assets.items()
    }
    results = rt.materialize_served_files(layout, sources, plan)
    rt.write_isolated_config(layout)
    rt.prepare_runtime_dirs(layout)
    return [
        {"role": r.role, "action": r.action, "sha256": r.sha256, "bytes": r.size_bytes}
        for r in results
    ]


# ----------------------------------------------------------------------------------------------------------- execute


def read_authorization(
    record_root: Path, manifest: QualificationManifest
) -> OwnerAuthorization | None:
    path = record_root / f"{manifest.attempt_identity()}{AUTHORIZATION_SUFFIX}"
    try:
        # utf-8-sig: an editor-added BOM must not turn a real record into "absent"; an undecodable file is simply unusable
        return read_authorization_text(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):  # AuthorizationError and UnicodeDecodeError are both ValueError
        return None


def interactive_confirm(summary: Mapping[str, Any]) -> str:
    shown = {k: v for k, v in summary.items() if k != "expected_phrase"}
    sys.stdout.write("EXACT SINGLE PHYSICAL CASE (one attempt, no retry, no replay)\n")
    sys.stdout.write(json.dumps(shown, indent=2, sort_keys=True) + "\n")
    sys.stdout.write(
        "Residual DIAG-GPU-130 hard-failure risk applies; no software can recover a hung GPU driver.\n"
    )
    # The assembled phrase is deliberately NOT printed: the operator composes it from the labelled values above.
    sys.stdout.write(
        "Type RUN-ONE-PHYSICAL-CASE followed by the case, manifest and payload values above, "
        "separated by single spaces, or anything else to refuse:\n> "
    )
    sys.stdout.flush()
    try:
        return sys.stdin.readline().strip()
    except (OSError, ValueError):
        return ""


def run_execute(config: HostConfig, attempt_identity_arg: str | None) -> int:
    plan = config.manifest
    authorization = read_authorization(config.record_root, plan)
    request = ActivationRequest(
        platform=sys.platform,
        env=os.environ,
        attempt_identity_arg=attempt_identity_arg,
        expected_identity=plan.attempt_identity(),
        stdin_tty=bool(getattr(sys.stdin, "isatty", lambda: False)()),
        stdout_tty=bool(getattr(sys.stdout, "isatty", lambda: False)()),
        under_test_runner=under_test_runner(),
        authorization_present=authorization is not None,
    )
    refusals = evaluate_activation(request)
    if refusals:
        sys.stderr.write("physical execution is disabled: " + ", ".join(refusals) + "\n")
        return 2
    payload = build_txt2img_payload(plan)
    layout = rt.plan_runtime_layout(config.root, plan)
    from src.utils.managed_forge_runtime import load_manifest

    profile = rt.build_isolated_launch_profile(layout, config.install, contract=load_manifest())
    runtime = rt.OwnedRuntime(profile)
    readers, _, _, _ = build_host_readers(
        config, payload, owned_pids=lambda: runtime.verify_ownership().tree
    )
    collector = co.LiveCollector(readers, manifest=plan, payload=payload)
    rt.prepare_runtime_dirs(layout)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(layout.evidence_dir) / f"case-{plan.attempt_identity()[:12]}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    fence = CaseFence(plan, config.record_root, workspace_root=config.root)
    clocks = probes.Clocks()

    def observe_new_fault_records() -> tuple[str, ...]:
        """New event-log records against the snapshot the preflight took (the same one the final classification uses)."""

        baseline = collector.fault_before
        if baseline is None:
            return (
                "fault_baseline_missing",
            )  # cannot verify: latched as an uncertain state by the monitor
        snapshot = probes.collect_fault_snapshot(clocks, probes.run_allow_listed)
        found: list[str] = []
        for name, source in snapshot.sources.items():
            known = baseline.sources.get(name)
            if known is None:
                continue
            found.extend(
                f"{name}:{record}" for record in sorted(source.record_ids - known.record_ids)
            )
        return tuple(found)

    def make_sampler(
        monitor: Any,
        writer: DurableJsonlWriter,
        stage: Callable[[], Any],
        endpoint: Callable[[], str],
    ) -> Any:
        # the SAME provider objects the preflight used (one NVML initialization, one PDH query per counter set), plus the
        # slow-cadence fault-event observer
        providers = [*readers.providers, sp.FaultEventProvider(observe_new_fault_records)]
        return sp.TelemetrySampler(
            providers,
            monitor,
            writer,
            stage=stage,
            endpoint=endpoint,
            owner=lambda: {
                "pid": runtime.start_details.get("pid"),
                "owns": runtime.start_details.get("owns_process"),
            },
        )

    def faults() -> FaultSnapshot | None:
        return probes.collect_fault_snapshot(clocks, probes.run_allow_listed)

    ports = CasePorts(
        collector=collector,
        fence=fence,
        runtime=runtime,
        http=HttpClientPort(QUALIFICATION_PORT),
        sampler_factory=make_sampler,
        faults=faults,
        confirm=interactive_confirm,
        passphrase=lambda: getpass.getpass("Owner passphrase (not echoed): "),
        clock=ClockPort(time.monotonic, lambda: datetime.now(UTC).isoformat(), time.sleep),
        bundle=EvidenceBundle(run_dir),
        sample_path=run_dir / "samples.jsonl",
        served_paths=layout.served_paths,
    )
    authority = mint_physical_authority(authorization.record_digest() if authorization else "")
    coordinator = CaseCoordinator(ports, manifest=plan, payload=payload, config=CaseConfig())
    try:
        report = coordinator.run(authority, authorization)
    finally:
        for (
            provider
        ) in readers.providers:  # release the PDH queries (the sampler's threads are daemons)
            close = getattr(provider, "close", None)
            if callable(close):
                close()
    summary = redact_value(report.as_dict())
    (run_dir / "case-report.redacted.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    sys.stdout.write(
        json.dumps({"result": summary["result"], "evidence": str(run_dir)}, indent=2) + "\n"
    )
    for line in report.recovery_instructions:
        sys.stderr.write(line + "\n")
    return 0 if report.result.is_pass else 1


# ------------------------------------------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="img154b.physical",
        description="PR-IMG-MODELS-154B physical qualification harness (DISABLED unless every activation gate holds).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("preflight", "read-only live preflight; starts and sends nothing"),
        ("materialize", "copy the three verified files into the isolated layout (filesystem only)"),
        ("execute", "ONE physical case; refuses unless every activation gate holds"),
    ):
        item = sub.add_parser(name, help=text)
        item.add_argument("--qualification-root", type=Path, default=None)
        item.add_argument("--forge-install", type=Path, default=None)
        item.add_argument("--models-root", type=Path, default=None)
        item.add_argument("--reserve", action="append", default=[])
        item.add_argument("--out", type=Path, default=None)
        if name == "materialize":
            item.add_argument(
                "--confirm-copy",
                action="store_true",
                help="acknowledge about 14.5 GB of file copies",
            )
        if name == "execute":
            item.add_argument("--attempt-identity", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = HostConfig(
        root=args.qualification_root or default_root(),
        install=args.forge_install or default_install(),
        models_root=args.models_root,
        reserve=tuple(args.reserve),
    )
    if args.command == "preflight":
        packet = run_preflight(config)
        text = json.dumps(packet, indent=2, sort_keys=True)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        sys.stdout.write(text + "\n")
        return 0 if packet["prepared"] else 1
    if args.command == "materialize":
        if not args.confirm_copy:
            sys.stderr.write("materialize copies about 14.5 GB; pass --confirm-copy to proceed\n")
            return 2
        sys.stdout.write(json.dumps(run_materialize(config), indent=2) + "\n")
        return 0
    return run_execute(config, args.attempt_identity)


if __name__ == "__main__":
    raise SystemExit(main())
