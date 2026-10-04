"""PR-IMG-116: the bounded Klein asset installer (tiny fake assets, a temp 'managed Forge'; no network)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install_forge_klein_assets.ps1"
SHELL = shutil.which("powershell") or shutil.which("pwsh")

pytestmark = pytest.mark.skipif(SHELL is None, reason="PowerShell is not available")

FILES = {
    "flux-2-klein-4b-fp8.safetensors": ("Stable-diffusion", b"transformer-bytes"),
    "qwen_3_4b.safetensors": ("text_encoder", b"text-encoder-bytes" * 3),
    "flux2-vae.safetensors": ("VAE", b"vae"),
}


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "source"
    install = tmp_path / "neo-test"
    (install / "data").mkdir(parents=True)
    source.mkdir()
    assets = []
    for name, (subdir, payload) in FILES.items():
        (source / name).write_bytes(payload)
        assets.append({
            "role": name, "filename": name, "models_subdir": subdir, "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(), "repo": "x/y", "revision": "0" * 40,
        })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": "test", "assets": assets}), encoding="utf-8")
    return {"source": source, "install": install, "manifest": manifest, "root": tmp_path}


def _run(world: dict[str, Path], *extra: str, source: Path | None = None) -> subprocess.CompletedProcess[str]:
    args = [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
            "-InstallDir", str(world["install"]), "-ManifestPath", str(world["manifest"])]
    if source is not False:
        args += ["-SourceDir", str(source or world["source"])]
    return subprocess.run([*args, *extra], capture_output=True, text=True, timeout=120)


def _dest(world: dict[str, Path], name: str) -> Path:
    return world["install"] / "data" / "models" / FILES[name][0] / name


def test_installs_the_three_exact_files_into_the_managed_data_model_tree(world) -> None:
    result = _run(world)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert {a["action"] for a in report["assets"]} == {"installed"}
    for name, (_, payload) in FILES.items():
        assert _dest(world, name).read_bytes() == payload
    assert not list((world["install"] / "data").rglob("*.partial-*"))  # atomic staging is cleaned up


def test_second_run_is_an_idempotent_noop(world) -> None:
    assert _run(world).returncode == 0
    stamps = {n: _dest(world, n).stat().st_mtime_ns for n in FILES}
    again = _run(world)
    assert again.returncode == 0, again.stderr
    assert {a["action"] for a in json.loads(again.stdout)["assets"]} == {"verified"}
    assert {n: _dest(world, n).stat().st_mtime_ns for n in FILES} == stamps


def test_wrong_source_hash_is_rejected_before_any_mutation(world) -> None:
    (world["source"] / "qwen_3_4b.safetensors").write_bytes(b"tampered-bytes-of-the-same-length!!"[: len(FILES["qwen_3_4b.safetensors"][1])])
    result = _run(world)
    assert result.returncode != 0
    assert "exact size and SHA-256 required" in result.stderr + result.stdout
    assert not (world["install"] / "data" / "models").exists()  # nothing created at all


def test_missing_source_file_is_rejected_before_any_mutation(world) -> None:
    (world["source"] / "flux2-vae.safetensors").unlink()
    result = _run(world)
    assert result.returncode != 0
    assert not (world["install"] / "data" / "models").exists()


def test_a_conflicting_same_name_destination_is_never_overwritten(world) -> None:
    conflict = _dest(world, "flux2-vae.safetensors")
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"someone elses vae")
    result = _run(world)
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr + result.stdout
    assert conflict.read_bytes() == b"someone elses vae"
    # classification happens before any copy: the other two files were not installed either
    assert not _dest(world, "qwen_3_4b.safetensors").exists()
    assert not _dest(world, "flux-2-klein-4b-fp8.safetensors").exists()


def test_check_only_mutates_nothing_and_reports_missing(world) -> None:
    result = _run(world, "-CheckOnly", source=False)
    assert result.returncode == 2
    assert {a["action"] for a in json.loads(result.stdout)["assets"]} == {"missing"}
    assert not (world["install"] / "data" / "models").exists()
    assert _run(world).returncode == 0
    assert _run(world, "-CheckOnly", source=False).returncode == 0


def test_refuses_a_missing_managed_forge_data_directory(world) -> None:
    shutil.rmtree(world["install"] / "data")
    result = _run(world)
    assert result.returncode != 0
    assert "Managed Forge data directory not found" in result.stderr + result.stdout


def test_script_never_downloads_and_never_touches_a1111_or_forge_source() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("Invoke-WebRequest", "Invoke-RestMethod", "curl", "wget", "pip ", "git ", "\\source", "\\venv", "stable-diffusion-webui"):
        assert forbidden not in text
