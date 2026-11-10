"""Read-only production view of the StableNew-managed ComfyUI runtime contract.

``config/managed_comfy_runtime.json`` owns the managed installation identity and launch policy.
This module lets the application use it: find the managed installation on disk, build the launch
command StableNew's own ``ComfyProcessManager`` would run (the same command the operator verifier
prints with ``--print-command``), and compare a configured ``comfy_command`` with the flags the
contract requires.

Nothing here writes settings, installs, downloads, starts or stops anything. Applying a detected
command is an explicit operator action in Engine Settings; an external ComfyUI is never adopted.
Only the standard library is imported, so detection is cheap and import-safe.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MANAGED_COMFY_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "managed_comfy_runtime.json"
)
#: Port used when the configured base URL does not name one (ComfyUI's own default).
DEFAULT_MANAGED_COMFY_PORT = 8188
_VERSION_PATTERN = re.compile(r'__version__\s*=\s*"([^"]+)"')
PINNED_MEMORY_FLAG = "--disable-pinned-memory"


class ManagedComfyContractError(ValueError):
    """The managed runtime contract is missing or does not have the expected shape."""


class UnsupportedConfiguredComfyFlag(ValueError):
    """A legacy launch command explicitly passes an unsupported optional switch."""


@dataclass(frozen=True)
class ManagedComfyContract:
    release: str
    version: str
    python_minor: str
    default_root: str
    default_runtime_dir: str
    listen: str
    required_flags: tuple[str, ...]
    runtime_folders: tuple[str, ...]
    extra_model_paths_file: str

    @property
    def install_dir_name(self) -> str:
        """``<release>-py<minor-without-dot>``, the layout the bootstrap script creates."""

        return f"{self.release}-py{self.python_minor.replace('.', '')}"


@dataclass(frozen=True)
class ManagedComfyDetection:
    """What was found for the managed installation, and the settings that would launch it."""

    contract: ManagedComfyContract
    install_dir: Path
    runtime_dir: Path
    problems: tuple[str, ...]
    command: tuple[str, ...] = ()
    workdir: str = ""
    base_url: str = ""

    @property
    def found(self) -> bool:
        return not self.problems

    def settings_updates(self) -> dict[str, Any]:
        """Engine settings that select this installation (only meaningful when ``found``)."""

        return {
            "comfy_command": list(self.command),
            "comfy_workdir": self.workdir,
            "comfy_base_url": self.base_url,
        }


@dataclass(frozen=True)
class ComfyLaunchAssessment:
    """How a configured ``comfy_command`` relates to the managed contract."""

    kind: str  # "none" | "managed" | "custom"
    missing_flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def flags_complete(self) -> bool:
        return self.kind != "none" and not self.missing_flags


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(str(value).replace("/", os.sep))).expanduser()


def load_managed_comfy_contract(
    path: Path = MANAGED_COMFY_MANIFEST_PATH,
) -> ManagedComfyContract:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManagedComfyContractError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ManagedComfyContractError(f"{path} must contain a JSON object")
    try:
        upstream = data["upstream"]
        python = data["python"]
        install = data["install"]
        policy = data["launch_policy"]
        return ManagedComfyContract(
            release=str(upstream["release"]),
            version=str(upstream["version"]),
            python_minor=str(python["minor"]),
            default_root=str(install["default_root"]),
            default_runtime_dir=str(policy["default_runtime_dir"]),
            listen=str(policy["listen"]),
            required_flags=tuple(str(flag) for flag in policy["required_flags"]),
            runtime_folders=tuple(str(folder) for folder in policy["runtime_folders"]),
            extra_model_paths_file=str(policy["extra_model_paths_file"]),
        )
    except (KeyError, TypeError) as exc:
        raise ManagedComfyContractError(f"{path} is missing a required field: {exc}") from exc


def _venv_python(install_dir: Path) -> Path:
    if os.name == "nt":
        return install_dir / "venv" / "Scripts" / "python.exe"
    return install_dir / "venv" / "bin" / "python"


def build_managed_launch_command(
    contract: ManagedComfyContract, *, install_dir: Path, runtime_dir: Path, port: int
) -> list[str]:
    """The launch command for the managed installation.

    Identical to ``tools/runtime/verify_managed_comfy.py --print-command`` (a test pins this).
    """

    command = [
        str(_venv_python(install_dir)),
        str(install_dir / "source" / "main.py"),
        "--listen",
        contract.listen,
        "--port",
        str(int(port)),
        "--input-directory",
        str(runtime_dir / "input"),
        "--output-directory",
        str(runtime_dir / "output"),
        "--temp-directory",
        str(runtime_dir / "temp"),
        "--user-directory",
        str(runtime_dir / "user"),
        "--extra-model-paths-config",
        str(runtime_dir / contract.extra_model_paths_file),
    ]
    command.extend(contract.required_flags)
    return command


def port_from_base_url(base_url: str | None) -> int:
    try:
        port = urlparse(str(base_url or "")).port
    except ValueError:
        port = None
    return int(port) if port else DEFAULT_MANAGED_COMFY_PORT


def detect_managed_comfy(
    contract: ManagedComfyContract,
    *,
    port: int = DEFAULT_MANAGED_COMFY_PORT,
    install_root: Path | None = None,
    runtime_dir: Path | None = None,
) -> ManagedComfyDetection:
    """Look for the managed installation the contract describes; read-only file checks only.

    This does not import Torch or run the installation; the full drift check stays with the
    operator verifier (``tools/runtime/verify_managed_comfy.py``).
    """

    root = install_root if install_root is not None else _expand(contract.default_root)
    install_dir = root / contract.install_dir_name
    resolved_runtime = (
        runtime_dir if runtime_dir is not None else _expand(contract.default_runtime_dir)
    )
    problems: list[str] = []
    if not install_dir.is_dir():
        problems.append(
            f"no managed ComfyUI {contract.release} installation at {install_dir} "
            "(build it with scripts/bootstrap_managed_comfy_windows.ps1)"
        )
    else:
        python = _venv_python(install_dir)
        if not python.is_file():
            problems.append(f"managed ComfyUI interpreter missing: {python}")
        main_py = install_dir / "source" / "main.py"
        if not main_py.is_file():
            problems.append(f"managed ComfyUI source missing: {main_py}")
        version_file = install_dir / "source" / "comfyui_version.py"
        reported = None
        if version_file.is_file():
            match = _VERSION_PATTERN.search(
                version_file.read_text(encoding="utf-8", errors="replace")
            )
            reported = match.group(1) if match else None
        if reported != contract.version:
            problems.append(
                f"managed ComfyUI source reports version {reported or 'unknown'}, "
                f"expected {contract.version}"
            )
    for folder in contract.runtime_folders:
        if not (resolved_runtime / folder).is_dir():
            problems.append(f"runtime folder missing: {resolved_runtime / folder}")
    if not (resolved_runtime / contract.extra_model_paths_file).is_file():
        problems.append(
            f"model path config missing: {resolved_runtime / contract.extra_model_paths_file}"
        )
    if problems:
        return ManagedComfyDetection(
            contract=contract,
            install_dir=install_dir,
            runtime_dir=resolved_runtime,
            problems=tuple(problems),
        )
    return ManagedComfyDetection(
        contract=contract,
        install_dir=install_dir,
        runtime_dir=resolved_runtime,
        problems=(),
        command=tuple(
            build_managed_launch_command(
                contract, install_dir=install_dir, runtime_dir=resolved_runtime, port=port
            )
        ),
        workdir=str(install_dir / "source"),
        base_url=f"http://{contract.listen}:{int(port)}",
    )


def missing_required_flags(command: Iterable[str], required: Iterable[str]) -> list[str]:
    present = set(command)
    return [flag for flag in required if flag not in present]


def with_required_flags(command: Sequence[str], required: Iterable[str]) -> list[str]:
    """``command`` with any missing required flag appended; existing arguments are kept as-is."""

    return [*command, *missing_required_flags(command, required)]


def assess_comfy_command(
    command: Sequence[str], contract: ManagedComfyContract
) -> ComfyLaunchAssessment:
    """Classify a configured command as none, the managed installation, or a custom command.

    "managed" means the interpreter is the venv of a ``<release>-py<minor>`` installation of
    this contract's release (under any root), which is how ``build_managed_launch_command``
    lays it out.
    """

    parts = [str(part) for part in command]
    if not parts:
        return ComfyLaunchAssessment(kind="none")
    interpreter = Path(parts[0])
    install_dir = interpreter.parent.parent.parent
    is_managed = (
        interpreter.parent.parent.name.casefold() == "venv"
        and install_dir.name.casefold() == contract.install_dir_name.casefold()
        and interpreter == _venv_python(install_dir)
    )
    kind = "managed" if is_managed else "custom"
    return ComfyLaunchAssessment(
        kind=kind, missing_flags=tuple(missing_required_flags(parts, contract.required_flags))
    )


def workflow_launch_requirements(
    command: Sequence[str],
    workflow_flags: Sequence[str],
    contract: ManagedComfyContract | None = None,
) -> tuple[str, ...]:
    """The workflow's switches plus the installation contract for the managed command."""

    if not command:
        return tuple(workflow_flags)
    contract = contract or load_managed_comfy_contract()
    managed_flags = (
        contract.required_flags if assess_comfy_command(command, contract).kind == "managed" else ()
    )
    return tuple(dict.fromkeys((*managed_flags, *workflow_flags)))


