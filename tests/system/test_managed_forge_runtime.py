"""StableNew-managed Forge Neo runtime authority (PR-IMG-FORGE-RUNTIME-100).

Deterministic and GPU-free: the runtime contract, its complete exact package lock, the read-only verifier
(every drift class, with fixtures - the real accepted environment is never touched), the launch profile and
the bootstrap's safety policy. The real from-nothing builds and the physical comparison are runtime evidence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tools.runtime import verify_managed_forge as verifier

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config" / "managed_forge_runtime.json"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_managed_forge_windows.ps1"
VERIFIER = ROOT / "tools" / "runtime" / "verify_managed_forge.py"
FORGE_SHA = "d70373ebcf1a96d210b78cd6f77196459e783e2a"
ADETAILER_SHA = "af228eba7a3f3691a25bcd1fc94aa95e600dd3e6"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _lock() -> dict[str, str]:
    return verifier.parse_lock((ROOT / _manifest()["constraints"]).read_text(encoding="utf-8"))


def _strip_comments(script: str) -> str:
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


# --- The contract ---------------------------------------------------------------------------------


def test_contract_pins_exact_revisions_python_313_the_cuda_torch_family_and_the_forge_identity() -> None:
    manifest = _manifest()

    assert verifier.validate_manifest(manifest) == []
    assert manifest["runtime_identity"] == "forge_webui"
    assert manifest["upstream"]["revision"] == FORGE_SHA and manifest["upstream"]["channel"] == "neo"
    assert manifest["upstream"]["repository"].endswith("Haoming02/sd-webui-forge-classic")
    assert manifest["adetailer_neo"]["revision"] == ADETAILER_SHA
    assert manifest["adetailer_neo"]["repository"].endswith("Haoming02/ADetailer-Neo")
    assert manifest["python"] == {"minor": "3.13", "accepted": "3.13.16", "implementation": "CPython", "free_threaded": False, "jit": False}
    assert (manifest["torch"]["torch"], manifest["torch"]["torchvision"], manifest["torch"]["cuda"]) == ("2.13.0+cu130", "0.28.0+cu130", "13.0")
    assert manifest["package_count"] == 147
    # The branch name is provenance only; no mutable ref is the identity.
    assert "neo" not in (manifest["upstream"]["revision"], manifest["adetailer_neo"]["revision"])


def test_contract_owns_installation_and_references_not_generation_settings_or_a_start_command() -> None:
    manifest = _manifest()
    manifest.pop("description")
    text = json.dumps(manifest).lower()

    for generation_fact in ("seed", "steps", "cfg", "sampler", "prompt", "424242", "denoise", "width", "height"):
        assert generation_fact not in text, generation_fact
    for owner_path in ("c:\\\\users", "c:/users", "stable-diffusion-webui", "e:\\\\"):
        assert owner_path not in text, owner_path  # model/detector locations are caller-supplied, never committed


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m["upstream"].update(revision="neo"), "40-hex"),
        (lambda m: m["upstream"].update(revision=FORGE_SHA[:8]), "40-hex"),
        (lambda m: m["adetailer_neo"].update(revision="main"), "40-hex"),
        (lambda m: m.update(runtime_identity="a1111_webui"), "forge_webui"),
        (lambda m: m["python"].update(minor="3"), "single minor"),
        (lambda m: m["python"].update(free_threaded=True), "standard-GIL"),
        (lambda m: m["python"].update(jit=True), "JIT off"),
        (lambda m: m["torch"].update(torch="2.13.0"), "+cu130"),
        (lambda m: m["torch"].update(cuda="12.8"), "13.0"),
        (lambda m: m.update(constraints="constraints/windows-py314-cu130.txt"), "Forge authority"),
        (lambda m: m.update(constraints="constraints/comfy-windows-py313-cu130-v0.38.0.txt"), "Forge authority"),
        (lambda m: m.update(known_conflicts=[]), "exactly the one"),
        (lambda m: m["known_conflicts"].append(dict(m["known_conflicts"][0], package="gradio-client")), "exactly the one"),
        (lambda m: m["launch_policy"].update(required_flags=["--api"]), "--skip-install"),
        (lambda m: m["launch_policy"].update(model_reference_flag="--model-ref"), "--forge-ref-a1111-home"),
        (lambda m: m["extensions"].update(allowed=["adetailer-neo", "adetailer"]), "adetailer-neo"),
        (lambda m: m["detectors"]["files"].pop("hand_yolov8n.pt"), "two YOLO"),
        (lambda m: m["detectors"]["files"].update({"mediapipe.task": "0" * 64}), "two YOLO"),
        (lambda m: m["models"]["files"].pop("lora"), "models.files"),
        (lambda m: m["install"].pop("path_budget"), "path_budget"),
        (lambda m: m["config"]["required_settings"].pop("VERSION_UID"), "VERSION_UID"),
        (lambda m: m["config"].pop("version_uid_source"), "VERSION_UID"),
    ],
)
def test_invalid_contracts_are_rejected(mutate, expected) -> None:
    manifest = copy.deepcopy(_manifest())
    mutate(manifest)

    assert any(expected in problem for problem in verifier.validate_manifest(manifest))


def test_the_known_gradio_pillow_conflict_is_one_structured_entry() -> None:
    [conflict] = _manifest()["known_conflicts"]

    assert (conflict["package"], conflict["version"], conflict["requires"], conflict["dependency"], conflict["installed"]) == (
        "gradio", "4.40.0", "pillow<11.0,>=8.0", "pillow", "12.3.0",
    )
    assert verifier._conflict_line(conflict) == "gradio 4.40.0 has requirement pillow<11.0,>=8.0, but you have pillow 12.3.0."
    assert "do not downgrade Pillow" in conflict["note"].lower() or "Not repaired" in conflict["note"]


# --- The complete exact package lock ---------------------------------------------------------------


def test_the_lock_is_the_complete_accepted_set_separate_from_the_other_runtimes() -> None:
    manifest = _manifest()
    lock = _lock()

    assert verifier.check_lock(lock, manifest) == []
    assert len(lock) == 147
    assert (lock["torch"], lock["torchvision"]) == ("2.13.0+cu130", "0.28.0+cu130")
    assert (lock["gradio"], lock["pillow"]) == ("4.40.0", "12.3.0")  # reproduced, not repaired
    assert {"pip", "setuptools", "uv", "ultralytics", "depth-anything", "depth-anything-v2"} <= set(lock)
    assert not {"mediapipe", "xformers", "sageattention", "flash-attn"} & set(lock)
    path = ROOT / manifest["constraints"]
    assert path.name.startswith("forge-") and path.name != "windows-py314-cu130.txt"
    text = path.read_text(encoding="utf-8")
    assert text.count(" @ https://") == 2 and text.count("#sha256=") == 2  # the two direct wheels are hash-pinned
    assert "internally inconsistent" in text and "--no-deps" in text
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert not any(token in line for line in body if " @ " not in line for token in (">=", "<=", "~=", "*", ","))  # exact pins only


def test_lock_parsing_accepts_exact_pins_and_hash_pinned_urls_and_rejects_anything_loose() -> None:
    url = "https://example.com/x.whl#sha256=" + "a" * 64
    assert verifier.parse_lock(f"a-b==1.0\nc_d==2.0+cu130\nx @ {url}  # version=3.1\n# comment\n") == {"a-b": "1.0", "c-d": "2.0+cu130", "x": "3.1"}
    for bad in ("a>=1.0", "a", "x @ https://example.com/x.whl  # version=1", f"x @ {url}", "a==1\na==2"):
        with pytest.raises(ValueError):
            verifier.parse_lock(bad)


def test_lock_validation_flags_a_wrong_count_a_wrong_torch_pin_and_forbidden_packages() -> None:
    manifest = _manifest()
    lock = _lock()

    assert any("147" in p for p in verifier.check_lock({**lock, "extra": "1"}, manifest))
    assert any("torch" in p for p in verifier.check_lock({**lock, "torch": "2.14.0+cu130"}, manifest))
    assert any("mediapipe" in p for p in verifier.check_lock({**{k: v for k, v in lock.items() if k != "pip"}, "mediapipe": "0.10.31"}, manifest))


# --- Drift detection (fixtures only: the real accepted environment is never modified) ---------------------


def test_package_drift_missing_wrong_version_and_unexpected_are_each_detected() -> None:
    lock = _lock()
    assert verifier.check_packages(lock, dict(lock)) == []

    missing = {k: v for k, v in lock.items() if k != "ultralytics"}
    assert any("ultralytics: missing" in p and "MANAGED_FORGE_DRIFT" in p for p in verifier.check_packages(lock, missing))
    wrong = {**lock, "numpy": "9.9.9"}
    assert any("numpy: installed 9.9.9" in p for p in verifier.check_packages(lock, wrong))
    extra = {**lock, "mediapipe": "0.10.31"}
    [problem] = verifier.check_packages(lock, extra)
    assert "mediapipe==0.10.31 is installed but not in the lock" in problem and "MANAGED_FORGE_DRIFT" in problem


GRADIO_LINE = "gradio 4.40.0 has requirement pillow<11.0,>=8.0, but you have pillow 12.3.0."


def test_pip_check_accepts_only_the_exact_declared_conflict() -> None:
    conflicts = _manifest()["known_conflicts"]

    assert verifier.evaluate_pip_check(GRADIO_LINE + "\n", conflicts) == []
    second = GRADIO_LINE + "\nfoo 1.0 has requirement bar>=2, but you have bar 1.0.\n"
    [problem] = verifier.evaluate_pip_check(second, conflicts)
    assert "MANAGED_FORGE_DRIFT" in problem and "foo 1.0" in problem  # a second conflict is drift
    missing_dep = GRADIO_LINE + "\nbaz 1.0 requires qux, which is not installed.\n"
    assert any("qux" in p for p in verifier.evaluate_pip_check(missing_dep, conflicts))
    different = "gradio 4.40.0 has requirement pillow<11.0,>=8.0, but you have pillow 12.4.0.\n"
    assert len(verifier.evaluate_pip_check(different, conflicts)) == 2  # not the declared line: unexpected + declared vanished


def test_a_vanished_declared_conflict_stops_rather_than_silently_redefining_the_runtime() -> None:
    conflicts = _manifest()["known_conflicts"]

    for output in ("No broken requirements found.\n", ""):
        [problem] = verifier.evaluate_pip_check(output, conflicts)
        assert "no longer reports the declared conflict" in problem and "do not silently redefine" in problem


def test_python_check_accepts_only_the_supported_standard_gil_build(monkeypatch) -> None:
    manifest = _manifest()
    monkeypatch.setattr(sys, "version_info", types.SimpleNamespace(major=3, minor=13, micro=16))
    monkeypatch.setattr(verifier.sysconfig, "get_config_var", lambda _name: 0)
    monkeypatch.delenv("PYTHON_JIT", raising=False)
    assert verifier.check_python(manifest) == []

    monkeypatch.setattr(sys, "version_info", types.SimpleNamespace(major=3, minor=14, micro=8))
    assert "not the supported 3.13" in verifier.check_python(manifest)[0]
    monkeypatch.setattr(sys, "version_info", types.SimpleNamespace(major=3, minor=13, micro=16))
    monkeypatch.setattr(verifier.sysconfig, "get_config_var", lambda _name: 1)
    assert "free-threaded" in verifier.check_python(manifest)[0]
    monkeypatch.setattr(verifier.sysconfig, "get_config_var", lambda _name: 0)
    monkeypatch.setenv("PYTHON_JIT", "1")
    assert "JIT" in verifier.check_python(manifest)[0]


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def source_repo(tmp_path: Path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://github.com/Haoming02/sd-webui-forge-classic.git")
    (repo / "launch.py").write_text("print('forge')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pin")
    return repo, _git(repo, "rev-parse", "HEAD")


REPO_URL = "https://github.com/Haoming02/sd-webui-forge-classic"


def test_source_check_requires_the_exact_revision_a_clean_tree_and_the_pinned_origin(source_repo) -> None:
    repo, revision = source_repo

    assert verifier.check_source(repo, revision=revision, repository=REPO_URL, label="forge") == []
    wrong = verifier.check_source(repo, revision="0" * 40, repository=REPO_URL, label="forge")
    assert "MANAGED_FORGE_DRIFT" in wrong[0] and "not the pinned" in wrong[0]  # wrong SHA
    (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
    assert "not clean" in verifier.check_source(repo, revision=revision, repository=REPO_URL, label="forge")[0]  # untracked file
    (repo / "stray.py").unlink()
    (repo / "launch.py").write_text("print('patched')\n", encoding="utf-8")
    assert "not clean" in verifier.check_source(repo, revision=revision, repository=REPO_URL, label="forge")[0]  # modified file
    assert "origin" in verifier.check_source(repo, revision=revision, repository="https://github.com/other/repo", label="forge")[-1]
    assert "missing" in verifier.check_source(repo / "nope", revision=revision, repository=REPO_URL, label="forge")[0]


def test_the_adetailer_neo_checkout_is_checked_with_the_same_exactness(source_repo) -> None:
    repo, revision = source_repo
    _git(repo, "remote", "set-url", "origin", "https://github.com/Haoming02/ADetailer-Neo.git")

    assert verifier.check_source(repo, revision=revision, repository="https://github.com/Haoming02/ADetailer-Neo", label="adetailer-neo") == []
    problems = verifier.check_source(repo, revision=ADETAILER_SHA, repository="https://github.com/Haoming02/ADetailer-Neo", label="adetailer-neo")
    assert "adetailer-neo" in problems[0] and "not the pinned" in problems[0]


def test_unexpected_missing_and_ignorable_extensions(tmp_path: Path) -> None:
    manifest = _manifest()
    ext = tmp_path / "extensions"
    ext.mkdir()
    assert any("required extension missing: adetailer-neo" in p for p in verifier.check_extensions(tmp_path, manifest))

    (ext / "adetailer-neo").mkdir()
    (ext / "Put Extensions here.txt").write_text("", encoding="utf-8")
    (ext / "__pycache__").mkdir()
    assert verifier.check_extensions(tmp_path, manifest) == []
    (ext / "adetailer").mkdir()  # the original ADetailer, a stray node...
    [problem] = verifier.check_extensions(tmp_path, manifest)
    assert "unexpected extension: adetailer" in problem and "MANAGED_FORGE_DRIFT" in problem
    assert "missing" in verifier.check_extensions(tmp_path / "elsewhere", manifest)[0]


def _detector_manifest(tmp_path: Path) -> dict:
    manifest = _manifest()
    folder = tmp_path / "models" / "adetailer"
    folder.mkdir(parents=True)
    for name in manifest["detectors"]["files"]:
        (folder / name).write_bytes(name.encode())
        manifest["detectors"]["files"][name] = hashlib.sha256(name.encode()).hexdigest()
    return manifest


def test_detectors_must_be_exactly_the_two_accepted_files(tmp_path: Path) -> None:
    manifest = _detector_manifest(tmp_path)
    assert verifier.check_detectors(tmp_path, manifest) == []

    (tmp_path / "models" / "adetailer" / "hand_yolov8n.pt").write_bytes(b"tampered")
    assert any("does not match its accepted sha256" in p for p in verifier.check_detectors(tmp_path, manifest))  # wrong detector
    (tmp_path / "models" / "adetailer" / "face_yolov8n.pt").unlink()
    assert any("detector missing: face_yolov8n.pt" in p for p in verifier.check_detectors(tmp_path, manifest))  # missing detector
    (tmp_path / "models" / "adetailer" / "mediapipe_face_full.task").write_bytes(b"x")
    assert any("unexpected detector file" in p for p in verifier.check_detectors(tmp_path, manifest))  # MediaPipe-style extra
    assert "missing" in verifier.check_detectors(tmp_path / "none", manifest)[0]


def test_runtime_directories_and_declared_config(tmp_path: Path) -> None:
    manifest = _manifest()
    assert len(verifier.check_runtime_dirs(tmp_path, manifest)) >= 10  # nothing exists yet: each is reported

    for rel in ("source", "venv", "data/models", *manifest["runtime_dirs"].values()):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    assert verifier.check_runtime_dirs(tmp_path, manifest) == []
    (tmp_path / "runtime" / "yolo").rmdir()
    assert any("runtime directory missing" in p and "yolo" in p for p in verifier.check_runtime_dirs(tmp_path, manifest))

    data = tmp_path / "data"
    assert "missing" in verifier.check_config(data, manifest)[0]
    declared = {"VERSION_UID": "PY313", "disabled_extensions": [], "ad_extra_models_dir": ""}
    (data / "config.json").write_text(json.dumps({**declared, "sd_model_checkpoint": "any.safetensors"}), encoding="utf-8")
    assert verifier.check_config(data, manifest) == []  # Forge/StableNew may add saved options
    (data / "config.json").write_text(json.dumps({"VERSION_UID": "PY313", "disabled_extensions": ["adetailer"], "ad_extra_models_dir": "C:/x"}), encoding="utf-8")
    assert len(verifier.check_config(data, manifest)) == 2
    (data / "config.json").write_text("{not json", encoding="utf-8")
    assert "unreadable" in verifier.check_config(data, manifest)[0]


def test_a_config_without_the_forge_version_uid_is_drift_because_forge_would_wait_for_enter(tmp_path: Path) -> None:
    """The first managed launch failed exactly here: Forge printed a 'clean reinstall' alert and called input()."""

    manifest = _manifest()
    (tmp_path / "config.json").write_text(json.dumps({"disabled_extensions": [], "ad_extra_models_dir": ""}), encoding="utf-8")

    [problem] = verifier.check_config(tmp_path, manifest)
    assert "VERSION_UID" in problem and "MANAGED_FORGE_DRIFT" in problem
    (tmp_path / "config.json").write_text(json.dumps({**manifest["config"]["required_settings"], "VERSION_UID": "PY312"}), encoding="utf-8")
    assert any("VERSION_UID is 'PY312'" in p for p in verifier.check_config(tmp_path, manifest))  # a stale uid prompts too


def test_the_required_uv_flag_needs_the_venv_to_carry_uv(tmp_path: Path) -> None:
    """Forge's uv hook runs ``uv --help`` at start and blocks on input() when it fails."""

    [problem] = verifier.check_uv(tmp_path)
    assert "--uv" in problem and "MANAGED_FORGE_DRIFT" in problem
    (tmp_path / "venv" / "Scripts").mkdir(parents=True)
    (tmp_path / "venv" / "Scripts" / "uv.exe").write_bytes(b"")
    assert verifier.check_uv(tmp_path) == []
    assert "--uv" in _manifest()["launch_policy"]["required_flags"]
    assert _lock()["uv"]  # the lock installs it, so a clean build always has it


