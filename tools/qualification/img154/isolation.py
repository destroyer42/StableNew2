"""D2: pure isolation, path-safety, port and process-ownership validation (never creates, links, starts or stops anything).

Filesystem facts come through the small ``FsFacts`` interface so every rule is exercised deterministically with a fake. The real
implementation (``RealFs``) only stats and resolves paths. Comparison is case-insensitive on purpose: for a refusal gate a false
overlap is safe and a missed one is not.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .core import Finding
from .manifest import QualificationManifest, build_manifest

QUALIFICATION_PORT = 7886  # unique, loopback only; distinct from the production Forge port 7871 and PR-IMG-115's 7885
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
#: Ports other StableNew runtimes use; the qualification endpoint must never be one of them.
RESERVED_PORTS = frozenset({*range(7860, 7870), 7871, 7885, 8188})

#: Path fragments that mean a root lives inside an application, runtime or library tree.
RESERVED_PATH_MARKERS = (
    ".venv",
    "stable-diffusion-webui",
    "comfyruntime",
    "managedcomfy",
    "site-packages",
)

RUNTIME_PROCESS_MARKERS = ("webui", "forge", "comfyui", "stable-diffusion")

#: Reserved trees the caller MUST name. Without them an "isolated" verdict would only mean "not inside the paths I was told".
REQUIRED_RESERVED_LABELS = ("repository", "managed_forge_install", "model_library")


class FsFacts(Protocol):
    def resolve(self, path: str) -> str: ...

    def is_absolute(self, path: str) -> bool: ...

    def is_reparse_point(self, path: str) -> bool: ...

    def exists(self, path: str) -> bool: ...

    def is_file(self, path: str) -> bool: ...

    def size(self, path: str) -> int | None: ...

    def volume(self, path: str) -> str: ...


class RealFs:
    """Read-only stat/resolve implementation; it never creates, writes or links anything."""

    def resolve(self, path: str) -> str:
        return os.path.realpath(path)

    def is_absolute(self, path: str) -> bool:
        return os.path.isabs(path)

    def is_reparse_point(self, path: str) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def is_file(self, path: str) -> bool:
        return os.path.isfile(path)

    def size(self, path: str) -> int | None:
        try:
            return os.stat(path).st_size
        except OSError:
            return None

    def volume(self, path: str) -> str:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if drive:
            return drive.lower()
        try:
            return str(os.stat(path).st_dev)
        except OSError:
            return "unknown"


def _parts(path: str) -> tuple[str, ...]:
    text = str(path).replace("\\", "/")
    return tuple(part.lower() for part in text.split("/") if part and part != ".")


def _within(child: tuple[str, ...], parent: tuple[str, ...]) -> bool:
    return bool(parent) and len(child) >= len(parent) and child[: len(parent)] == parent


def _sep(path: str) -> str:
    return "\\" if "\\" in path and "/" not in path else "/"


def _join(base: str, *names: str) -> str:
    return _sep(base).join([base.rstrip("/\\"), *names])


def _chain(path: str) -> list[str]:
    """Every ancestor path (string prefixes of the stated path), excluding a bare drive such as ``C:``."""

    pieces = str(path).split(_sep(str(path)))
    prefixes = [_sep(str(path)).join(pieces[:index]) for index in range(1, len(pieces) + 1)]
    return [
        prefix for prefix in prefixes if prefix and not (len(prefix) == 2 and prefix.endswith(":"))
    ]


def plan_layout(root: str) -> dict[str, str]:
    """The future qualification layout (names only; this function creates nothing)."""

    return {
        name: _join(str(root), name)
        for name in ("assets", "forge-data", "evidence", "outputs", "runtime", "model-home")
    }


def _overlap(mine: set[tuple[str, ...]], theirs: set[tuple[str, ...]]) -> str | None:
    """``inside`` when ``mine`` equals or lies within ``theirs``; ``contains`` when it holds ``theirs``; else ``None``."""

    for own in mine:
        for other in theirs:
            if not other:
                continue
            if own == other or _within(own, other):
                return "inside"
            if _within(other, own):
                return "contains"
    return None


def validate_isolation(
    root: str,
    reserved: Mapping[str, str],
    fs: FsFacts,
    *,
    manifest: QualificationManifest | None = None,
    source_paths: Mapping[str, str] | None = None,
    required_reserved: Sequence[str] = REQUIRED_RESERVED_LABELS,
) -> list[Finding]:
    """Refuse a qualification root that overlaps (in EITHER direction) any reserved tree, or escapes through a link.

    ``reserved`` maps a label to a path: repository and worktrees, managed Forge install, A1111/Comfy, model libraries,
    application environments, other user-state directories. ``source_paths`` are where the candidate files are today (for
    the same-volume hardlink assumption). Nothing is created, resolved on disk beyond a read, or modified.
    """

    plan = manifest or build_manifest()
    findings: list[Finding] = []
    stated = str(root)
    if not fs.is_absolute(stated):
        return [
            Finding(
                "ISOLATION_ROOT_NOT_ABSOLUTE",
                "refuse",
                "qualification root must be an absolute path",
            )
        ]
    stated_parts = _parts(stated)
    if len(stated_parts) <= 1:
        findings.append(
            Finding(
                "ISOLATION_ROOT_COLLISION",
                "refuse",
                "qualification root is a drive or filesystem root",
            )
        )
        return findings
    resolved = fs.resolve(stated)
    resolved_parts = _parts(resolved)

    for prefix in _chain(stated):
        if fs.exists(prefix) and fs.is_reparse_point(prefix):
            findings.append(
                Finding(
                    "ISOLATION_REPARSE_ESCAPE", "refuse", "a path component is a link or junction"
                )
            )
            break
    else:
        if resolved_parts != stated_parts:
            findings.append(
                Finding(
                    "ISOLATION_REPARSE_ESCAPE",
                    "refuse",
                    "the root resolves to a different location than stated",
                )
            )

    missing = [label for label in required_reserved if label not in reserved]
    if missing:
        findings.append(
            Finding(
                "ISOLATION_RESERVED_SET_INCOMPLETE",
                "inconclusive",
                "reserved trees not named: " + ", ".join(missing),
            )
        )

    for label, other in reserved.items():
        relation = _overlap(
            {stated_parts, resolved_parts}, {_parts(str(other)), _parts(fs.resolve(str(other)))}
        )
        if relation == "inside":
            findings.append(
                Finding(
                    "ISOLATION_INSIDE_RESERVED", "refuse", f"root is inside or equal to {label}"
                )
            )
        elif relation == "contains":
            findings.append(
                Finding("ISOLATION_CONTAINS_RESERVED", "refuse", f"root contains {label}")
            )

    lowered = "/".join(resolved_parts)
    for marker in RESERVED_PATH_MARKERS:
        if marker in lowered:
            findings.append(
                Finding("ISOLATION_RESERVED_MARKER", "refuse", f"root path contains {marker!r}")
            )

    models_root = _join(plan_layout(stated)["forge-data"], "models")
    for role, spec in plan.assets.items():
        target = _join(models_root, spec.models_subdir, spec.filename)
        for prefix in (models_root, _join(models_root, spec.models_subdir)):
            if fs.exists(prefix) and fs.is_reparse_point(prefix):
                findings.append(
                    Finding(
                        "ISOLATION_LAYOUT_REPARSE", "refuse", f"{role}: layout directory is a link"
                    )
                )
        if fs.exists(target):
            if fs.is_reparse_point(target) or not fs.is_file(target):
                findings.append(
                    Finding(
                        "ISOLATION_TARGET_NOT_PLAIN_FILE",
                        "refuse",
                        f"{role}: existing target is not a plain file",
                    )
                )
            elif fs.size(target) != spec.size_bytes:
                findings.append(
                    Finding(
                        "ISOLATION_TARGET_SIZE_MISMATCH",
                        "refuse",
                        f"{role}: existing target has other bytes",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "ISOLATION_TARGET_EXISTS_UNVERIFIED",
                        "inconclusive",
                        f"{role}: existing target needs a full hash",
                    )
                )
        source = (source_paths or {}).get(role)
        if source is not None and fs.volume(source) != fs.volume(models_root):
            findings.append(
                Finding(
                    "ISOLATION_CROSS_VOLUME_HARDLINK",
                    "refuse",
                    f"{role}: source and served directory are on different volumes; a same-volume link cannot be assumed",
                )
            )
    return findings


# ----------------------------------------------------------------------------------------------- port and processes


@dataclass(frozen=True)
class PortObservation:
    host: str
    port: int
    state: str  # "free" | "occupied" | "unverifiable"
    source: str = "unspecified"
    observed_mono_s: float | None = None


def validate_endpoint(
    observation: PortObservation | None, *, expected_port: int = QUALIFICATION_PORT
) -> list[Finding]:
    if observation is None:
        return [
            Finding("PORT_NOT_OBSERVED", "inconclusive", "the qualification port was not observed")
        ]
    findings: list[Finding] = []
    if observation.host not in LOOPBACK_HOSTS:
        findings.append(
            Finding("PORT_NOT_LOOPBACK", "refuse", "the endpoint must be the loopback address")
        )
    if observation.port != expected_port:
        findings.append(
            Finding(
                "PORT_NOT_FROZEN",
                "refuse",
                "the observed port is not the frozen qualification port",
            )
        )
    if not 1024 <= observation.port <= 65535 or observation.port in RESERVED_PORTS:
        findings.append(
            Finding(
                "PORT_RESERVED",
                "refuse",
                "the port is outside the user range or reserved by another runtime",
            )
        )
    if observation.state == "occupied":
        findings.append(
            Finding("RUNTIME_PORT_OCCUPIED", "refuse", "the qualification port is already in use")
        )
    elif observation.state != "free":
        findings.append(
            Finding(
                "RUNTIME_PORT_UNVERIFIED", "inconclusive", "the port state could not be established"
            )
        )
    return findings


@dataclass(frozen=True)
class ProcessObservation:
    pid: int
    name: str
    cmdline: tuple[str, ...] = ()
    listening_ports: tuple[int, ...] = ()
    owner: str = "unknown"  # "stablenew_manager" | "external" | "unknown"


def looks_like_runtime(process: ProcessObservation) -> bool:
    """Conservative: a WebUI/Forge/Comfy-looking command line, or a listener on any other runtime's reserved port."""

    text = " ".join((process.name, *process.cmdline)).lower()
    if any(marker in text for marker in RUNTIME_PROCESS_MARKERS):
        return True
    return any(port in RESERVED_PORTS for port in process.listening_ports)


