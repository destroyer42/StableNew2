"""D4 (154B): the isolated serving layout, served-file proof, launch profile and the manager-owned lifecycle adapter.

* The qualification layout lives outside the repository, the managed Forge install, the external A1111/Comfy trees and the
  original model library (the PR-154A validators decide). The three candidate files are separately verified COPIES: a source
  file is only ever opened for reading, never linked, renamed, re-attributed or exposed to the executable runtime.
* ``materialize_served_files`` is explicit and never called by import, a default command or a test (tests use temporary
  synthetic files). It never overwrites, repairs or deletes anything it did not create in the same call.
* The lifecycle authority is ``WebUIProcessManager`` through PR-IMG-115's ``OwnedForge``. This module adds NO process control:
  no signal, no kill, no taskkill and no PID acted upon outside the manager. A stop that cannot be completed by the manager
  is reported, with operator instructions, and the automation ends.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tools.qualification.img154.core import GIB, Finding
from tools.qualification.img154.isolation import QUALIFICATION_PORT, plan_layout
from tools.qualification.img154.manifest import (
    AssetSpec,
    FileMeasurement,
    QualificationManifest,
    build_manifest,
    verify_served_files,
)

CONFIG_VERSION_UID = (
    "PY313"  # Forge blocks on an interactive prompt without this marker (PR-IMG-115 evidence)
)
CHUNK = 8 << 20
EVIDENCE_RESERVE_BYTES = 2 * GIB
OUTPUT_RESERVE_BYTES = 1 * GIB

#: The complete, exact flag set of the isolated launch (PR-IMG-115's physically exercised set on this pin). Anything else, in
#: particular any model-directory or reference flag, is refused.
ALLOWED_LAUNCH_FLAGS = ("--uv", "--api", "--port", "--data-dir", "--skip-install")
#: Model-discovery and exposure flags that must never appear, whatever the contract's fragment list says.
FORBIDDEN_LAUNCH_FLAGS = (
    "--model-ref",
    "--forge-ref-a1111-home",
    "--ckpt-dir",
    "--vae-dir",
    "--lora-dir",
    "--embeddings-dir",
    "--text-encoder-dir",
    "--listen",
    "--share",
    "--nowebui",
    "--ui-config-file",
    "--ui-settings-file",
    "--config",
)


class RuntimePathError(ValueError):
    """A layout or launch input is outside the isolated qualification contract."""


# --------------------------------------------------------------------------------------------------------- layout


@dataclass(frozen=True)
class RuntimeLayout:
    root: str
    data_dir: str
    models_root: str
    evidence_dir: str
    outputs_dir: str
    runtime_dir: str
    model_home: str
    config_path: str
    served_paths: Mapping[str, str]
    model_directories: Mapping[str, str]  # role -> directory that must hold exactly that one file

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_dir": self.data_dir,
            "models_root": self.models_root,
            "evidence_dir": self.evidence_dir,
            "outputs_dir": self.outputs_dir,
            "served_paths": dict(self.served_paths),
        }


def _join(base: str, *names: str) -> str:
    return os.path.join(base, *names)


def plan_runtime_layout(
    root: str | os.PathLike[str], manifest: QualificationManifest | None = None
) -> RuntimeLayout:
    """Names only: this function creates nothing."""

    plan = manifest or build_manifest()
    base = os.fspath(root)
    named = plan_layout(base)
    models_root = _join(named["forge-data"], "models")
    served = {
        role: _join(models_root, spec.models_subdir, spec.filename)
        for role, spec in plan.assets.items()
    }
    directories = {
        role: _join(models_root, spec.models_subdir) for role, spec in plan.assets.items()
    }
    return RuntimeLayout(
        root=base,
        data_dir=named["forge-data"],
        models_root=models_root,
        evidence_dir=named["evidence"],
        outputs_dir=named["outputs"],
        runtime_dir=named["runtime"],
        model_home=named["model-home"],
        config_path=_join(named["forge-data"], "config.json"),
        served_paths=served,
        model_directories=directories,
    )


def storage_cost(manifest: QualificationManifest | None = None) -> dict[str, int]:
    plan = manifest or build_manifest()
    assets = sum(spec.size_bytes for spec in plan.assets.values())
    return {
        "assets_bytes": assets,
        "evidence_reserve_bytes": EVIDENCE_RESERVE_BYTES,
        "outputs_reserve_bytes": OUTPUT_RESERVE_BYTES,
        "required_bytes": assets + EVIDENCE_RESERVE_BYTES + OUTPUT_RESERVE_BYTES,
    }


def assess_storage(
    free_bytes: float | int | None, manifest: QualificationManifest | None = None
) -> list[Finding]:
    """Whether the volume that will hold three separate copies has room for them plus evidence and output."""

    cost = storage_cost(manifest)
    if (
        free_bytes is None
        or isinstance(free_bytes, bool)
        or not isinstance(free_bytes, int | float)
    ):
        return [
            Finding(
                "STORAGE_FREE_UNKNOWN",
                "inconclusive",
                "free space of the qualification volume is unknown",
            )
        ]
    if free_bytes != free_bytes or free_bytes < 0:
        return [Finding("STORAGE_FREE_INVALID", "inconclusive", "free space reading is invalid")]
    if free_bytes < cost["required_bytes"]:
        return [
            Finding(
                "STORAGE_INSUFFICIENT",
                "refuse",
                f"{cost['required_bytes'] / GIB:.1f} GiB are needed for separate copies, evidence and output",
            )
        ]
    return []


def expected_config_text() -> str:
    return json.dumps({"VERSION_UID": CONFIG_VERSION_UID}, indent=2, sort_keys=True)


# -------------------------------------------------------------------------------------------------------- hashing


def hash_stream(stream: Any, *, chunk: int = CHUNK) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for block in iter(lambda: stream.read(chunk), b""):
        digest.update(block)
        total += len(block)
    return digest.hexdigest(), total


def sha256_of(path: str | os.PathLike[str], *, chunk: int = CHUNK) -> tuple[str, int]:
    with open(path, "rb") as stream:
        return hash_stream(stream, chunk=chunk)


def _signature(path: str) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_size, info.st_mtime_ns


def _is_reparse(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _same_or_inside(path: str, parent: str) -> bool:
    child = os.path.normcase(os.path.realpath(path))
    base = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([child, base]) == base
    except ValueError:
        return False


# --------------------------------------------------------------------------------------------------- materialization


@dataclass(frozen=True)
class MaterializeResult:
    role: str
    action: str  # "copied" | "already_present_verified"
    path: str
    sha256: str
    size_bytes: int


def materialize_served_files(
    layout: RuntimeLayout,
    sources: Mapping[str, str | os.PathLike[str]],
    manifest: QualificationManifest | None = None,
) -> list[MaterializeResult]:
    """Copy each source into its served path, verifying size and full SHA-256 on the way in. Never overwrite.

    Each file is written to ``<target>.partial`` (created exclusively), verified, then atomically renamed. A source that is a
    link, escapes, lacks the frozen size or digest, or lies inside the qualification root is refused before anything is
    written, and every existing target is verified (never replaced) before the first copy. Each file is atomic on its own: a
    copy that fails verification leaves only a verified earlier file or nothing. Only the ``.partial`` file created by this call
    is removed on failure. Not called by import, tests or any default command.
    """

    plan = manifest or build_manifest()
    for role in plan.assets:
        if role not in sources:
            raise RuntimePathError(f"no source for {role!r}")
    # 1) validate everything before the first byte is written
    for role, spec in plan.assets.items():
        source = os.fspath(sources[role])
        target = layout.served_paths[role]
        if os.path.basename(source) != spec.filename:
            raise RuntimePathError(f"{role}: source name is not the frozen file name")
        if _is_reparse(source) or not os.path.isfile(source):
            raise RuntimePathError(f"{role}: source must be a plain file")
        if _same_or_inside(source, layout.root):
            raise RuntimePathError(f"{role}: source lies inside the qualification root")
        if os.path.getsize(source) != spec.size_bytes:
            raise RuntimePathError(f"{role}: source size differs from the frozen size")
        if not _same_or_inside(os.path.dirname(target), layout.root) or _is_reparse(
            os.path.dirname(target)
        ):
            raise RuntimePathError(f"{role}: target directory escapes the qualification root")
        if os.path.lexists(target + ".partial"):
            raise RuntimePathError(
                f"{role}: a partial file is present; it is not cleaned automatically"
            )
    # 2) existing targets are verified (never replaced) before the first copy, so a wrong one stops everything early
    verified_existing: dict[str, MaterializeResult] = {}
    for role, spec in plan.assets.items():
        target = layout.served_paths[role]
        if os.path.lexists(target):
            verified_existing[role] = _verify_existing(role, spec, target)
    results: list[MaterializeResult] = []
    for role, spec in plan.assets.items():
        if role in verified_existing:
            results.append(verified_existing[role])
        else:
            results.append(
                _materialize_one(role, spec, os.fspath(sources[role]), layout.served_paths[role])
            )
    return results


def _verify_existing(role: str, spec: AssetSpec, target: str) -> MaterializeResult:
    if _is_reparse(target) or not os.path.isfile(target):
        raise RuntimePathError(f"{role}: existing target is not a plain file")
    digest, size = sha256_of(target)
    if size != spec.size_bytes or digest != spec.sha256:
        raise RuntimePathError(
            f"{role}: an existing target has other bytes; it is not overwritten or repaired"
        )
    return MaterializeResult(role, "already_present_verified", target, digest, size)


def _materialize_one(role: str, spec: AssetSpec, source: str, target: str) -> MaterializeResult:
    if os.path.lexists(target):
        return _verify_existing(role, spec, target)
    Path(os.path.dirname(target)).mkdir(parents=True, exist_ok=True)
    partial = target + ".partial"
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        out_fd = os.open(partial, flags, 0o600)
        created = True
        digest = hashlib.sha256()
        total = 0
        with open(source, "rb") as reader, os.fdopen(out_fd, "wb") as writer:
            for block in iter(lambda: reader.read(CHUNK), b""):
                digest.update(block)
                total += len(block)
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        if total != spec.size_bytes or digest.hexdigest() != spec.sha256:
            raise RuntimePathError(f"{role}: the source bytes are not the frozen asset")
        verified, size = sha256_of(partial)
        if verified != spec.sha256 or size != spec.size_bytes:
            raise RuntimePathError(f"{role}: the copy does not verify")
        os.replace(partial, target)
        created = False
        return MaterializeResult(role, "copied", target, verified, size)
    finally:
        if created and os.path.lexists(partial):
            os.unlink(partial)  # only the partial this call created


def write_isolated_config(layout: RuntimeLayout) -> bool:
    """Create ``forge-data/config.json`` with the version marker if it does not exist. ``True`` when it was created."""

    path = layout.config_path
    if os.path.lexists(path):
        return False
    Path(layout.data_dir).mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
        stream.write(expected_config_text())
    return True


# ------------------------------------------------------------------------------------------------ served-file proof


@dataclass(frozen=True)
class ServedProof:
    measurements: Mapping[str, FileMeasurement | None]
    signatures: Mapping[str, tuple[int, int] | None]
    findings: tuple[Finding, ...]

    @property
    def verified(self) -> bool:
        return not self.findings


def verify_served_layout(
    layout: RuntimeLayout,
    manifest: QualificationManifest | None = None,
    *,
    hasher: Callable[[str], tuple[str, int]] = sha256_of,
) -> ServedProof:
    """Complete proof about the files Forge would actually load, at the paths it would load them from.

    Existence, plain file (no link/junction), realpath containment, a single hard link (no alias that could expose another
    library file), exact size and complete SHA-256, an unchanged signature across the hashing, exactly one file per
    discovery directory, and the expected config marker. Nothing is repaired.
    """

    plan = manifest or build_manifest()
    findings: list[Finding] = []
    measured: dict[str, FileMeasurement | None] = {}
    signatures: dict[str, tuple[int, int] | None] = {}
    for role, spec in plan.assets.items():
        path = layout.served_paths[role]
        directory = layout.model_directories[role]
        if not os.path.lexists(path):
            findings.append(
                Finding("SERVED_FILE_MISSING", "refuse", f"{role}: not present at the served path")
            )
            measured[role] = None
            signatures[role] = None
            continue
        if _is_reparse(path) or _is_reparse(directory) or not os.path.isfile(path):
            findings.append(
                Finding(
                    "SERVED_FILE_NOT_PLAIN",
                    "refuse",
                    f"{role}: served path is a link or not a file",
                )
            )
            measured[role] = None
            signatures[role] = None
            continue
        if not _same_or_inside(path, layout.root) or os.path.normcase(
            os.path.realpath(path)
        ) != os.path.normcase(os.path.abspath(path)):
            findings.append(
                Finding(
                    "SERVED_FILE_ESCAPES_ROOT",
                    "refuse",
                    f"{role}: realpath differs from the served path or leaves the root",
                )
            )
            measured[role] = None
            signatures[role] = None
            continue
        if os.stat(path).st_nlink > 1:
            findings.append(
                Finding(
                    "SERVED_FILE_ALIASED",
                    "refuse",
                    f"{role}: more than one hard link; isolation cannot be shown",
                )
            )
        before = _signature(path)
        try:
            digest, size = hasher(path)
        except OSError as exc:
            findings.append(
                Finding("SERVED_FILE_UNREADABLE", "refuse", f"{role}: {type(exc).__name__}")
            )
            measured[role] = None
            signatures[role] = before
            continue
        after = _signature(path)
        if before is None or after is None or before != after or size != after[0]:
            findings.append(
                Finding(
                    "SERVED_FILE_CHANGED_DURING_VERIFICATION",
                    "refuse",
                    f"{role}: file changed while it was hashed",
                )
            )
        measured[role] = FileMeasurement(spec.filename, size, digest, path)
        signatures[role] = after
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            entries = []
        if entries != [spec.filename]:
            findings.append(
                Finding(
                    "LAYOUT_UNEXPECTED_ENTRY",
                    "refuse",
                    f"{role}: the discovery directory must hold exactly the one frozen file",
                )
            )
    findings.extend(verify_served_files(measured, models_root=layout.models_root, manifest=plan))
    findings.extend(_config_findings(layout))
    return ServedProof(measured, signatures, tuple(findings))


def _config_findings(layout: RuntimeLayout) -> list[Finding]:
    path = layout.config_path
    if not os.path.lexists(path):
        return [
            Finding("CONFIG_MISSING", "inconclusive", "the isolated config marker is not present")
        ]
    if _is_reparse(path) or not os.path.isfile(path):
        return [Finding("CONFIG_NOT_PLAIN", "refuse", "the isolated config is not a plain file")]
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [Finding("CONFIG_UNREADABLE", "refuse", "the isolated config cannot be read")]
    if loaded != {"VERSION_UID": CONFIG_VERSION_UID}:
        return [
            Finding(
                "CONFIG_UNEXPECTED",
                "refuse",
                "the isolated config holds more than the version marker",
            )
        ]
    return []


def served_unchanged(
    proof: ServedProof, layout: RuntimeLayout, manifest: QualificationManifest | None = None
) -> list[Finding]:
    """A cheap re-check (size and modification time) that nothing changed after the full proof was made."""

    plan = manifest or build_manifest()
    findings: list[Finding] = []
    for role in plan.assets:
        recorded = proof.signatures.get(role)
        if recorded is None or _signature(layout.served_paths[role]) != recorded:
            findings.append(
                Finding(
                    "SERVED_FILE_CHANGED_AFTER_PROOF",
                    "refuse",
                    f"{role}: served file differs from the proven one",
                )
            )
    return findings


# ------------------------------------------------------------------------------------------------------ launch profile


@dataclass(frozen=True)
class LaunchProfile:
    command: tuple[str, ...]
    working_dir: str
    env_overrides: Mapping[str, str]
    endpoint: str
    port: int
    startup_timeout_seconds: float
    runtime_identity: str = "forge_webui"

    def as_runtime_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "working_dir": self.working_dir,
            "env_overrides": dict(self.env_overrides),
            "endpoint": self.endpoint,
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "runtime_identity": self.runtime_identity,
        }


def validate_launch(
    profile: LaunchProfile,
    layout: RuntimeLayout,
    install_dir: str,
    *,
    forbidden_fragments: Sequence[str] = (),
) -> list[Finding]:
    """Exact flags and values, loopback endpoint, isolated data and cache directories, neutralized inherited arguments."""

    findings: list[Finding] = []
    command = list(profile.command)
    expected_python = os.path.join(install_dir, "venv", "Scripts", "python.exe")
    if not command or os.path.normcase(command[0]) != os.path.normcase(expected_python):
        findings.append(
            Finding(
                "LAUNCH_INTERPRETER",
                "refuse",
                "the interpreter is not the managed install's venv python",
            )
        )
    if len(command) < 2 or command[1] != "launch.py":
        findings.append(Finding("LAUNCH_SCRIPT", "refuse", "the launch script is not launch.py"))
    flags = [part for part in command[2:] if part.startswith("--")]
    if sorted(flags) != sorted(ALLOWED_LAUNCH_FLAGS):
        findings.append(
            Finding("LAUNCH_FLAG_SET", "refuse", "the launch flags are not exactly the allowed set")
        )
    for flag in flags:
        lowered = flag.lower()
        if lowered in FORBIDDEN_LAUNCH_FLAGS or any(
            fragment in lowered for fragment in forbidden_fragments
        ):
            findings.append(
                Finding("LAUNCH_FLAG_FORBIDDEN", "refuse", f"forbidden launch flag {flag}")
            )
    values = {
        command[i]: command[i + 1]
        for i in range(2, len(command) - 1)
        if command[i].startswith("--")
    }
    if values.get("--port") != str(QUALIFICATION_PORT) or profile.port != QUALIFICATION_PORT:
        findings.append(
            Finding("LAUNCH_PORT", "refuse", "the port is not the frozen qualification port")
        )
    if os.path.normcase(values.get("--data-dir", "")) != os.path.normcase(layout.data_dir):
        findings.append(
            Finding(
                "LAUNCH_DATA_DIR",
                "refuse",
                "the data directory is not the isolated forge-data directory",
            )
        )
    if profile.endpoint != f"http://127.0.0.1:{QUALIFICATION_PORT}":
        findings.append(
            Finding(
                "LAUNCH_ENDPOINT",
                "refuse",
                "the endpoint is not the loopback qualification endpoint",
            )
        )
    if os.path.normcase(profile.working_dir) != os.path.normcase(
        os.path.join(install_dir, "source")
    ):
        findings.append(
            Finding(
                "LAUNCH_WORKING_DIR", "refuse", "the working directory is not the managed source"
            )
        )
    env = profile.env_overrides
    if env.get("COMMANDLINE_ARGS") != "":
        findings.append(
            Finding(
                "LAUNCH_ENV_COMMANDLINE_ARGS",
                "refuse",
                "inherited COMMANDLINE_ARGS must be neutralized",
            )
        )
    for key in ("HF_HUB_CACHE", "MPLCONFIGDIR", "YOLO_CONFIG_DIR", "UV_CACHE_DIR"):
        value = env.get(key)
        if not value or not _same_or_inside(value, layout.runtime_dir):
            findings.append(
                Finding(
                    "LAUNCH_ENV_CACHE",
                    "refuse",
                    f"{key} is not inside the isolated runtime directory",
                )
            )
    return findings


def build_isolated_launch_profile(
    layout: RuntimeLayout,
    install_dir: str | os.PathLike[str],
    *,
    port: int = QUALIFICATION_PORT,
    contract: Mapping[str, Any] | None = None,
) -> LaunchProfile:
    """The managed Forge's own interpreter, source and environment policy with every writable path redirected into the
    qualification root. Pure: it creates no directory (``prepare_runtime_dirs`` does, explicitly)."""

    if contract is None:
        from src.utils.managed_forge_runtime import load_manifest

        contract = load_manifest()
    install = os.fspath(install_dir)
    policy = contract["launch_policy"]
    command = (
        os.path.join(install, "venv", "Scripts", "python.exe"),
        str(policy.get("launch_script", "launch.py")),
        "--uv",
        "--api",
        "--port",
        str(port),
        str(policy.get("data_dir_flag", "--data-dir")),
        layout.data_dir,
        "--skip-install",
    )
    env = dict(policy["env"])
    runtime = layout.runtime_dir
    env.update(
        {
            "HF_HUB_CACHE": os.path.join(runtime, "hf"),
            "MPLCONFIGDIR": os.path.join(runtime, "matplotlib"),
            "YOLO_CONFIG_DIR": os.path.join(runtime, "yolo"),
            "UV_CACHE_DIR": os.path.join(runtime, "uv-cache"),
            # Forge appends COMMANDLINE_ARGS to its argv; an inherited value could name a model directory elsewhere.
            "COMMANDLINE_ARGS": "",
        }
    )
    return LaunchProfile(
        command=command,
        working_dir=os.path.join(install, "source"),
        env_overrides=env,
        endpoint=f"http://127.0.0.1:{port}",
        port=port,
        startup_timeout_seconds=300.0,
    )


def prepare_runtime_dirs(layout: RuntimeLayout) -> None:
    """Create the writable runtime directories (an explicit step; ``build_isolated_launch_profile`` stays pure)."""

    for name in ("hf", "matplotlib", "yolo", "uv-cache"):
        Path(os.path.join(layout.runtime_dir, name)).mkdir(parents=True, exist_ok=True)
    for directory in (layout.evidence_dir, layout.outputs_dir):
        Path(directory).mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------------------------------- ownership


class ProcessFacts(Protocol):
    """Read-only process facts (psutil in production, a fake in tests). It can describe processes; it cannot act on them."""

    def exists(self, pid: int) -> bool: ...

    def create_time(self, pid: int) -> float | None: ...

    def children(self, pid: int) -> list[int]: ...

    def listening_pids(self, port: int) -> list[int]: ...

    def cmdline(self, pid: int) -> tuple[str, ...]: ...


class PsutilProcessFacts:
    def exists(self, pid: int) -> bool:
        import psutil

        return bool(psutil.pid_exists(pid))

    def create_time(self, pid: int) -> float | None:
        import psutil

        try:
            return float(psutil.Process(pid).create_time())
        except psutil.Error:
            return None

    def children(self, pid: int) -> list[int]:
        import psutil

        try:
            return [child.pid for child in psutil.Process(pid).children(recursive=True)]
        except psutil.Error:
            return []

    def listening_pids(self, port: int) -> list[int]:
        import psutil

        pids: set[int] = set()
        try:
            for conn in psutil.net_connections(kind="inet"):
                if (
                    conn.status == psutil.CONN_LISTEN
                    and conn.laddr
                    and conn.laddr.port == port
                    and conn.pid
                ):
                    pids.add(int(conn.pid))
        except (psutil.Error, OSError):
            return []
        return sorted(pids)

    def cmdline(self, pid: int) -> tuple[str, ...]:
        import psutil

        try:
            return tuple(psutil.Process(pid).cmdline())
        except psutil.Error:
            return ()


@dataclass(frozen=True)
class OwnershipFacts:
    """What was verified about the owned process immediately before a runtime-changing operation."""

    owned: bool
    pid: int | None
    tree: tuple[int, ...] = ()
    listener_pids: tuple[int, ...] = ()
    endpoint_in_tree: bool = False
    start_time_unchanged: bool = False
    problems: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "owned": self.owned,
            "pid": self.pid,
            "tree": list(self.tree),
            "listener_pids": list(self.listener_pids),
            "endpoint_in_tree": self.endpoint_in_tree,
            "start_time_unchanged": self.start_time_unchanged,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class ShutdownResult:
    requested: bool
    succeeded: bool
    timed_out: bool
    verified: bool
    survivors: tuple[int, ...] = ()
    detail: str = ""

    @property
    def outcome(self) -> str:
        if not self.requested:
            return "not_attempted"
        if self.succeeded and self.verified and not self.survivors:
            return "verified_clean"
        if self.timed_out:
            return "timed_out"
        return "requested_unverified"

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "succeeded": self.succeeded,
            "timed_out": self.timed_out,
            "verified": self.verified,
            "survivors": list(self.survivors),
            "outcome": self.outcome,
            "detail": self.detail,
        }


RECOVERY_INSTRUCTIONS = (
    "The manager-owned shutdown did not complete. This harness has no other process authority and will not act further.",
    "1) Do not start another Forge, A1111 or Comfy process and do not retry this case.",
    "2) Inspect the owned process tree (the PIDs are recorded in the evidence) in Task Manager or Resource Monitor.",
    "3) Stop those processes yourself, by hand, only after confirming they belong to the qualification root.",
    "4) If the display is black or the machine is unresponsive, use the normal hardware power-cycle path; no software "
    "control can recover a hung GPU driver.",
    "5) After recovery, collect the evidence folder; the case is consumed and cannot be re-run under the same identity.",
)


class OwnedRuntime:
    """One manager-owned Forge for one case: start, verify ownership, stop. It acts only through ``OwnedForge``."""

    def __init__(
        self,
        profile: LaunchProfile,
        *,
        forge_factory: Callable[[dict[str, Any]], Any] | None = None,
        process_facts: ProcessFacts | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        stop_timeout_s: float = 90.0,
    ) -> None:
        self.profile = profile
        self._forge_factory = forge_factory
        self.facts = process_facts or PsutilProcessFacts()
        self._monotonic = monotonic
        self._stop_timeout_s = stop_timeout_s
        self._forge: Any = None
        self._root_pid: int | None = None
        self._root_created: float | None = None
        self.start_details: dict[str, Any] = {}

    # ------------------------------------------------------------------------------------------------ lifecycle
    def start(self) -> dict[str, Any]:
        """Start through the manager. Refuses if an owned process already exists; ownership is verified separately."""

        if self._forge is not None:
            raise RuntimePathError("this runtime has already been started; there is no restart")
        factory = self._forge_factory
        if factory is None:
            from tools.qualification.img115.runtime import OwnedForge

            factory = OwnedForge
        self._forge = factory(self.profile.as_runtime_dict())
        details = dict(self._forge.start())
        self._root_pid = details.get("pid") if isinstance(details.get("pid"), int) else None
        self._root_created = self.facts.create_time(self._root_pid) if self._root_pid else None
        self.start_details = {
            "pid": self._root_pid,
            "owns_process": bool(details.get("owns_process")),
            "started_at": details.get("started_at"),
        }
        return dict(self.start_details)

    def verify_ownership(self) -> OwnershipFacts:
        """The exact manager PID, its process tree and the endpoint listener, re-verified on every call."""

        problems: list[str] = []
        manager = getattr(self._forge, "manager", None)
        if self._forge is None or manager is None:
            return OwnershipFacts(False, None, problems=("no manager exists",))
        pid = self._root_pid
        if not bool(getattr(manager, "owns_process", False)):
            problems.append("manager does not report launch-session ownership")
        if pid is None or getattr(manager, "pid", None) != pid:
            problems.append("manager pid differs from the recorded owned pid")
        if pid is None or not self.facts.exists(pid):
            problems.append("owned root process does not exist")
        created = self.facts.create_time(pid) if pid is not None else None
        unchanged = (
            created is not None
            and self._root_created is not None
            and abs(created - self._root_created) < 1e-3
        )
        if not unchanged:
            problems.append("owned root process start time changed or is unknown (pid reuse)")
        tree = (pid, *self.facts.children(pid)) if pid is not None else ()
        listeners = tuple(self.facts.listening_pids(self.profile.port))
        in_tree = bool(listeners) and all(item in tree for item in listeners)
        if not listeners:
            problems.append("nothing listens on the qualification port")
        elif not in_tree:
            problems.append("a process outside the owned tree listens on the qualification port")
        return OwnershipFacts(
            not problems, pid, tree, listeners, in_tree, unchanged, tuple(problems)
        )

    def output_tail(self) -> dict[str, Any]:
        manager = getattr(self._forge, "manager", None)
        try:
            tails = manager.get_recent_output_tail(max_lines=60) if manager is not None else {}
        except Exception:  # noqa: BLE001 - evidence only
            return {}
        return {key: tails.get(key) for key in ("stdout_tail", "stderr_tail", "pid", "running")}

    def stop(self) -> ShutdownResult:
        """Ask the manager to stop its own process tree, with a deadline. Never signals or kills anything itself."""

        if self._forge is None:
            return ShutdownResult(False, False, False, False, detail="no runtime was started")
        root = self._root_pid
        before: tuple[int, ...] = ()
        if root is not None and self.facts.exists(root):
            before = (root, *self.facts.children(root))
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["result"] = self._forge.stop()
            except Exception as exc:  # noqa: BLE001 - reported as an unsuccessful stop
                outcome["error"] = type(exc).__name__

        worker = threading.Thread(target=run, name="img154b-owned-stop", daemon=True)
        worker.start()
        worker.join(self._stop_timeout_s)
        if worker.is_alive():
            return ShutdownResult(
                True, False, True, False, before, "the manager-owned stop did not return in time"
            )
        if "error" in outcome:
            return ShutdownResult(
                True, False, False, False, before, f"manager stop raised {outcome['error']}"
            )
        reported = outcome.get("result") or {}
        candidates = {
            *before,
            *(int(p) for p in reported.get("survivors", ()) if isinstance(p, int)),
        }
        survivors = tuple(sorted(pid for pid in candidates if self.facts.exists(pid)))
        # Verification needs an observation of the tree before the stop or of the root being gone afterwards.
        observed_gone = root is not None and not self.facts.exists(root)
        verified = (bool(before) or observed_gone) and not survivors
        return ShutdownResult(True, True, False, verified, survivors, "manager-owned stop returned")