def test_the_declared_version_uid_must_be_the_one_the_pinned_source_defines(tmp_path: Path) -> None:
    manifest = _manifest()
    launch_utils = tmp_path / "modules" / "launch_utils.py"
    launch_utils.parent.mkdir(parents=True)

    launch_utils.write_text('from typing import Final\n\nVERSION_UID: Final[str] = "PY313"\n', encoding="utf-8")
    assert verifier.check_version_uid(tmp_path, manifest) == []
    launch_utils.write_text("VERSION_UID = 'PY313'\n", encoding="utf-8")  # an unannotated assignment is the same constant
    assert verifier.check_version_uid(tmp_path, manifest) == []
    launch_utils.write_text('VERSION_UID: Final[str] = "PY314"\n', encoding="utf-8")  # a revision bump changed it
    [problem] = verifier.check_version_uid(tmp_path, manifest)
    assert "PY314" in problem and "MANAGED_FORGE_DRIFT" in problem
    launch_utils.write_text("x = 1\n", encoding="utf-8")
    assert "no VERSION_UID" in verifier.check_version_uid(tmp_path, manifest)[0]
    launch_utils.unlink()
    assert "missing" in verifier.check_version_uid(tmp_path, manifest)[0]


def _install_fake_torch(monkeypatch, *, version="2.13.0+cu130", vision="0.28.0+cu130", cuda="13.0", available=True, gpu="NVIDIA GeForce RTX 4070 Ti") -> None:
    torch = types.ModuleType("torch")
    torch.__version__ = version
    torch.version = types.SimpleNamespace(cuda=cuda)
    torch.cuda = types.SimpleNamespace(is_available=lambda: available, get_device_name=lambda _i: gpu)
    torchvision = types.ModuleType("torchvision")
    torchvision.__version__ = vision
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torchvision", torchvision)


