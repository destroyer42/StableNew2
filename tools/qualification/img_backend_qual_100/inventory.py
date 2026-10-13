"""Read-only local inventory: runtime identities, model visibility per backend and (optionally) live host facts.

Nothing here writes, starts, stops, selects or downloads anything. Files are only ``stat``-ed (and hashed when the caller
asks); runtime sources are read as text. The live-host probe is a separate function the caller must invoke explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from .comfy_graphs import Graph, required_models

# Comfy model folders a qualification graph needs, with the alternate folder names Comfy also searches.
COMFY_FOLDER_ALIASES: dict[str, tuple[str, ...]] = {
    "checkpoints": ("checkpoints",),
    "loras": ("loras",),
    "controlnet": ("controlnet",),
    "diffusion_models": ("diffusion_models", "unet"),
    "text_encoders": ("text_encoders", "clip"),
    "vae": ("vae",),
}
MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
FORGE_DEFAULT_PORT = 7871
COMFY_DEFAULT_PORT = 8188


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _git_head(source: Path) -> str | None:
    """HEAD commit of a checkout by reading ``.git`` directly (no subprocess, no write)."""

    git = Path(source) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if re.fullmatch(r"[0-9a-f]{40}", head):
        return head
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        try:
            return (git / ref).read_text(encoding="utf-8").strip()
        except OSError:
            try:
                for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
            except OSError:
                return None
    return None


def _venv_facts(venv: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"present": Path(venv).is_dir()}
    cfg = Path(venv) / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "version":
                facts["python"] = value.strip()
    except OSError:
        pass
    site = Path(venv) / "Lib" / "site-packages"
    if site.is_dir():
        torch = sorted(p.name for p in site.glob("torch-*.dist-info"))
        facts["torch"] = (
            torch[0].removeprefix("torch-").removesuffix(".dist-info") if torch else None
        )
    return facts


def comfy_identity(manifest_path: Path, install_dir: Path) -> dict[str, Any]:
    """Declared (manifest) versus installed (source HEAD, venv) identity of the managed Comfy runtime."""

    manifest = _read_json(manifest_path) or {}
    declared = (manifest.get("upstream") or {}).get("revision")
    source = Path(install_dir) / "source"
    head = _git_head(source)
    custom = source / "custom_nodes"
    allowed = set((manifest.get("custom_nodes") or {}).get("allowed_entries") or ())
    extra = (
        sorted(p.name for p in custom.iterdir() if p.name not in allowed) if custom.is_dir() else []
    )
    return {
        "release": (manifest.get("upstream") or {}).get("release"),
        "declared_revision": declared,
        "installed_revision": head,
        "revision_matches": bool(declared and head and declared == head),
        "venv": _venv_facts(Path(install_dir) / "venv"),
        "declared_python_minor": (manifest.get("python") or {}).get("minor"),
        "declared_torch": (manifest.get("torch") or {}).get("torch"),
        "custom_nodes_policy": (manifest.get("custom_nodes") or {}).get("policy"),
        "unlisted_custom_nodes": extra,
        "install_present": source.is_dir(),
    }


def forge_identity(manifest_path: Path, install_dir: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path) or {}
    declared = (manifest.get("upstream") or {}).get("revision")
    head = _git_head(Path(install_dir) / "source")
    return {
        "declared_revision": declared,
        "installed_revision": head,
        "revision_matches": bool(declared and head and declared == head),
        "venv": _venv_facts(Path(install_dir) / "venv"),
        "declared_torch": (manifest.get("torch") or {}).get("torch"),
        "install_present": (Path(install_dir) / "source").is_dir(),
    }


# ---- model visibility -------------------------------------------------------------------------------------------
def parse_extra_model_paths(path: Path) -> dict[str, list[Path]]:
    """Folder name -> directories from an ``extra_model_paths.yaml`` (read-only; missing file -> empty)."""

    import yaml

    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    roots: dict[str, list[Path]] = {}
    if not isinstance(document, Mapping):
        return roots
    for section in document.values():
        if not isinstance(section, Mapping):
            continue
        base = Path(os.path.expandvars(os.path.expanduser(str(section.get("base_path", "")))))
        if not base.is_absolute():
            base = Path(path).resolve().parent / base
        for folder, value in section.items():
            if folder in ("base_path", "is_default") or not isinstance(value, str):
                continue
            for line in value.splitlines():
                line = line.strip()
                if line:
                    roots.setdefault(folder, []).append(base / line)
    return roots


def comfy_search_roots(
    source: Path, extra_paths: Mapping[str, list[Path]]
) -> dict[str, list[Path]]:
    """The directories Comfy would search per folder: its own ``models/<folder>`` plus the extra-paths entries."""

    roots: dict[str, list[Path]] = {}
    for folder, aliases in COMFY_FOLDER_ALIASES.items():
        found: list[Path] = []
        for alias in aliases:
            found.append(Path(source) / "models" / alias)
            found.extend(extra_paths.get(alias, ()))
        roots[folder] = found
    return roots


def _candidates(directory: Path, wanted: str) -> list[Path]:
    """Files in ``directory`` (recursive) whose name or stem equals ``wanted`` (case-insensitive, a model suffix only)."""

    if not directory.is_dir():
        return []
    key = wanted.lower()
    found = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MODEL_SUFFIXES:
            continue
        if path.name.lower() == key or path.stem.lower() == key:
            found.append(path)
    return found


def locate_model(roots: Iterable[Path], wanted: str) -> list[Path]:
    seen: dict[str, Path] = {}
    for directory in roots:
        for path in _candidates(Path(directory), wanted):
            seen.setdefault(str(path.resolve()).lower(), path)
    return sorted(seen.values(), key=str)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def model_visibility(
    graph: Graph,
    comfy_roots: Mapping[str, list[Path]],
    *,
    frozen: Mapping[str, Mapping[str, Any]] | None = None,
    hash_files: bool = False,
) -> list[dict[str, Any]]:
    """Per model the graph loads: where Comfy would find it, its size, and (optionally) its SHA-256.

    ``frozen`` maps a file name to ``{"size": int, "sha256": str}``; a located file is then ``exact`` only when size
    (and, when hashed, SHA-256) match. Without a frozen identity the status is ``located_unverified``.
    """

    report: list[dict[str, Any]] = []
    for folder, names in sorted(required_models(graph).items()):
        if folder == "input":
            continue  # images are staged into the runtime input folder by the runner, not discovered
        for name in sorted(set(names)):
            matches = locate_model(comfy_roots.get(folder, ()), name)
            entry: dict[str, Any] = {
                "folder": folder,
                "name": name,
                "matches": [str(m) for m in matches],
                "status": "missing"
                if not matches
                else "ambiguous"
                if len(matches) > 1
                else "located_unverified",
            }
            if len(matches) == 1:
                path = matches[0]
                entry["size"] = path.stat().st_size
                want = (frozen or {}).get(path.name)
                if want:
                    ok = entry["size"] == want["size"]
                    if ok and hash_files:
                        entry["sha256"] = sha256_file(path)
                        ok = entry["sha256"] == want["sha256"]
                    entry["status"] = (
                        "exact" if ok and hash_files else "size_match" if ok else "mismatch"
                    )
            report.append(entry)
    return report


def forge_model_visibility(
    forge_model_roots: Iterable[Path],
    names: Iterable[str],
    *,
    frozen: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    roots = [Path(r) for r in forge_model_roots]
    out = []
    for name in sorted(set(names)):
        matches = locate_model(roots, name)
        entry: dict[str, Any] = {
            "name": name,
            "matches": [str(m) for m in matches],
            "status": "missing" if not matches else "ambiguous" if len(matches) > 1 else "located",
        }
        if len(matches) == 1:
            entry["size"] = matches[0].stat().st_size
            want = (frozen or {}).get(matches[0].name)
            if want:
                entry["status"] = "size_match" if entry["size"] == want["size"] else "mismatch"
        out.append(entry)
    return out


# ---- live host (explicit only) ---------------------------------------------------------------------------------
GPU_FIELDS = "name,driver_version,memory.total,memory.used,temperature.gpu"


def port_occupied(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((host, port)) == 0


def host_probe(
    *,
    ports: Iterable[int] = (FORGE_DEFAULT_PORT, COMFY_DEFAULT_PORT),
    memory: Callable[[], Any] | None = None,
    run: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Live, read-only host facts: RAM, GPU state and whether the well-known runtime ports are occupied."""

    if memory is None:
        import psutil

        memory = psutil.virtual_memory
    vm = memory()
    facts: dict[str, Any] = {
        "ram_total_gb": round(vm.total / 1e9, 2),
        "ram_available_gb": round(vm.available / 1e9, 2),
        "ports_occupied": {str(p): port_occupied(p) for p in ports},
    }
    runner = run or (lambda *a, **k: subprocess.check_output(*a, **k))
    try:
        out = runner(
            ["nvidia-smi", f"--query-gpu={GPU_FIELDS}", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
        )
        name, driver, total, used, temp = [
            part.strip() for part in out.strip().splitlines()[0].split(",")
        ][:5]
        facts["gpu"] = {
            "name": name,
            "driver": driver,
            "vram_total_mib": int(total),
            "vram_used_mib": int(used),
            "temp_c": int(temp),
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        facts["gpu"] = None
    return facts