def plan_comfy_launch(
    command: Sequence[str], workdir: str | None, required: Sequence[str]
) -> tuple[str, ...]:
    """Resolve and verify a new argv without executing the interpreter, ComfyUI or custom nodes."""

    if not command:
        if not required:
            return ()
        raise ValueError(
            "External ComfyUI flags cannot be verified. Configure a StableNew-managed ComfyUI launch command."
        )

    check_configured_pin = PINNED_MEMORY_FLAG in command
    if not required and not check_configured_pin:
        return tuple(command)
    try:
        executable, parser_path, supported = _inspect_comfy_cli(command, workdir)
    except ValueError:
        if required:
            raise
        # Custom wrappers were already allowed for workflows without required switches.
        return tuple(command)
    unsupported = missing_required_flags(supported, required)
    if unsupported:
        raise ValueError(
            f"ComfyUI at {parser_path} does not support {' '.join(unsupported)}. "
            "Select a compatible ComfyUI installation."
        )
    if check_configured_pin and PINNED_MEMORY_FLAG not in supported:
        raise UnsupportedConfiguredComfyFlag(
            f"ComfyUI at {parser_path} does not support {PINNED_MEMORY_FLAG} in the launch command. "
            "Remove the unsupported flag for this workflow or select a compatible installation."
        )
    if not required:
        return tuple(command)
    return tuple(with_required_flags((str(Path(executable).absolute()), *command[1:]), required))