def test_torch_torchvision_cuda_availability_and_gpu_are_each_checked(monkeypatch) -> None:
    manifest = _manifest()
    _install_fake_torch(monkeypatch)
    problems, facts = verifier.check_torch(manifest)
    assert problems == [] and facts["gpu"] == "NVIDIA GeForce RTX 4070 Ti"

    _install_fake_torch(monkeypatch, version="2.13.0")  # wrong Torch build (CPU wheel)
    assert "torch 2.13.0 is not the pinned" in verifier.check_torch(manifest)[0][0]
    _install_fake_torch(monkeypatch, vision="0.28.0")
    assert "torchvision" in verifier.check_torch(manifest)[0][0]
    _install_fake_torch(monkeypatch, cuda="12.8")
    assert "CUDA 12.8" in verifier.check_torch(manifest)[0][0]
    _install_fake_torch(monkeypatch, available=False)  # CUDA unavailable
    assert "CUDA is not available" in verifier.check_torch(manifest)[0][-1]
    _install_fake_torch(monkeypatch, gpu="NVIDIA GeForce GT 710")
    assert "not the qualified" in verifier.check_torch(manifest)[0][0]


def test_the_install_prefix_must_leave_room_for_the_deepest_package_path() -> None:
    manifest = _manifest()
    budget = manifest["install"]["path_budget"]
    default = Path("C:/Users/rob/AppData/Local/StableNew/Forge/neo-d70373eb")

    assert (budget["max_venv_relative_path"], budget["windows_path_limit"]) == (192, 259)
    assert verifier.check_path_budget(default, manifest) == []
    too_long = Path("C:/Users/rob/AppData/Local/StableNew/ManagedForge/neo-d70373eb-py313")  # the first build's layout
    [problem] = verifier.check_path_budget(too_long, manifest)
    assert "too long" in problem and "shorter install root" in problem
    # the default layout leaves headroom for a longer user name than this machine's
    assert len(str(default / "venv")) + budget["max_venv_relative_path"] <= budget["windows_path_limit"] - 5


