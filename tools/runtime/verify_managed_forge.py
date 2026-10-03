"""Verify (read-only) a StableNew-managed Forge Neo installation against its runtime contract.

``config/managed_forge_runtime.json`` owns the installation identity (exact Forge and ADetailer-Neo
revisions, Python, Torch, launch policy, StableNew-owned runtime dirs, YOLO detectors, external model
references) and points at one exact, COMPLETE package lock. This module checks an installation on disk
against that contract and prints the launch profile for ``WebUIProcessManager``. It never writes,
installs, downloads or starts anything and touches no process; the lifecycle authority stays
``WebUIProcessManager``. Run it with the managed venv's interpreter so package metadata is the venv's.

The accepted upstream dependency graph is internally inconsistent (gradio 4.40.0 vs pillow 12.3.0). The
contract declares that single conflict; ``pip check`` must report exactly it and nothing else. Any other
line, or the disappearance of the declared one, is MANAGED_FORGE_DRIFT.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config" / "managed_forge_runtime.json"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MINOR = re.compile(r"^3\.\d{1,2}$")
_VERSION_UID = re.compile(r"""^VERSION_UID\s*(?::[^=\n]+)?=\s*["']([^"']+)["']""", re.MULTILINE)
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\S+)\s*(?:#.*)?$")
_URL_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)\s*@\s*(\S+)\s+#\s*version=(\S+)\s*$")
DRIFT = "MANAGED_FORGE_DRIFT"


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def validate_manifest(
    manifest: dict[str, Any], *, root: Path = ROOT, require_constraints_file: bool = True
) -> list[str]:
    """Problems with the contract itself (shape, exactness, no mutable refs, one declared conflict)."""

    problems: list[str] = []
    if manifest.get("schema_version") != 1:
        problems.append("schema_version must be 1")
    if manifest.get("runtime_identity") != "forge_webui":
        problems.append("runtime_identity must be forge_webui")
    for key in ("upstream", "adetailer_neo"):
        section = manifest.get(key) or {}
        if not _SHA40.match(str(section.get("revision", ""))):
            problems.append(f"{key}.revision must be a full 40-hex commit SHA (never a branch)")
        if not str(section.get("repository", "")).startswith("https://github.com/"):
            problems.append(f"{key}.repository must be an https GitHub URL")
    python = manifest.get("python") or {}
    if not _MINOR.match(str(python.get("minor", ""))):
        problems.append("python.minor must be a single minor version like 3.13")
    if python.get("free_threaded") is not False or python.get("jit") is not False:
        problems.append("python must be the standard-GIL build with the JIT off")
    torch = manifest.get("torch") or {}
    for key in ("torch", "torchvision"):
        if not str(torch.get(key, "")).endswith("+cu130"):
            problems.append(f"torch.{key} must be an exact +cu130 build")
    if torch.get("cuda") != "13.0":
        problems.append("torch.cuda must be 13.0")
    constraints = str(manifest.get("constraints", ""))
    if "windows-py314" in constraints or not constraints.startswith("constraints/forge-"):
        problems.append("constraints must be the Forge authority, not the application or Comfy constraints")
    elif require_constraints_file and not (root / constraints).is_file():
        problems.append(f"constraints file missing: {constraints}")
    conflicts = manifest.get("known_conflicts") or []
    if len(conflicts) != 1 or {c.get("package") for c in conflicts} != {"gradio"}:
        problems.append("known_conflicts must declare exactly the one accepted gradio/pillow conflict")
    for conflict in conflicts:
        if not all(conflict.get(k) for k in ("package", "version", "requires", "dependency", "installed")):
            problems.append("a known conflict must carry package, version, requires, dependency and installed")
    config = manifest.get("config") or {}
    if not str((config.get("required_settings") or {}).get("VERSION_UID", "")).strip() or not config.get("version_uid_source"):
        problems.append("config must declare required_settings.VERSION_UID and the version_uid_source that defines it")
    budget = (manifest.get("install") or {}).get("path_budget") or {}
    if not all(isinstance(budget.get(k), int) and budget[k] > 0 for k in ("max_venv_relative_path", "windows_path_limit")):
        problems.append("install.path_budget must declare max_venv_relative_path and windows_path_limit")
    policy = manifest.get("launch_policy") or {}
    required = set(policy.get("required_flags") or [])
    if not {"--api", "--skip-install", "--ad-no-huggingface"} <= required:
        problems.append("launch_policy must require --api, --skip-install and --ad-no-huggingface")
    if policy.get("model_reference_flag") != "--forge-ref-a1111-home":
        problems.append("launch_policy.model_reference_flag must be --forge-ref-a1111-home")
    if (manifest.get("extensions") or {}).get("allowed") != ["adetailer-neo"]:
        problems.append("extensions.allowed must be exactly ['adetailer-neo']")
    files = (manifest.get("detectors") or {}).get("files") or {}
    if set(files) != {"face_yolov8n.pt", "hand_yolov8n.pt"} or not all(_SHA256.match(str(v)) for v in files.values()):
        problems.append("detectors.files must be exactly the two YOLO files with sha256 hashes")
    models = (manifest.get("models") or {}).get("files") or {}
    if set(models) != {"checkpoint", "lora", "upscaler"} or not all(_SHA256.match(str(m.get("sha256", ""))) for m in models.values()):
        problems.append("models.files must identify the checkpoint, LoRA and upscaler by sha256")
    return problems


# --- package lock ---------------------------------------------------------------------------------


def parse_lock(text: str) -> dict[str, str]:
    """``{normalized name: exact version}``; a direct-URL line carries its version in ``# version=``."""

    pins: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN.match(line)
        if match:
            name, version = normalize_name(match.group(1)), match.group(2)
        else:
            url = _URL_PIN.match(line)
            if not url or "#sha256=" not in url.group(2):
                raise ValueError(f"line {number}: not an exact pin or a hash-pinned direct URL: {line!r}")
            name, version = normalize_name(url.group(1)), url.group(3)
        if name in pins:
            raise ValueError(f"line {number}: duplicate pin for {name}")
        pins[name] = version
    return pins


