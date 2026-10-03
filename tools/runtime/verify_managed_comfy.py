"""Verify (read-only) a StableNew-managed ComfyUI installation against its runtime contract.

``config/managed_comfy_runtime.json`` owns the installation identity (exact upstream release
and revision, Python minor, Torch build, launch policy, custom-node policy) and points at one
exact-version constraints file. This module checks an installation on disk against that contract:
source revision and cleanliness, interpreter, package pins, Torch/CUDA, custom-node policy and the
StableNew-owned runtime folders. It never writes, installs, downloads or starts anything, and it
touches no process. Run it with the Comfy venv's interpreter so package metadata is the venv's.

Workflow facts (graphs, model hashes, controls, readiness thresholds) are deliberately not here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config" / "managed_comfy_runtime.json"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MINOR = re.compile(r"^3\.\d{1,2}$")
_RELEASE = re.compile(r"^v\d+\.\d+\.\d+$")

if str(ROOT) not in sys.path:  # share the pin parser with the application verifier
    sys.path.insert(0, str(ROOT))
from tools.runtime import verify_runtime_pins as _pins  # noqa: E402


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def validate_manifest(
    manifest: dict[str, Any], *, root: Path = ROOT, require_constraints_file: bool = True
) -> list[str]:
    """Problems with the contract itself (shape, exactness, no mutable refs)."""

    problems: list[str] = []
    if manifest.get("schema_version") != 1:
        problems.append("schema_version must be 1")
    upstream = manifest.get("upstream") or {}
    if not _RELEASE.match(str(upstream.get("release", ""))):
        problems.append("upstream.release must be an exact stable tag like v0.38.0")
    if str(upstream.get("version", "")) != str(upstream.get("release", "")).lstrip("v"):
        problems.append("upstream.version must equal the release without the leading v")
    if not _SHA.match(str(upstream.get("revision", ""))):
        problems.append("upstream.revision must be a full 40-hex commit SHA")
    if str(upstream.get("release", "")).lower() in {"master", "main", "nightly"}:
        problems.append("upstream.release must not be a mutable ref")
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
    if "windows-py314" in constraints or not constraints.startswith("constraints/comfy-"):
        problems.append("constraints must be the Comfy authority, not the application constraints")
    elif require_constraints_file and not (root / constraints).is_file():
        problems.append(f"constraints file missing: {constraints}")
    policy = manifest.get("launch_policy") or {}
    if policy.get("listen") != "127.0.0.1":
        problems.append("launch_policy.listen must be loopback-only")
    if "--disable-pinned-memory" not in (policy.get("required_flags") or []):
        problems.append("launch_policy must require --disable-pinned-memory")
    if (manifest.get("custom_nodes") or {}).get("policy") != "none":
        problems.append("custom_nodes.policy must be 'none' (no third-party nodes by default)")
    return problems


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
    done = subprocess.run(
        ["git", "-C", str(source), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout.strip()


def check_source(source: Path, *, version: str, revision: str) -> list[str]:
    """The checkout is exactly the pinned revision, clean, and reports the pinned version."""

    if not source.is_dir():
        return [f"source directory missing: {source}"]
    problems = []
    try:
        head = _git(source, "rev-parse", "HEAD")
        if head != revision:
            problems.append(f"source revision {head} is not the pinned {revision}")
        if _git(source, "status", "--porcelain"):
            problems.append("source checkout is not clean (modified or untracked files)")
    except (RuntimeError, OSError) as exc:
        problems.append(f"source is not a readable git checkout: {exc}")
    version_file = source / "comfyui_version.py"
    reported = re.search(r'__version__\s*=\s*"([^"]+)"', version_file.read_text(encoding="utf-8")) if version_file.is_file() else None
    if reported is None or reported.group(1) != version:
        problems.append(f"comfyui_version.py reports {reported.group(1) if reported else 'nothing'}, expected {version}")
    return problems


def check_pins(constraints: Path, installed: dict[str, str] | None = None) -> list[str]:
    """Every pinned package installed at its pin, and nothing installed beyond the pins.

    The application verifier ignores unpinned packages; this runtime is a clean Comfy core with no
    third-party nodes, so an extra distribution (a node's dependency, a stray ``pip install``) is
    drift and is reported.
    """

    parsed = _pins.parse_profiles(constraints.read_text(encoding="utf-8"))
    installed = _pins.installed_versions() if installed is None else installed
    problems, _state = _pins.evaluate(parsed, installed)
    pinned = parsed.all_pins
    problems += [
        f"{name}=={version} is installed but not pinned (this runtime carries exactly its constraints)"
        for name, version in sorted(installed.items())
        if name not in pinned
    ]
    return problems


def check_custom_nodes(source: Path, allowed: list[str]) -> list[str]:
    nodes = source / "custom_nodes"
    if not nodes.is_dir():
        return [f"custom_nodes directory missing: {nodes}"]
    return [
        f"unexpected custom node entry: {entry.name} (this runtime carries no third-party nodes)"
        for entry in sorted(nodes.iterdir())
        if entry.name not in allowed
    ]


def check_torch(manifest: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Torch build and CUDA visibility. Importing torch does not initialise a model."""

    import torch  # noqa: PLC0415 - only the venv's own torch matters

    problems = []
    expected = manifest["torch"]
    if not _pins.versions_equal(str(torch.__version__), expected["torch"]):
        problems.append(f"torch {torch.__version__} is not the pinned {expected['torch']}")
    if str(torch.version.cuda) != expected["cuda"]:
        problems.append(f"torch CUDA {torch.version.cuda} is not {expected['cuda']} (CPU build?)")
    available = bool(torch.cuda.is_available())
    if not available:
        problems.append("CUDA is not available to torch")
    facts = {
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "cuda_available": available,
        "gpu": str(torch.cuda.get_device_name(0)) if available else None,
    }
    return problems, facts


def check_runtime_dir(manifest: dict[str, Any], runtime_dir: Path) -> list[str]:
    policy = manifest["launch_policy"]
    problems = [
        f"runtime folder missing: {runtime_dir / folder}"
        for folder in policy["runtime_folders"]
        if not (runtime_dir / folder).is_dir()
    ]
    extra = runtime_dir / policy["extra_model_paths_file"]
    if not extra.is_file():
        problems.append(f"model path config missing: {extra}")
    else:
        try:
            import yaml  # noqa: PLC0415

            parsed = yaml.safe_load(extra.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict) or not parsed:
                problems.append(f"model path config is empty or not a mapping: {extra}")
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            problems.append(f"model path config is unreadable: {exc}")
    return problems


def build_launch_command(
    manifest: dict[str, Any], *, install_dir: Path, runtime_dir: Path, port: int
) -> list[str]:
    """The ``comfy_command`` list StableNew's own process manager should launch (not run here)."""

    policy = manifest["launch_policy"]
    command = [
        str(install_dir / "venv" / "Scripts" / "python.exe"),
        str(install_dir / "source" / "main.py"),
        "--listen",
        policy["listen"],
        "--port",
        str(port),
        "--input-directory",
        str(runtime_dir / "input"),
        "--output-directory",
        str(runtime_dir / "output"),
        "--temp-directory",
        str(runtime_dir / "temp"),
        "--user-directory",
        str(runtime_dir / "user"),
        "--extra-model-paths-config",
        str(runtime_dir / policy["extra_model_paths_file"]),
    ]
    command.extend(policy["required_flags"])
    return command


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(value.replace("/", os.sep)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--install-dir", type=Path, help="<root>/<release>-py<minor> directory")
    parser.add_argument("--release", help="qualification override (default: the manifest release)")
    parser.add_argument("--revision", help="qualification override (default: the manifest revision)")
    parser.add_argument("--constraints", type=Path, help="qualification override of the constraints file")
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("--contract-only", action="store_true", help="validate the manifest and exit")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"MANAGED COMFY CONTRACT UNREADABLE: {args.manifest}: {exc}", file=sys.stderr)
        return 2
    contract_problems = validate_manifest(
        manifest, require_constraints_file=args.constraints is None
    )
    if contract_problems or args.contract_only:
        for problem in contract_problems:
            print(f"  contract: {problem}", file=sys.stderr)
        if not contract_problems:
            print("managed Comfy contract is valid")
        return 1 if contract_problems else 0
    if args.install_dir is None:
        print("--install-dir is required for installation checks", file=sys.stderr)
        return 2

    upstream = manifest["upstream"]
    release = args.release or upstream["release"]
    revision = args.revision or upstream["revision"]
    constraints = args.constraints or (ROOT / manifest["constraints"])
    runtime_dir = args.runtime_dir or _expand(manifest["launch_policy"]["default_runtime_dir"])
    if args.print_command:
        print(json.dumps(build_launch_command(manifest, install_dir=args.install_dir, runtime_dir=runtime_dir, port=args.port)))
        return 0

    problems = [f"[python] {p}" for p in check_python(manifest)]
    problems += [f"[source] {p}" for p in check_source(args.install_dir / "source", version=release.lstrip("v"), revision=revision)]
    problems += [f"[pins] {p}" for p in check_pins(constraints)]
    problems += [f"[custom-nodes] {p}" for p in check_custom_nodes(args.install_dir / "source", manifest["custom_nodes"]["allowed_entries"])]
    torch_problems, facts = check_torch(manifest)
    problems += [f"[torch] {p}" for p in torch_problems]
    problems += [f"[runtime-dir] {p}" for p in check_runtime_dir(manifest, runtime_dir)]
    if problems:
        print(f"MANAGED COMFY DRIFT: {len(problems)} problem(s) in {args.install_dir}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"managed Comfy {release}@{revision[:8]} on Python {sys.version.split()[0]} verified: torch {facts['torch']} cuda {facts['cuda']} on {facts['gpu']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