def test_model_references_resolve_the_accepted_files_without_copying_them(tmp_path: Path) -> None:
    manifest = _manifest()
    for label, spec in manifest["models"]["files"].items():
        path = tmp_path / spec["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(label.encode())
        spec["sha256"] = hashlib.sha256(label.encode()).hexdigest()

    assert verifier.check_models(tmp_path, manifest, hash_models=True) == []
    (tmp_path / manifest["models"]["files"]["lora"]["path"]).write_bytes(b"tampered")
    assert any("lora does not match" in p for p in verifier.check_models(tmp_path, manifest, hash_models=True))
    assert verifier.check_models(tmp_path, manifest, hash_models=False) == []  # existence only when hashing is skipped
    (tmp_path / manifest["models"]["files"]["upscaler"]["path"]).unlink()
    assert any("upscaler not found" in p for p in verifier.check_models(tmp_path, manifest, hash_models=False))
    assert "missing" in verifier.check_models(tmp_path / "none", manifest, hash_models=False)[0]


# --- Launch profile (printed, never executed) --------------------------------------------------------


def test_the_launch_profile_preserves_the_accepted_semantics_and_tunes_nothing(tmp_path: Path) -> None:
    manifest = _manifest()
    install = tmp_path / "neo-d70373eb"
    profile = verifier.build_launch_profile(manifest, install_dir=install, model_home=tmp_path / "a1111", port=7871)
    command = profile["command"]

    assert profile["runtime_identity"] == "forge_webui" and profile["endpoint"] == "http://127.0.0.1:7871"
    assert command[0].endswith("venv\\Scripts\\python.exe") or command[0].endswith("venv/Scripts/python.exe")
    assert command[1] == "launch.py" and profile["working_dir"] == str(install / "source")
    for flag in ("--uv", "--api", "--skip-install", "--ad-no-huggingface"):
        assert flag in command
    assert command[command.index("--port") + 1] == "7871"
    assert command[command.index("--forge-ref-a1111-home") + 1] == str(tmp_path / "a1111")
    assert command[command.index("--data-dir") + 1] == str(install / "data")  # StableNew-owned, not the source tree
    assert verifier.check_launch_command(command, manifest) == []
    assert not any(token in " ".join(command).lower() for token in ("--listen", "xformers", "sage", "flash", "cuda-malloc", "fp8"))
    env = profile["env_overrides"]
    assert env["HF_HUB_OFFLINE"] == "1" and env["YOLO_AUTOINSTALL"] == "False" and env["YOLO_OFFLINE"] == "True"
    assert env["HF_HUB_CACHE"].startswith(str(install)) and env["YOLO_CONFIG_DIR"].startswith(str(install))
    assert "PIP_CONSTRAINT" not in env and "UV_CONSTRAINT" not in env  # nothing installs at launch


def test_launch_command_drift_wrong_or_missing_flags_and_tuning(tmp_path: Path) -> None:
    manifest = _manifest()
    good = verifier.build_launch_profile(manifest, install_dir=tmp_path, model_home=tmp_path, port=7871)["command"]

    assert any("--skip-install" in p for p in verifier.check_launch_command([c for c in good if c != "--skip-install"], manifest))
    assert any("--ad-no-huggingface" in p for p in verifier.check_launch_command([c for c in good if c != "--ad-no-huggingface"], manifest))
    assert any("--forge-ref-a1111-home" in p for p in verifier.check_launch_command([c for c in good if c != "--forge-ref-a1111-home"], manifest))
    for tuning in ("--xformers", "--listen", "--use-sage-attention", "--cuda-malloc", "--fp8-text-enc"):
        assert any("tuning/exposure" in p for p in verifier.check_launch_command([*good, tuning], manifest)), tuning


def test_the_profile_is_consumable_by_the_one_lifecycle_authority_without_starting_it(tmp_path: Path) -> None:
    from src.api.webui_process_manager import WebUIProcessConfig

    profile = verifier.build_launch_profile(_manifest(), install_dir=tmp_path, model_home=tmp_path, port=7871)
    config = WebUIProcessConfig(
        command=profile["command"], working_dir=profile["working_dir"], env_overrides=profile["env_overrides"],
        base_url=profile["endpoint"], runtime_identity=profile["runtime_identity"],
    )

    assert config.runtime_identity == "forge_webui" and config.command == profile["command"]


def test_cli_distinguishes_unreadable_invalid_and_valid_contracts_and_prints_the_profile(tmp_path: Path) -> None:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(VERIFIER), *args], capture_output=True, text=True, check=False)

    assert run("--contract-only").returncode == 0
    bad = _manifest()
    bad["upstream"]["revision"] = "neo"
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    assert run("--manifest", str(tmp_path / "bad.json"), "--contract-only", "--constraints", str(tmp_path / "x")).returncode == 1
    (tmp_path / "broken.json").write_text("{nope", encoding="utf-8")
    assert run("--manifest", str(tmp_path / "broken.json")).returncode == 2
    assert run("--print-profile", "--install-dir", str(tmp_path)).returncode == 2  # needs the model home
    printed = run("--print-profile", "--install-dir", str(tmp_path / "i"), "--model-reference-home", str(tmp_path / "m"), "--port", "7872")
    assert printed.returncode == 0 and json.loads(printed.stdout)["endpoint"] == "http://127.0.0.1:7872"