def check_lock(lock: dict[str, str], manifest: dict[str, Any]) -> list[str]:
    problems = []
    if len(lock) != manifest.get("package_count"):
        problems.append(f"lock has {len(lock)} pins, the contract declares {manifest.get('package_count')}")
    for key in ("torch", "torchvision"):
        if lock.get(key) != manifest["torch"][key]:
            problems.append(f"lock pins {key} {lock.get(key)}, expected {manifest['torch'][key]}")
    for forbidden in ("mediapipe", "xformers", "sageattention", "flash-attn"):
        if forbidden in lock:
            problems.append(f"{forbidden} must not be in the accepted package set")
    return problems


def installed_versions() -> dict[str, str]:
    return {
        normalize_name(dist.metadata["Name"]): dist.version
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }


def check_packages(lock: dict[str, str], installed: dict[str, str]) -> list[str]:
    """The installed set equals the lock: nothing missing, nothing extra, every version exact."""

    problems = [
        f"[{DRIFT}] {name}: missing (expected {version})" for name, version in sorted(lock.items()) if name not in installed
    ]
    problems += [
        f"[{DRIFT}] {name}: installed {installed[name]}, expected {version}"
        for name, version in sorted(lock.items())
        if name in installed and installed[name] != version
    ]
    problems += [
        f"[{DRIFT}] {name}=={version} is installed but not in the lock"
        for name, version in sorted(installed.items())
        if name not in lock
    ]
    return problems


def _conflict_line(conflict: dict[str, Any]) -> str:
    return (
        f"{conflict['package']} {conflict['version']} has requirement {conflict['requires']}, "
        f"but you have {conflict['dependency']} {conflict['installed']}."
    )


def evaluate_pip_check(output: str, conflicts: list[dict[str, Any]]) -> list[str]:
    """Accept ONLY the declared conflict lines; anything else (or a vanished declared line) is drift."""

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    lines = [line for line in lines if line != "No broken requirements found."]
    declared = [_conflict_line(c) for c in conflicts]
    problems = [f"[{DRIFT}] pip check: unexpected dependency problem: {line}" for line in lines if line not in declared]
    for line in declared:
        if line not in lines:
            problems.append(
                f"[{DRIFT}] pip check no longer reports the declared conflict ({line}); the accepted runtime "
                "differs from its frozen contract. Stop: do not silently redefine it."
            )
    return problems


def run_pip_check() -> str:
    done = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, check=False)
    return (done.stdout or "") + (done.stderr or "")


# --- interpreter, sources, tree, config, detectors ----------------------------------------------------


def check_python(manifest: dict[str, Any]) -> list[str]:
    problems = []
    expected = str(manifest["python"]["minor"])
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual != expected:
        problems.append(f"python {actual} is not the supported {expected}")
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        problems.append("the free-threaded Python build is not supported")
    if os.environ.get("PYTHON_JIT", "0") not in ("", "0"):
        problems.append("the experimental Python JIT (PYTHON_JIT) must not be enabled")
    return problems