def _inspect_comfy_cli(command: Sequence[str], workdir: str | None) -> tuple[str, Path, set[str]]:
    # Inspect the parser next to the actual script, not a similarly named install or a wrapper
    # whose argument forwarding cannot be determined without running it.
    interpreter = Path(command[0])
    python_name = r"python(?:\d+(?:\.\d+)?)?(?:\.exe)?"
    executable = (
        shutil.which(command[0])
        if re.fullmatch(python_name, interpreter.name, re.IGNORECASE)
        else None
    )
    script_index = 1
    while script_index < len(command) and command[script_index] in {"-B", "-E", "-s", "-u"}:
        script_index += 1
    if (
        not executable
        or not re.fullmatch(python_name, Path(executable).name, re.IGNORECASE)
        or script_index >= len(command)
        or Path(command[script_index]).name != "main.py"
        or "--" in command[script_index + 1 :]
    ):
        raise ValueError(
            "Cannot verify ComfyUI support for required switches from this launch command. "
            "Configure a direct Python command for ComfyUI main.py with a valid interpreter."
        )

    cwd = Path(workdir or ".")
    if not cwd.is_dir():
        raise ValueError(
            f"ComfyUI launch directory {cwd} does not exist. Repair the selected install."
        )
    main = cwd / command[script_index]
    try:
        main = main.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"Cannot resolve the configured ComfyUI entrypoint {main}: {exc}."
        ) from exc
    parser_path = main.parent / "comfy" / "cli_args.py"
    try:
        entry = ast.parse(main.read_bytes(), filename=str(main))
        parser = ast.parse(parser_path.read_bytes(), filename=str(parser_path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(
            f"Cannot read ComfyUI's CLI at {parser_path}: {exc}. Repair the selected install."
        ) from exc
    if not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "comfy.cli_args"
        and any(alias.name == "args" for alias in node.names)
        for node in entry.body
    ):
        raise ValueError(
            f"{main} does not expose the ComfyUI CLI. Configure a direct ComfyUI launch."
        )
    supported: set[str] = set()
    for node in parser.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_argument"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "parser"
        ):
            continue
        if any(
            kw.arg == "action"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "store_true"
            for kw in call.keywords
        ):
            supported.update(
                arg.value
                for arg in call.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
    return executable, parser_path, supported


__all__ = [
    "DEFAULT_MANAGED_COMFY_PORT",
    "MANAGED_COMFY_MANIFEST_PATH",
    "ComfyLaunchAssessment",
    "ManagedComfyContract",
    "ManagedComfyContractError",
    "ManagedComfyDetection",
    "assess_comfy_command",
    "build_managed_launch_command",
    "detect_managed_comfy",
    "load_managed_comfy_contract",
    "missing_required_flags",
    "port_from_base_url",
    "with_required_flags",
]