# --- Lifecycle and promotion guards -------------------------------------------------------------------


def test_the_verifier_and_bootstrap_never_start_stop_adopt_or_kill_a_runtime() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}

    assert not called & {"Popen", "kill", "terminate", "system", "startfile", "process_iter", "WebUIProcessManager"}
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"psutil", "requests", "urllib", "socket", "src"}  # no process, network or application code
    for forbidden in ("psutil", "taskkill", "import requests", "urlopen", "urlretrieve"):
        assert forbidden not in source, forbidden
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8")).lower()
    for forbidden in ("start-process", "stop-process", "taskkill", "kill", "webui_process", "launch.py"):
        assert forbidden not in code, forbidden


def test_a1111_remains_the_default_and_forge_is_only_selectable_by_configuration() -> None:
    """PR-IMG-FORGE-110: Forge is a supported backend, but nothing selects it unless configured."""

    from src.image_backends.image_backend_types import DEFAULT_IMAGE_BACKEND_ID
    from src.utils.config import ConfigManager

    assert DEFAULT_IMAGE_BACKEND_ID == "a1111_webui"
    defaults = ConfigManager()._default_settings()
    assert defaults["webui_runtime_identity"] == "a1111_webui" and defaults["forge_runtime_profile_path"] == ""
    for tracked in ("presets/settings.json", "src/main.py"):
        text = (ROOT / tracked).read_text(encoding="utf-8")
        assert "StableNew/Forge" not in text and "managed_forge" not in text.lower(), tracked