def _git(source: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def check_source(source: Path, *, revision: str, repository: str, label: str) -> list[str]:
    """The checkout is exactly the pinned revision from the pinned repository and has no local changes."""

    if not source.is_dir():
        return [f"[{label}] source directory missing: {source}"]
    problems = []
    try:
        head = _git(source, "rev-parse", "HEAD")
        if head != revision:
            problems.append(f"[{DRIFT}] [{label}] source revision {head} is not the pinned {revision}")
        if _git(source, "status", "--porcelain"):
            problems.append(f"[{DRIFT}] [{label}] source checkout is not clean (modified or untracked files)")
        origin = _git(source, "remote", "get-url", "origin").removesuffix(".git").rstrip("/")
        if origin.lower() != repository.removesuffix(".git").rstrip("/").lower():
            problems.append(f"[{label}] origin {origin} is not the pinned repository {repository}")
    except (RuntimeError, OSError) as exc:
        problems.append(f"[{label}] source is not a readable git checkout: {exc}")
    return problems


def check_extensions(data_dir: Path, manifest: dict[str, Any]) -> list[str]:
    folder = data_dir / "extensions"
    if not folder.is_dir():
        return [f"extensions directory missing: {folder}"]
    allowed = set(manifest["extensions"]["allowed"])
    ignored = set(manifest["extensions"].get("ignored_entries") or [])
    present = {entry.name for entry in folder.iterdir() if entry.name not in ignored}
    problems = [f"[{DRIFT}] unexpected extension: {name}" for name in sorted(present - allowed)]
    problems += [f"[{DRIFT}] required extension missing: {name}" for name in sorted(allowed - present)]
    return problems


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_detectors(data_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Exactly the two accepted YOLO detectors, by hash; no MediaPipe or other detector files."""

    folder = data_dir / "models" / "adetailer"
    if not folder.is_dir():
        return [f"detector directory missing: {folder}"]
    expected = manifest["detectors"]["files"]
    present = {entry.name for entry in folder.iterdir() if entry.is_file()}
    problems = [f"[{DRIFT}] unexpected detector file: {name}" for name in sorted(present - set(expected))]
    for name, digest in expected.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"[{DRIFT}] detector missing: {name}")
        elif sha256_file(path) != digest:
            problems.append(f"[{DRIFT}] detector {name} does not match its accepted sha256")
    return problems


def check_path_budget(install_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """The venv prefix leaves room for the deepest accepted package path (Windows long paths are off by default)."""

    budget = manifest["install"]["path_budget"]
    worst = len(str(install_dir / "venv")) + budget["max_venv_relative_path"]
    if worst > budget["windows_path_limit"]:
        return [f"install path is too long: the deepest package file would be {worst} characters (limit {budget['windows_path_limit']}); use a shorter install root"]
    return []


def check_runtime_dirs(install_dir: Path, manifest: dict[str, Any]) -> list[str]:
    wanted = [install_dir / "source", install_dir / "venv", install_dir / "data" / "models"]
    wanted += [install_dir / rel for rel in manifest["runtime_dirs"].values()]
    return [f"runtime directory missing: {path}" for path in wanted if not path.is_dir()]


def check_config(data_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """The declared settings hold. Forge may add its own saved options (StableNew selects the checkpoint)."""

    path = data_dir / "config.json"
    if not path.is_file():
        return [f"Forge settings file missing: {path}"]
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"Forge settings file is unreadable: {exc}"]
    return [
        f"[{DRIFT}] config {key} is {actual.get(key)!r}, the contract requires {value!r}"
        for key, value in manifest["config"]["required_settings"].items()
        if actual.get(key) != value
    ]


def check_uv(install_dir: Path) -> list[str]:
    """``--uv`` is a required launch flag; Forge runs ``uv --help`` at start and waits for Enter if it fails.

    The launch profile puts the venv's ``Scripts`` first on ``PATH``, so the venv must carry ``uv.exe``.
    """

    executable = install_dir / "venv" / "Scripts" / "uv.exe"
    if executable.is_file():
        return []
    return [f"[{DRIFT}] the required --uv flag needs {executable}; without it Forge prints an error and waits for Enter"]


def check_version_uid(source_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """The declared ``VERSION_UID`` is the one the pinned Forge source defines.

    Forge refuses to start unattended when ``config.json`` lacks it: it prints a "clean reinstall" alert and
    waits for Enter, which ``WebUIProcessManager`` can never answer. The value is a property of the pinned
    revision, so a revision bump that changes it must be a deliberate contract change.
    """

    path = source_dir / manifest["config"]["version_uid_source"]
    expected = manifest["config"]["required_settings"]["VERSION_UID"]
    if not path.is_file():
        return [f"VERSION_UID source missing: {path}"]
    match = _VERSION_UID.search(path.read_text(encoding="utf-8"))
    if match is None:
        return [f"[{DRIFT}] no VERSION_UID is defined in {manifest['config']['version_uid_source']}"]
    if match.group(1) != expected:
        return [f"[{DRIFT}] the pinned Forge source defines VERSION_UID {match.group(1)!r}, the contract declares {expected!r}"]
    return []


def check_models(home: Path, manifest: dict[str, Any], *, hash_models: bool) -> list[str]:
    """External model references resolve to the accepted files (never copied or downloaded)."""

    if not home.is_dir():
        return [f"model reference home missing: {home}"]
    problems = []
    for label, spec in manifest["models"]["files"].items():
        path = home / spec["path"]
        if not path.is_file():
            problems.append(f"model reference: {label} not found at {path}")
        elif hash_models and sha256_file(path) != spec["sha256"]:
            problems.append(f"model reference: {label} does not match its accepted sha256")
    return problems


def check_torch(manifest: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Torch/torchvision builds, CUDA build and availability, and the qualified GPU is visible."""

    import torch  # noqa: PLC0415 - only the venv's own torch matters
    import torchvision  # noqa: PLC0415

    expected = manifest["torch"]
    problems = []
    if str(torch.__version__) != expected["torch"]:
        problems.append(f"[{DRIFT}] torch {torch.__version__} is not the pinned {expected['torch']}")
    if str(torchvision.__version__) != expected["torchvision"]:
        problems.append(f"[{DRIFT}] torchvision {torchvision.__version__} is not the pinned {expected['torchvision']}")
    if str(torch.version.cuda) != expected["cuda"]:
        problems.append(f"[{DRIFT}] torch CUDA {torch.version.cuda} is not {expected['cuda']} (CPU build?)")
    available = bool(torch.cuda.is_available())
    gpu = str(torch.cuda.get_device_name(0)) if available else None
    if not available:
        problems.append("CUDA is not available to torch")
    elif expected["qualified_gpu_name_contains"] not in gpu:
        problems.append(f"GPU {gpu!r} is not the qualified {expected['qualified_gpu_name_contains']!r}")
    return problems, {"torch": str(torch.__version__), "torchvision": str(torchvision.__version__), "cuda": str(torch.version.cuda), "gpu": gpu}


# --- launch profile (printed, never executed) ----------------------------------------------------------


def build_launch_profile(manifest: dict[str, Any], *, install_dir: Path, model_home: Path, port: int) -> dict[str, Any]:
    """The WebUIProcessManager launch profile: command, working directory and environment, loopback only."""

    policy = manifest["launch_policy"]
    venv = install_dir / "venv"
    runtime = manifest["runtime_dirs"]
    command = [
        str(venv / "Scripts" / "python.exe"),
        policy["launch_script"],
        "--uv",
        "--api",
        "--port",
        str(port),
        policy["data_dir_flag"],
        str(install_dir / manifest["runtime_dirs"]["data"]),
        policy["model_reference_flag"],
        str(model_home),
        "--ad-no-huggingface",
        "--skip-install",
    ]
    env = dict(policy["env"])
    env.update(
        {
            "HF_HUB_CACHE": str(install_dir / runtime["huggingface_cache"]),
            "MPLCONFIGDIR": str(install_dir / runtime["matplotlib"]),
            "YOLO_CONFIG_DIR": str(install_dir / runtime["yolo_config"]),
            "UV_CACHE_DIR": str(install_dir / runtime["uv_cache"]),
            "UV_PYTHON": str(venv / "Scripts" / "python.exe"),
            "VIRTUAL_ENV": str(venv),
            "PATH": str(venv / "Scripts") + os.pathsep + os.environ.get("PATH", ""),
        }
    )
    return {
        "runtime_identity": manifest["runtime_identity"],
        "command": command,
        "working_dir": str(install_dir / "source"),
        "env_overrides": env,
        "endpoint": f"http://127.0.0.1:{port}",
        "startup_timeout_seconds": 180,
    }


def check_launch_command(command: list[str], manifest: dict[str, Any]) -> list[str]:
    """A launch command keeps the qualified semantics: required flags present, loopback, nothing tuned."""

    policy = manifest["launch_policy"]
    flags = {part for part in command if part.startswith("--")}
    problems = [f"launch command lacks required flag {flag}" for flag in policy["required_flags"] if flag not in flags]
    if policy["model_reference_flag"] not in flags:
        problems.append(f"launch command lacks {policy['model_reference_flag']} (the accepted model reference)")
    problems += [
        f"launch command carries tuning/exposure flag {flag}"
        for flag in sorted(flags)
        if any(fragment in flag.lower() for fragment in policy["forbidden_flag_fragments"])
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--install-dir", type=Path, help="<root>/neo-<rev8> directory")
    parser.add_argument("--model-reference-home", type=Path, help="existing A1111 home referenced for models (never copied)")
    parser.add_argument("--constraints", type=Path, help="override of the constraints file")
    parser.add_argument("--port", type=int)
    parser.add_argument("--print-profile", action="store_true", help="print the WebUIProcessManager launch profile and exit")
    parser.add_argument("--contract-only", action="store_true", help="validate the manifest and exit")
    parser.add_argument("--skip-model-hashes", action="store_true", help="skip hashing the large external model files")
    parser.add_argument("--json", action="store_true", help="print the verified facts as JSON")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"MANAGED FORGE CONTRACT UNREADABLE: {args.manifest}: {exc}", file=sys.stderr)
        return 2
    contract_problems = validate_manifest(manifest, require_constraints_file=args.constraints is None)
    if contract_problems or args.contract_only:
        for problem in contract_problems:
            print(f"  contract: {problem}", file=sys.stderr)
        if not contract_problems:
            print("managed Forge contract is valid")
        return 1 if contract_problems else 0
    if args.install_dir is None:
        print("--install-dir is required", file=sys.stderr)
        return 2
    port = args.port or manifest["launch_policy"]["default_port"]
    if args.print_profile:
        if args.model_reference_home is None:
            print("--model-reference-home is required to print the launch profile", file=sys.stderr)
            return 2
        print(json.dumps(build_launch_profile(manifest, install_dir=args.install_dir, model_home=args.model_reference_home, port=port), indent=2))
        return 0

    constraints = args.constraints or (ROOT / manifest["constraints"])
    data_dir = args.install_dir / manifest["runtime_dirs"]["data"]
    problems = [f"[python] {p}" for p in check_python(manifest)]
    problems += check_source(args.install_dir / "source", revision=manifest["upstream"]["revision"], repository=manifest["upstream"]["repository"], label="forge")
    problems += check_source(data_dir / "extensions" / "adetailer-neo", revision=manifest["adetailer_neo"]["revision"], repository=manifest["adetailer_neo"]["repository"], label="adetailer-neo")
    try:
        lock = parse_lock(constraints.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"MANAGED FORGE LOCK UNREADABLE: {exc}", file=sys.stderr)
        return 2
    problems += [f"[lock] {p}" for p in check_lock(lock, manifest)]
    problems += check_packages(lock, installed_versions())
    problems += evaluate_pip_check(run_pip_check(), manifest["known_conflicts"])
    torch_problems, facts = check_torch(manifest)
    problems += [f"[torch] {p}" for p in torch_problems]
    problems += [f"[extensions] {p}" for p in check_extensions(data_dir, manifest)]
    problems += [f"[detectors] {p}" for p in check_detectors(data_dir, manifest)]
    problems += [f"[path-budget] {p}" for p in check_path_budget(args.install_dir, manifest)]
    problems += [f"[runtime-dir] {p}" for p in check_runtime_dirs(args.install_dir, manifest)]
    problems += [f"[config] {p}" for p in check_config(data_dir, manifest)]
    problems += [f"[config] {p}" for p in check_version_uid(args.install_dir / "source", manifest)]
    problems += [f"[uv] {p}" for p in check_uv(args.install_dir)]
    if args.model_reference_home is not None:
        problems += [f"[models] {p}" for p in check_models(args.model_reference_home, manifest, hash_models=not args.skip_model_hashes)]
        profile = build_launch_profile(manifest, install_dir=args.install_dir, model_home=args.model_reference_home, port=port)
        problems += [f"[launch] {p}" for p in check_launch_command(profile["command"], manifest)]
    if problems:
        print(f"MANAGED FORGE DRIFT: {len(problems)} problem(s) in {args.install_dir}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    summary = {
        "forge_revision": manifest["upstream"]["revision"],
        "adetailer_neo_revision": manifest["adetailer_neo"]["revision"],
        "python": sys.version.split()[0],
        "packages": len(lock),
        "known_conflicts": [c["id"] for c in manifest["known_conflicts"]],
        **facts,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"managed Forge neo@{manifest['upstream']['revision'][:8]} on Python {summary['python']} verified: {len(lock)} packages, torch {facts['torch']} cuda {facts['cuda']} on {facts['gpu']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