def validate_process_conflicts(
    processes: Sequence[ProcessObservation] | None, *, port: int = QUALIFICATION_PORT
) -> list[Finding]:
    """Refuse on any competing or unowned runtime. This only ever REPORTS: no process is adopted, stopped or signalled."""

    if processes is None:
        return [
            Finding(
                "PROCESS_LIST_UNAVAILABLE", "inconclusive", "the process list could not be read"
            )
        ]
    findings: list[Finding] = []
    for process in processes:
        if port in process.listening_ports:
            findings.append(
                Finding(
                    "RUNTIME_PORT_LISTENER",
                    "refuse",
                    f"pid {process.pid} listens on the qualification port",
                )
            )
        if looks_like_runtime(process):
            code = (
                "RUNTIME_CONFLICT_FOREIGN_OWNER"
                if process.owner != "stablenew_manager"
                else "RUNTIME_CONFLICT_PRESENT"
            )
            findings.append(
                Finding(
                    code,
                    "refuse",
                    f"pid {process.pid} ({process.name}) looks like a competing runtime",
                )
            )
    return findings


@dataclass(frozen=True)
class OwnershipPlan:
    """Documentation of who may control a future process. This package controls nothing."""

    lifecycle_authority: str = (
        "WebUIProcessManager (future PR-IMG-MODELS-154B; not instantiated here)"
    )
    sole_owner_required: bool = True
    observer_may_control_process: bool = False
    external_runtime_adoption: bool = False
    termination_performed_by_this_package: bool = False
    notes: tuple[str, ...] = field(
        default=(
            "An instrumentation observer is never an owner.",
            "An external runtime is never adopted, terminated or restarted.",
            "A watchdog cannot recover a GPU driver hang, black screen or machine reset.",
        )
    )


def repository_roots_to_reserve(
    repo_root: Path | str, worktrees: Sequence[Path | str]
) -> dict[str, str]:
    """Label every repository checkout so a qualification root can be refused inside any of them."""

    reserved = {"repository": str(repo_root)}
    for index, tree in enumerate(worktrees):
        reserved[f"worktree_{index}"] = str(tree)
    return reserved