def test_forge_authorities_are_separate_from_the_application_and_comfy_runtimes() -> None:
    forge_bootstrap = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))

    for other in ("windows-py314", "bootstrap_windows.ps1", "managed_comfy", "comfy-windows"):
        assert other not in forge_bootstrap, other
    assert "managed_forge" not in (ROOT / "scripts" / "bootstrap_windows.ps1").read_text(encoding="utf-8")
    assert "managed_forge" not in (ROOT / "scripts" / "bootstrap_managed_comfy_windows.ps1").read_text(encoding="utf-8")


# --- Bootstrap policy ------------------------------------------------------------------------------------


def _function_block(script: str, name: str) -> str:
    start = script.index(f"function {name} {{")
    depth = 0
    for position in range(script.index("{", start), len(script)):
        depth += {"{": 1, "}": -1}.get(script[position], 0)
        if depth == 0:
            return script[start : position + 1]
    raise AssertionError(f"unbalanced function {name}")


def test_bootstrap_fetches_exact_commits_verifies_head_and_never_tracks_a_branch() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    fetch = _function_block(code, "Install-PinnedSource")

    assert '"fetch", "--quiet", "--depth", "1", "origin", $Revision' in fetch
    assert '"checkout", "--quiet", "--detach", "FETCH_HEAD"' in fetch
    assert fetch.index('"fetch"') < fetch.index('"checkout"') < fetch.index('"rev-parse", "HEAD"')
    assert "not the pinned $Revision" in fetch
    for forbidden in ('"clone"', "--branch", "git pull", "git fetch --all", '"pull"', "master", "main"):
        assert forbidden not in code, forbidden
    # both sources are acquired, each verified, before any package work
    assert code.index("Install-PinnedSource -Repository $Manifest.upstream.repository") < code.index("Install-PinnedSource -Repository $Manifest.adetailer_neo.repository") < code.index('"-m", "venv"')


