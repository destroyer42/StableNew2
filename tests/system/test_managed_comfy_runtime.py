"""StableNew-managed ComfyUI runtime authority (PR-COMFY-RUNTIME-100).

Deterministic and GPU-free: the runtime contract, its exact constraints, the read-only verifier and
the bootstrap's safety policy. The real candidate builds and physical runs are runtime evidence.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
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
    assert "was not created by this tooling" in code and "$MarkerName" in code  # only a tooling-created install
    assert "Refusing to use a drive root or the repository root" in code
    assert "outside -InstallRoot" in code


# --- Ownership marker: claim a NEW install directory first, never touch a pre-existing unowned one ----


def _function_block(script: str, name: str) -> str:
    start = script.index(f"function {name} {{")
    depth = 0
    for position in range(script.index("{", start), len(script)):
        depth += {"{": 1, "}": -1}.get(script[position], 0)
        if depth == 0:
            return script[start : position + 1]
    raise AssertionError(f"unbalanced function {name}")


def test_new_install_directory_is_marked_before_the_first_fallible_step() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    init = _function_block(code, "Initialize-OwnedInstallDir")
    main = code.replace(init, "")  # the call site, not the definition

    # Ordering in the run: claim the directory, then clone, then create the venv, then any pip install.
    claim = main.index("\nInitialize-OwnedInstallDir\n")
    assert claim < main.index('"clone"') < main.index('"-m", "venv"') < main.index('"-m", "pip", "install"')
    # Inside the claim: refuse an unmarked existing dir BEFORE any deletion; create the dir without
    # -Force (an existing directory is never adopted); write the marker immediately after creating it.
    assert init.index("was not created by this tooling") < init.index("Remove-Item")
    assert "-Force -Path" not in init and "New-Item -ItemType Directory -Path $InstallDir" in init
    assert init.index("New-Item") < init.index('Write-InstallMarker -Status "installing"')
    # Every other place that could fail comes after the marker; nothing else creates the directory.
    assert "New-Item" not in main
    assert main.index('Write-InstallMarker -Status "verified"') > main.index("Invoke-Verifier")


def test_destructive_removal_is_confined_to_the_claim_function_and_gated_by_the_marker() -> None:
    code = _strip_comments(BOOTSTRAP.read_text(encoding="utf-8"))
    init = _function_block(code, "Initialize-OwnedInstallDir")

    assert code.count("Remove-Item") == init.count("Remove-Item") == 2  # the -Recreate rebuild + marker-failure cleanup
    marker_gate = init.index("was not created by this tooling")
    assert marker_gate < init.index("Remove-Item -LiteralPath $InstallDir -Recurse -Force\n")
    assert code.index("Assert-OwnedInstallDir\n\nif ($CheckOnly)") < code.index("\nInitialize-OwnedInstallDir\n")
    assert "Set-Content" in _function_block(code, "Write-InstallMarker") and code.count("Set-Content") == 1


POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
MARKER = ".stablenew-managed-comfy.json"


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
            f"$InstallDir = '{tmp_path / 'ManagedComfy' / 'v0.38.0-py313'}'",
            f"$MarkerName = '{MARKER}'",
            f"$Recreate = {'$true' if recreate else '$false'}",
            "$VenvPython = Join-Path $InstallDir 'venv/Scripts/python.exe'",
            "$Release = 'v0.38.0'; $Revision = ('a' * 40); $pythonMinor = '3.13'; $ConstraintsPath = 'c/constraints.txt'",
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


def _install_dir(tmp_path: Path) -> Path:
    return tmp_path / "ManagedComfy" / "v0.38.0-py313"


def _says(stderr: str, phrase: str) -> bool:
    """PowerShell wraps long error lines at an arbitrary column; compare without whitespace."""

    return re.sub(r"\s+", "", phrase) in re.sub(r"\s+", "", stderr)


needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not available")


@needs_powershell
@pytest.mark.parametrize("recreate", [False, True])
def test_a_new_install_directory_is_created_and_marked_immediately(tmp_path: Path, recreate: bool) -> None:
    (tmp_path / "ManagedComfy").mkdir()

    done = _run_claim(tmp_path, recreate=recreate)

    assert done.returncode == 0, done.stderr
    marker = json.loads((_install_dir(tmp_path) / MARKER).read_text(encoding="utf-8-sig"))
    assert marker["status"] == "installing" and marker["release"] == "v0.38.0"
    assert marker["created_by"] == "bootstrap_managed_comfy_windows.ps1"


@needs_powershell
@pytest.mark.parametrize("recreate", [False, True])
@pytest.mark.parametrize("with_venv", [False, True])
def test_a_preexisting_unmarked_directory_is_never_modified_adopted_or_deleted(
    tmp_path: Path, recreate: bool, with_venv: bool
) -> None:
    install = _install_dir(tmp_path)
    install.mkdir(parents=True)
    (install / "keep.txt").write_text("someone else's file", encoding="utf-8")
    if with_venv:  # even a directory that looks like a finished install is not ours without the marker
        (install / "venv" / "Scripts").mkdir(parents=True)
        (install / "venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")

    done = _run_claim(tmp_path, recreate=recreate)

    assert done.returncode != 0 and _says(done.stderr, "was not created by this tooling")
    assert (install / "keep.txt").read_text(encoding="utf-8") == "someone else's file"
    assert not (install / MARKER).exists()  # not claimed either
    assert sorted(p.name for p in install.iterdir()) == sorted(["keep.txt", "venv"] if with_venv else ["keep.txt"])


@needs_powershell
def test_a_failed_partial_owned_install_is_reported_incomplete_and_rebuilt_by_recreate(tmp_path: Path) -> None:
    assert _run_claim(tmp_path, recreate=False).returncode == 0  # claimed: marker exists before any install
    install = _install_dir(tmp_path)
    (install / "source").mkdir()
    (install / "source" / "half-cloned.txt").write_text("partial", encoding="utf-8")  # then clone/pip failed

    plain = _run_claim(tmp_path, recreate=False)
    assert plain.returncode != 0 and _says(plain.stderr, "incomplete StableNew-managed install")
    assert (install / "source" / "half-cloned.txt").exists()  # a plain run changes nothing

    rebuilt = _run_claim(tmp_path, recreate=True)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert sorted(p.name for p in install.iterdir()) == [MARKER]  # removed the remnant, freshly claimed
    assert json.loads((install / MARKER).read_text(encoding="utf-8-sig"))["status"] == "installing"


@needs_powershell
def test_a_complete_owned_install_is_reused_untouched_without_recreate(tmp_path: Path) -> None:
    assert _run_claim(tmp_path, recreate=False).returncode == 0
    install = _install_dir(tmp_path)
    (install / "venv" / "Scripts").mkdir(parents=True)
    (install / "venv" / "Scripts" / "python.exe").write_text("x", encoding="utf-8")

    done = _run_claim(tmp_path, recreate=False)

    assert done.returncode == 0, done.stderr
    assert (install / "venv" / "Scripts" / "python.exe").exists()


@needs_powershell
def test_a_marker_write_failure_leaves_no_markerless_directory_behind(tmp_path: Path) -> None:
    (tmp_path / "ManagedComfy").mkdir()

    done = _run_claim(tmp_path, recreate=False, fail_marker=True)

    assert done.returncode != 0 and _says(done.stderr, "simulated marker write failure")
    assert not _install_dir(tmp_path).exists()  # the empty directory this run created is removed
    assert _run_claim(tmp_path, recreate=False).returncode == 0  # and a later run starts cleanly


def test_bootstrap_rejects_other_pythons_free_threaded_builds_and_a_reused_wrong_venv() -> None:
    code = BOOTSTRAP.read_text(encoding="utf-8")

    assert "is required for the managed ComfyUI runtime" in code
    assert "free-threaded" in code and "PYTHON_JIT" in code
    assert code.index("Assert-SupportedPython -Executable $VenvPython") < code.index('"-m", "pip", "install"')


# --- The documented launch procedure matches how StableNew actually reads its configuration ---------

RUNBOOK = ROOT / "docs" / "runbooks" / "managed_comfy_runtime.md"


def test_runbook_documents_the_settings_comfy_command_array_as_the_managed_launch_path() -> None:
    launch = RUNBOOK.read_text(encoding="utf-8").split("## Launch", 1)[1].split("## Rollback", 1)[0]
    flat = re.sub(r"\s+", " ", launch)

    for required in ("presets/settings.json", "`comfy_command`", "`comfy_workdir`", "`comfy_base_url`", "--port", "JSON array"):
        assert required in flat, required
    # The two flags the contract requires are named, and the verifier really emits both.
    for flag in ("--disable-pinned-memory", "--disable-auto-launch"):
        assert flag in flat and flag in _manifest()["launch_policy"]["required_flags"]
    # The verifier's output is a JSON array of separate elements: that is what the settings array holds.
    command = json.loads(
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "runtime" / "verify_managed_comfy.py"), "--install-dir", "X", "--runtime-dir", "R", "--port", "8000", "--print-command"],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    assert isinstance(command, list) and all(isinstance(element, str) for element in command)


def test_runbook_does_not_recommend_the_whitespace_split_command_environment_override() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)

    # Every mention is in the "not recommended / leave unset" paragraph, never an instruction to use it.
    assert "STABLENEW_COMFY_COMMAND" in flat
    for paragraph in re.split(r"\n\s*\n", text):
        if "STABLENEW_COMFY_COMMAND" in paragraph:
            squashed = re.sub(r"\s+", " ", paragraph)
            assert "not** the recommended path" in squashed and "split it on whitespace" in squashed
            assert "leave it unset" in squashed
            assert "do not paste the verifier's output into it" in squashed
    # The source claims the runbook makes are true: both readers really use a plain whitespace split.
    for source in (ROOT / "src" / "main.py", ROOT / "src" / "video" / "comfy_process_manager.py"):
        assert 'os.getenv("STABLENEW_COMFY_COMMAND", "").split()' in source.read_text(encoding="utf-8").replace(
            "os.environ.get(", "os.getenv("
        )
    for other in ("STABLENEW_COMFY_WORKDIR", "STABLENEW_COMFY_BASE_URL"):
        assert other not in text  # one supported configuration path, not a mix of authorities


# --- Ownership: no process-name kill fallback ------------------------------------------------


def test_comfy_lifecycle_never_kills_by_name_or_adopts_an_unowned_process() -> None:
    source = (ROOT / "src" / "video" / "comfy_process_manager.py").read_text(encoding="utf-8")

    for forbidden in ("taskkill", "process_iter", "pkill", "killall", "psutil", "name ==", ".name()"):
        assert forbidden not in source, forbidden
    assert "refusing to adopt, stop, or replace it" in source
