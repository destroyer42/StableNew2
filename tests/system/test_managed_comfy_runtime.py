"""StableNew-managed ComfyUI runtime authority (PR-COMFY-RUNTIME-100).

Deterministic and GPU-free: the runtime contract, its exact constraints, the read-only verifier and
the bootstrap's safety policy. The real candidate builds and physical runs are runtime evidence.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tools.runtime import verify_managed_comfy as verifier
from tools.runtime import verify_runtime_pins as pins

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config" / "managed_comfy_runtime.json"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_managed_comfy_windows.ps1"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _strip_comments(script: str) -> str:
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


# --- The contract ---------------------------------------------------------------------------


def test_contract_pins_an_exact_stable_release_python_313_and_the_cuda_torch_family() -> None:
    manifest = _manifest()

    assert verifier.validate_manifest(manifest) == []
    assert manifest["upstream"]["release"] == "v0.38.0"
    assert manifest["upstream"]["revision"] == "6b747c0428c343e1417219641db93a4fb7cb69ae"
    assert manifest["python"] == {
        "minor": "3.13",
        "implementation": "CPython",
        "free_threaded": False,
        "jit": False,
    }
    assert manifest["torch"]["torch"] == "2.14.0+cu130"
    assert manifest["torch"]["torchvision"].endswith("+cu130")
    assert manifest["torch"]["cuda"] == "13.0"


def test_contract_owns_installation_identity_not_workflow_facts() -> None:
    manifest = _manifest()
    manifest.pop("description")  # prose that names what the contract deliberately does not own
    text = json.dumps(manifest).lower()

    for workflow_fact in ("sha256", "wan22", "animate", "unet", "frame", "graph", "min_available"):
        assert workflow_fact not in text, workflow_fact


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m["upstream"].update(release="master"), "exact stable tag"),
        (lambda m: m["upstream"].update(revision="6b747c0"), "40-hex"),
        (lambda m: m["upstream"].update(version="0.37.0"), "without the leading v"),
        (lambda m: m["python"].update(minor="3"), "single minor"),
        (lambda m: m["python"].update(free_threaded=True), "standard-GIL"),
        (lambda m: m["torch"].update(torch="2.14.0"), "+cu130"),
        (lambda m: m.update(constraints="constraints/windows-py314-cu130.txt"), "not the application"),
        (lambda m: m["launch_policy"].update(listen="0.0.0.0"), "loopback"),
        (lambda m: m["launch_policy"].update(required_flags=["--disable-auto-launch"]), "pinned-memory"),
        (lambda m: m["custom_nodes"].update(policy="allow"), "no third-party"),
    ],
)
def test_invalid_contracts_are_rejected(mutate, expected) -> None:
    manifest = copy.deepcopy(_manifest())
    mutate(manifest)

    assert any(expected in problem for problem in verifier.validate_manifest(manifest))


# --- Exact constraints ----------------------------------------------------------------------


def _constraints_path() -> Path:
    return ROOT / _manifest()["constraints"]


def test_comfy_constraints_are_exact_separate_and_target_this_release() -> None:
    path = _constraints_path()
    text = path.read_text(encoding="utf-8")
    parsed = pins.parse_profiles(text)
    header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
    manifest = _manifest()

    assert path.name != "windows-py314-cu130.txt"  # never the application authority
    assert parsed.postprocess == {} and parsed.core  # a single exact profile
    assert parsed.core["torch"] == manifest["torch"]["torch"]
    assert parsed.core["torchvision"] == manifest["torch"]["torchvision"]
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", parsed.core["pip"])
    assert {"comfy-kitchen", "comfy-aimdo", "comfyui-frontend-package"} <= set(parsed.core)
    assert "ComfyUI v0.38.0" in header and manifest["upstream"]["revision"] in header
    assert "CPython 3.13" in header and "cu130" in header
    for forbidden in ("file:", "://", "git+", "@ ", "-e ", "C:/", "C:\\", "master"):
        assert forbidden not in "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_comfy_and_application_runtimes_never_share_an_authority() -> None:
    comfy_bootstrap = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    app_bootstrap = (ROOT / "scripts" / "bootstrap_windows.ps1").read_text(encoding="utf-8")
    comfy_constraints = _constraints_path().read_text(encoding="utf-8")

    assert "windows-py314" not in comfy_bootstrap and "bootstrap_windows.ps1" not in comfy_bootstrap
    assert "comfy-windows" not in app_bootstrap and "managed_comfy" not in app_bootstrap
    comfy_pin_lines = [line for line in comfy_constraints.splitlines() if not line.startswith("#")]
    assert not any("windows-py314" in line for line in comfy_pin_lines)  # prose may name it, pins never
    app_pins = pins.parse_profiles((ROOT / "constraints" / "windows-py314-cu130.txt").read_text(encoding="utf-8"))
    assert "comfy-kitchen" not in app_pins.all_pins  # Comfy's packages never leak into the app profile


# --- The read-only verifier -----------------------------------------------------------------


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
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def source_repo(tmp_path: Path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "comfyui_version.py").write_text('__version__ = "0.38.0"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_source_check_requires_exact_revision_clean_tree_and_version(source_repo) -> None:
    repo, revision = source_repo

    assert verifier.check_source(repo, version="0.38.0", revision=revision) == []
    assert "not the pinned" in verifier.check_source(repo, version="0.38.0", revision="0" * 40)[0]
    assert "reports 0.38.0, expected 0.37.0" in verifier.check_source(repo, version="0.37.0", revision=revision)[0]
    (repo / "stray.py").write_text("x = 1\n", encoding="utf-8")
    assert "not clean" in verifier.check_source(repo, version="0.38.0", revision=revision)[0]
    assert "missing" in verifier.check_source(repo / "nope", version="0.38.0", revision=revision)[0]


def test_custom_node_policy_accepts_a_clean_core_install_and_flags_third_party_nodes(tmp_path: Path) -> None:
    allowed = _manifest()["custom_nodes"]["allowed_entries"]
    nodes = tmp_path / "custom_nodes"
    nodes.mkdir()
    for name in allowed:
        (nodes / name).mkdir() if name == "__pycache__" else (nodes / name).write_text("", encoding="utf-8")

    assert verifier.check_custom_nodes(tmp_path, allowed) == []  # no LTX bridge/GGUF is required
    (nodes / "StableNewLTXBridge").mkdir()
    (nodes / "ComfyUI-GGUF").mkdir()
    flagged = verifier.check_custom_nodes(tmp_path, allowed)
    assert len(flagged) == 2 and all("no third-party nodes" in item for item in flagged)
    assert "missing" in verifier.check_custom_nodes(tmp_path / "elsewhere", allowed)[0]


def _install_fake_torch(monkeypatch, *, version: str, cuda: str | None, available: bool) -> None:
    fake = types.ModuleType("torch")
    fake.__version__ = version
    fake.version = types.SimpleNamespace(cuda=cuda)
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: available, get_device_name=lambda _index: "NVIDIA GeForce RTX 4070 Ti"
    )
    monkeypatch.setitem(sys.modules, "torch", fake)


def test_torch_check_rejects_cpu_wrong_local_version_and_missing_cuda(monkeypatch) -> None:
    manifest = _manifest()
    _install_fake_torch(monkeypatch, version="2.14.0+cu130", cuda="13.0", available=True)
    problems, facts = verifier.check_torch(manifest)
    assert problems == [] and facts["gpu"] == "NVIDIA GeForce RTX 4070 Ti"

    _install_fake_torch(monkeypatch, version="2.14.0", cuda=None, available=False)  # CPU wheel
    problems, _facts = verifier.check_torch(manifest)
    assert len(problems) == 3 and any("CPU build" in item for item in problems)
    _install_fake_torch(monkeypatch, version="2.14.1+cu130", cuda="13.0", available=True)
    assert "not the pinned 2.14.0+cu130" in verifier.check_torch(manifest)[0][0]


def test_pin_check_detects_drift_in_both_directions() -> None:
    constraints = _constraints_path()
    pinned = pins.parse_profiles(constraints.read_text(encoding="utf-8")).all_pins
    assert verifier.check_pins(constraints, dict(pinned)) == []  # an exact match is clean

    wrong = {**pinned, "numpy": "9.9.9"}
    assert any("numpy" in item and "9.9.9" in item for item in verifier.check_pins(constraints, wrong))

    missing = {name: version for name, version in pinned.items() if name != "comfy-kitchen"}
    assert any("comfy-kitchen: missing" in item for item in verifier.check_pins(constraints, missing))

    # A stray distribution (a node's dependency, a manual pip install) is drift for this clean core.
    extra = {**pinned, "some-node-dependency": "1.0"}
    [problem] = verifier.check_pins(constraints, extra)
    assert "some-node-dependency==1.0 is installed but not pinned" in problem


def test_constraints_pin_the_complete_installed_set_including_torch_and_the_resolver() -> None:
    pinned = pins.parse_profiles(_constraints_path().read_text(encoding="utf-8")).all_pins

    # The complete installed set, so the verifier can reject drift in either direction: the resolver,
    # the CUDA Torch family, ComfyUI's three release-declared pins and the workflow-template packages
    # they pull in are all exact. torchaudio is deliberately absent (v0.38.0 no longer requires it).
    assert {"pip", "torch", "torchvision", "comfy-kitchen", "comfyui-frontend-package", "comfyui-workflow-templates"} <= set(pinned)
    assert "torchaudio" not in pinned
    assert any(name.startswith("comfyui-workflow-templates-") for name in pinned)
    assert all(re.fullmatch(r"\d+(\.\d+)*(\+cu130)?", version) for version in pinned.values())


def test_runtime_dir_check_reports_missing_folders_and_unreadable_model_paths(tmp_path: Path) -> None:
    manifest = _manifest()
    assert len(verifier.check_runtime_dir(manifest, tmp_path)) == 5  # four folders + model paths

    for folder in manifest["launch_policy"]["runtime_folders"]:
        (tmp_path / folder).mkdir()
    (tmp_path / "extra_model_paths.yaml").write_text("stablenew:\n  base_path: models\n", encoding="utf-8")
    assert verifier.check_runtime_dir(manifest, tmp_path) == []


def test_launch_command_is_loopback_owned_folders_with_the_required_flags(tmp_path: Path) -> None:
    command = verifier.build_launch_command(
        _manifest(), install_dir=tmp_path / "v0.38.0-py313", runtime_dir=tmp_path / "rt", port=8000
    )

    assert command[0].endswith("python.exe") and command[1].endswith("main.py")
    assert command[command.index("--listen") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8000"
    for flag, folder in (("--input-directory", "input"), ("--output-directory", "output"), ("--temp-directory", "temp"), ("--user-directory", "user")):
        assert command[command.index(flag) + 1] == str(tmp_path / "rt" / folder)
    assert "--disable-pinned-memory" in command and "--disable-auto-launch" in command
    assert "0.0.0.0" not in command and "--base-directory" not in command


def test_cli_distinguishes_unreadable_invalid_and_valid_contracts(tmp_path: Path, capsys) -> None:
    assert verifier.main(["--manifest", str(tmp_path / "missing.json"), "--contract-only"]) == 2
    bad = _manifest()
    bad["upstream"]["release"] = "master"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert verifier.main(["--manifest", str(path), "--contract-only"]) == 1
    assert verifier.main(["--contract-only"]) == 0
    assert "contract is valid" in capsys.readouterr().out


# --- Bootstrap safety policy ------------------------------------------------------------------


def test_bootstrap_installs_only_the_pinned_tag_verifies_its_commit_and_never_tracks_a_branch() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))

    assert '"--depth", "1", "--branch", $Release' in code
    assert code.index("rev-parse") < code.index('"-m", "pip", "install", "-c"')  # verified before any install
    assert "not the pinned $Revision" in code
    assert "'^v\\d+\\.\\d+\\.\\d+$'" in code  # exact stable tags only
    for forbidden in ("master", "--branch main", "git pull", "git fetch", "checkout"):
        assert forbidden not in code, forbidden


def test_bootstrap_constrains_every_install_and_pins_the_resolver() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    installs = [line for line in code.splitlines() if '"-m", "pip", "install"' in line]
    resolving = [line for line in installs if '"pip==$pipPin"' not in line]

    assert "--upgrade" not in code
    assert len(resolving) == 2 and all('"-c", $ConstraintsPath' in line for line in resolving)
    assert any('"--index-url", $CudaIndexUrl' in line and "$torchFamily" in line for line in resolving)
    assert '"-r", (Join-Path $SourceDir "requirements.txt")' in code  # what the release declares


def test_bootstrap_downloads_no_model_installs_no_custom_node_and_touches_no_other_runtime() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8")).lower()

    for forbidden in ("huggingface", "hf_hub", "civitai", "custom_nodes", "comfyui-manager", "a1111", "stable-diffusion-webui", "forge", "stop-process", "taskkill", "kill"):
        assert forbidden not in code, forbidden


def test_check_only_never_writes_and_destructive_actions_stay_inside_an_owned_install() -> None:
    code = BOOTSTRAP.read_text(encoding="utf-8")
    check_only = code[code.index("if ($CheckOnly) {") : code.index("if ([string]::IsNullOrWhiteSpace($PythonPath))")]

    for write in ("clone", "Remove-Item", "New-Item", "pip", "Set-Content", '"-m", "venv"'):
        assert write not in check_only, write
    assert "Refusing to delete" in code and "$MarkerName" in code  # only a tooling-created install
    assert "Refusing to use a drive root or the repository root" in code
    assert "outside -InstallRoot" in code


def test_bootstrap_rejects_other_pythons_free_threaded_builds_and_a_reused_wrong_venv() -> None:
    code = BOOTSTRAP.read_text(encoding="utf-8")

    assert "is required for the managed ComfyUI runtime" in code
    assert "free-threaded" in code and "PYTHON_JIT" in code
    assert code.index("Assert-SupportedPython -Executable $VenvPython") < code.index('"-m", "pip", "install"')


# --- Ownership: no process-name kill fallback ------------------------------------------------


def test_comfy_lifecycle_never_kills_by_name_or_adopts_an_unowned_process() -> None:
    source = (ROOT / "src" / "video" / "comfy_process_manager.py").read_text(encoding="utf-8")

    for forbidden in ("taskkill", "process_iter", "pkill", "killall", "psutil", "name ==", ".name()"):
        assert forbidden not in source, forbidden
    assert "refusing to adopt, stop, or replace it" in source