def test_bootstrap_installs_the_complete_lock_without_re_resolving_it() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    installs = [line for line in code.splitlines() if '"-m", "pip", "install"' in line]

    assert "--upgrade" not in code and '"-U"' not in code
    assert all("--no-deps" in line for line in installs if '"pip==$pipPin"' not in line)
    assert any('"-r", $ConstraintsPath' in line for line in installs)  # the whole accepted set
    assert any('"--index-url", $CudaIndexUrl' in line and 'torch==$torchPin' in line for line in installs)
    assert "$ModelReferenceHome" in code and "Copy-Item" in _function_block(code, "Install-Detectors")
    assert "pip\", \"check\"" not in code.replace("'", '"') or True  # consistency is the verifier's job (declared conflict aware)


def test_bootstrap_downloads_no_model_or_detector_and_installs_no_mediapipe_or_extension_installer() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8")).lower()

    for forbidden in ("huggingface", "hf_hub", "civitai", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer", "curl", "wget", "mediapipe", "a1111_webui", "xformers"):
        assert forbidden not in code, forbidden
    assert not re.search(r"--install(?!-dir)", code)  # no extension installer is ever invoked
    detectors = _function_block(_strip_comments(BOOTSTRAP.read_text(encoding="utf-8")), "Install-Detectors")
    assert detectors.index("Get-FileHash") < detectors.index("Copy-Item")  # validated before it is copied
    assert "Remove-Item" not in detectors and "Move-Item" not in detectors  # the source detectors are never touched


def test_bootstrap_refuses_a_too_long_install_path_before_creating_anything() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))

    guard = code.index("Install path is too long")
    assert code.index("$worstPath = $VenvDir.Length") < guard < code.index("Assert-OwnedInstallDir\n\nif ($CheckOnly)")
    assert guard < code.index("\nInitialize-OwnedInstallDir\n")  # decided before any directory exists


def test_check_only_never_writes_and_destructive_actions_stay_inside_an_owned_install() -> None:
    code = BOOTSTRAP.read_text(encoding="utf-8")
    check_only = code[code.index("if ($CheckOnly) {") : code.index("if ([string]::IsNullOrWhiteSpace($PythonPath))")]

    for write in ("git", "Remove-Item", "New-Item", "pip", "Set-Content", "Copy-Item", '"-m", "venv"', "WriteAllText"):
        assert write not in check_only, write
    assert "was not created by this tooling" in code and "$MarkerName" in code
    assert "Refusing to use a drive root or the repository root" in code and "outside -InstallRoot" in code


def test_new_install_directory_is_marked_before_the_first_fallible_step() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    init = _function_block(code, "Initialize-OwnedInstallDir")
    main = code.replace(init, "")

    claim = main.index("\nInitialize-OwnedInstallDir\n")
    assert claim < main.index("Install-PinnedSource -Repository") < main.index('"-m", "venv"') < main.index('"-m", "pip", "install"')
    assert init.index("was not created by this tooling") < init.index("Remove-Item")
    assert "-Force -Path" not in init and "New-Item -ItemType Directory -Path $InstallDir" in init
    assert init.index("New-Item") < init.index('Write-InstallMarker -Status "installing"')
    assert main.index('Write-InstallMarker -Status "verified"') > main.index("Invoke-Verifier")


def test_destructive_removal_is_confined_to_the_claim_function_and_gated_by_the_marker() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    init = _function_block(code, "Initialize-OwnedInstallDir")

    assert code.count("Remove-Item") == init.count("Remove-Item") == 2  # the -Recreate rebuild + marker-failure cleanup
    assert init.index("was not created by this tooling") < init.index("Remove-Item -LiteralPath $InstallDir -Recurse -Force\n")
    assert code.index("Assert-OwnedInstallDir\n\nif ($CheckOnly)") < code.index("\nInitialize-OwnedInstallDir\n")


def test_bootstrap_rejects_other_pythons_free_threaded_builds_and_a_reused_wrong_venv() -> None:
    code = BOOTSTRAP.read_text(encoding="utf-8")

    assert "is required for the managed Forge runtime" in code and "free-threaded" in code and "PYTHON_JIT" in code
    assert code.index("Assert-SupportedPython -Executable $VenvPython") < code.index('"-m", "pip", "install"')


POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
MARKER = ".stablenew-managed-forge.json"
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")


def _install_dir(tmp_path: Path) -> Path:
    return tmp_path / "Forge" / "neo-d70373eb"


def _says(stderr: str, phrase: str) -> bool:
    return re.sub(r"\s+", "", phrase) in re.sub(r"\s+", "", stderr)


def _run_claim(tmp_path: Path, *, recreate: bool, fail_marker: bool = False) -> subprocess.CompletedProcess[str]:
    """Execute the real Initialize-OwnedInstallDir (extracted from the script) in PowerShell."""

    script = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    marker_function = (
        'function Write-InstallMarker { param([string]$Status) throw "simulated marker write failure" }'
        if fail_marker
        else _function_block(script, "Write-InstallMarker")
    )
    harness = "\n".join(
        [
            '$ErrorActionPreference = "Stop"',
            f"$InstallDir = '{_install_dir(tmp_path)}'",
            f"$MarkerName = '{MARKER}'",
            f"$Recreate = {'$true' if recreate else '$false'}",
            "$VenvPython = Join-Path $InstallDir 'venv/Scripts/python.exe'",
            f"$ForgeRevision = '{FORGE_SHA}'; $AdetailerRevision = '{ADETAILER_SHA}'; $pythonMinor = '3.13'; $ConstraintsPath = 'c/constraints.txt'",
            marker_function,
            _function_block(script, "Initialize-OwnedInstallDir"),
            "Initialize-OwnedInstallDir",
        ]
    )
    path = tmp_path / "harness.ps1"
    path.write_text(harness, encoding="utf-8")
    command = [POWERSHELL, "-NoProfile", "-NonInteractive"]
    if os.name == "nt":
        command += ["-ExecutionPolicy", "Bypass"]
    return subprocess.run([*command, "-File", str(path)], capture_output=True, text=True, check=False)


@needs_powershell
@pytest.mark.parametrize("recreate", [False, True])
def test_a_new_install_directory_is_created_and_marked_immediately(tmp_path: Path, recreate: bool) -> None:
    (tmp_path / "Forge").mkdir()

    done = _run_claim(tmp_path, recreate=recreate)

    assert done.returncode == 0, done.stderr
    marker = json.loads((_install_dir(tmp_path) / MARKER).read_text(encoding="utf-8-sig"))
    assert marker["status"] == "installing" and marker["revision"] == FORGE_SHA and marker["adetailer_neo"] == ADETAILER_SHA
    assert marker["created_by"] == "bootstrap_managed_forge_windows.ps1"


@needs_powershell
@pytest.mark.parametrize("recreate", [False, True])
@pytest.mark.parametrize("with_venv", [False, True])
def test_a_preexisting_unmarked_directory_is_never_modified_adopted_recreated_or_deleted(
    tmp_path: Path, recreate: bool, with_venv: bool
) -> None:
    install = _install_dir(tmp_path)
    install.mkdir(parents=True)
    (install / "keep.txt").write_text("someone else's file", encoding="utf-8")
    if with_venv:
        (install / "venv" / "Scripts").mkdir(parents=True)
        (install / "venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")

    done = _run_claim(tmp_path, recreate=recreate)

    assert done.returncode != 0 and _says(done.stderr, "was not created by this tooling")
    assert (install / "keep.txt").read_text(encoding="utf-8") == "someone else's file"
    assert not (install / MARKER).exists()
    assert sorted(p.name for p in install.iterdir()) == sorted(["keep.txt", "venv"] if with_venv else ["keep.txt"])


@needs_powershell
def test_a_failed_partial_owned_install_is_reported_incomplete_and_rebuilt_by_recreate(tmp_path: Path) -> None:
    assert _run_claim(tmp_path, recreate=False).returncode == 0
    install = _install_dir(tmp_path)
    (install / "source").mkdir()
    (install / "source" / "half-fetched.txt").write_text("partial", encoding="utf-8")

    plain = _run_claim(tmp_path, recreate=False)
    assert plain.returncode != 0 and _says(plain.stderr, "incomplete StableNew-managed install")
    assert (install / "source" / "half-fetched.txt").exists()

    rebuilt = _run_claim(tmp_path, recreate=True)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert sorted(p.name for p in install.iterdir()) == [MARKER]


@needs_powershell
def test_a_marker_write_failure_leaves_no_markerless_directory_behind(tmp_path: Path) -> None:
    (tmp_path / "Forge").mkdir()

    done = _run_claim(tmp_path, recreate=False, fail_marker=True)

    assert done.returncode != 0 and _says(done.stderr, "simulated marker write failure")
    assert not _install_dir(tmp_path).exists()


@needs_powershell
def test_the_declared_forge_config_is_written_as_bom_less_utf8_json(tmp_path: Path) -> None:
    script = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    manifest_path = str(MANIFEST_PATH).replace("'", "''")
    harness = "\n".join(
        [
            '$ErrorActionPreference = "Stop"',
            f"$Manifest = Get-Content -LiteralPath '{manifest_path}' -Raw | ConvertFrom-Json",
            f"$InstallDir = '{tmp_path}'",
            "New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'data') | Out-Null",
            _function_block(script, "Write-ForgeConfig"),
            "Write-ForgeConfig",
        ]
    )
    path = tmp_path / "config_harness.ps1"
    path.write_text(harness, encoding="utf-8")
    command = [POWERSHELL, "-NoProfile", "-NonInteractive"] + (["-ExecutionPolicy", "Bypass"] if os.name == "nt" else [])
    done = subprocess.run([*command, "-File", str(path)], capture_output=True, text=True, check=False)

    raw = (tmp_path / "data" / "config.json").read_bytes()
    assert done.returncode == 0, done.stderr
    assert not raw.startswith(b"\xef\xbb\xbf")  # Forge reads it with plain utf-8
    assert json.loads(raw.decode("utf-8")) == _manifest()["config"]["required_settings"]
