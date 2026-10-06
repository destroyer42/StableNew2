"""PR-DEVEX-LAUNCH-180: one-command supported Windows launch.

Hermetic: no real runtime is installed. The launcher runs inside a disposable fixture checkout (its path
contains spaces and parentheses) whose bootstrap is a recording stub, whose ``src.main`` is a recorder, and
whose venv is a pip-less copy of a template venv. Decoy ``python``/``py`` shims at the front of PATH prove the
launcher never reaches for a bare interpreter. The PowerShell behavior tests are Windows-only; the interpreter
policy, the static contract and the bootstrap-preservation tests run everywhere.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.runtime import check_launch_environment as checker

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
windows_only = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell launcher behavior")

CANONICAL_LAUNCHERS = (
    SCRIPTS / "launch_stablenew.ps1",
    SCRIPTS / "launch_stablenew.bat",
    SCRIPTS / "launch_stablenew_advanced.bat",
    SCRIPTS / "create_desktop_shortcut.ps1",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_lines(path: Path) -> list[str]:
    """Executable lines: no comment-based help block, ``#`` comments or batch ``REM`` lines."""

    text = re.sub(r"<#.*?#>", "", _read(path), flags=re.DOTALL)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#") and not line.strip().upper().startswith("REM ")
    ]


# --- Interpreter policy (pure) ------------------------------------------------------------------


def test_supported_interpreter_is_standard_gil_314_with_jit_off() -> None:
    assert checker.interpreter_problems((3, 14, 8), free_threaded=False, jit_enabled=False) == []
    assert any("3.14 is required" in p for p in checker.interpreter_problems((3, 12, 1), free_threaded=False, jit_enabled=False))
    assert any("3.14 is required" in p for p in checker.interpreter_problems((3, 15, 0), free_threaded=False, jit_enabled=False))
    assert any("free-threaded" in p for p in checker.interpreter_problems((3, 14, 8), free_threaded=True, jit_enabled=False))
    assert any("JIT" in p for p in checker.interpreter_problems((3, 14, 8), free_threaded=False, jit_enabled=True))


def test_check_rejects_an_unsupported_interpreter_before_any_package_check(monkeypatch, capsys, tmp_path) -> None:
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("# no pins\n", encoding="utf-8")
    monkeypatch.setattr(checker, "current_interpreter_problems", lambda: ["Python 3.14 is required; this environment is Python 3.12.1."])

    assert checker.main(["--constraints", str(constraints)]) == checker.EXIT_UNSUPPORTED_INTERPRETER
    err = capsys.readouterr().err
    assert "UNSUPPORTED INTERPRETER" in err and "3.12.1" in err and "bootstrap_windows.ps1" in err


def test_check_delegates_exact_pins_to_the_single_authority(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(checker, "current_interpreter_problems", lambda: [])
    ok = tmp_path / "ok.txt"
    ok.write_text("# no pins\n", encoding="utf-8")
    drift = tmp_path / "drift.txt"
    drift.write_text("stablenew-surely-not-installed==1.0\n", encoding="utf-8")

    assert checker.main(["--constraints", str(ok)]) == 0
    assert checker.main(["--constraints", str(drift)]) == 1
    assert "stablenew-surely-not-installed: missing" in capsys.readouterr().err


# --- Static contract ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", CANONICAL_LAUNCHERS, ids=lambda p: p.name)
def test_launchers_hard_code_no_user_drive_or_checkout_name(path: Path) -> None:
    text = _read(path)

    assert not re.search(r"[A-Za-z]:\\", text), "no drive-rooted path"
    for forbidden in ("rober", "\\Users\\", "StableNew-main", "%USERNAME%", "%USERPROFILE%"):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize("path", CANONICAL_LAUNCHERS, ids=lambda p: p.name)
def test_launchers_never_invoke_a_bare_python_or_py(path: Path) -> None:
    for line in _code_lines(path):
        assert not re.search(r"(^|[&|;(]\s*|\s)(python3?(\.exe)?|py(\.exe)?)\s+(-|\S+\.py)", line), line
        assert not re.search(r"^\s*(&\s*)?(python3?(\.exe)?|py(\.exe)?)\b", line, re.IGNORECASE), line


def test_the_application_is_started_only_through_the_repository_venv_interpreter() -> None:
    code = "\n".join(_code_lines(SCRIPTS / "launch_stablenew.ps1"))

    assert '$VenvPython = Join-Path $VenvPath "Scripts\\python.exe"' in code
    assert '$VenvPath = Join-Path $RepoRoot ".venv"' in code
    assert "& $VenvPython -m src.main @args" in code
    assert "$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot \"..\")).Path" in code
    # No ambient interpreter discovery lives in the launcher; that is bootstrap's job.
    mentions = [line for line in code.splitlines() if "python.exe" in line]
    assert len(mentions) == 2 and mentions[0].startswith("$VenvPython = ")  # the venv path, and one message
    assert r"no Scripts\python.exe" in mentions[1]
    for ambient in ("Get-Command", "py.exe", "Get-Process -Name"):
        assert ambient not in code


def test_old_launchers_only_forward_to_the_canonical_launcher() -> None:
    simple = _code_lines(SCRIPTS / "launch_stablenew.bat")
    advanced = _code_lines(SCRIPTS / "launch_stablenew_advanced.bat")

    assert any('-File "%~dp0launch_stablenew.ps1" %*' in line for line in simple)
    assert advanced == ["@echo off", 'call "%~dp0launch_stablenew.bat" %*', "exit /b %ERRORLEVEL%"]
    assert not (SCRIPTS / "create_shortcuts.ps1").exists()
    assert "launch_stablenew.bat" in _read(SCRIPTS / "create_desktop_shortcut.ps1")


def test_launcher_neither_owns_a_package_list_nor_any_runtime_lifecycle() -> None:
    text = _read(SCRIPTS / "launch_stablenew.ps1")

    assert "==" not in text  # no exact pins; constraints + verifier stay the only authority
    assert "pip" not in "\n".join(_code_lines(SCRIPTS / "launch_stablenew.ps1")).lower().replace("check_launch", "")
    for runtime in ("a1111", "forge", "comfy", "webui", "Start-Process", "Stop-Process", "taskkill"):
        assert runtime.lower() not in "\n".join(_code_lines(SCRIPTS / "launch_stablenew.ps1")).lower(), runtime


# --- Bootstrap: core readiness is separate; the native-SVD verification is not weakened ---------


def test_skip_svd_readiness_only_gates_the_svd_verification_block() -> None:
    script = _read(SCRIPTS / "bootstrap_windows.ps1")
    gate = script.index("if ($SkipSvdReadiness) {")
    install_lines = [line for line in script.splitlines() if '"-m", "pip", "install"' in line]

    assert "[switch]$SkipSvdReadiness" in script
    assert script.count("$SkipSvdReadiness") == 2  # the declaration and the one gate
    assert not any("$SkipSvdReadiness" in line for line in install_lines)  # never installs fewer packages
    # identical interpreter, install, pip check and exact-pin checks happen before the gate in both modes
    assert script.index("Assert-RuntimePins\n") < gate < script.index("$verificationCode = @'")
    gate_block = script[gate : script.index("$verificationCode = @'")]
    assert "exit 0" in gate_block and "native-SVD readiness skipped" in gate_block


def test_default_bootstrap_still_performs_the_full_native_svd_verification() -> None:
    script = _read(SCRIPTS / "bootstrap_windows.ps1")
    svd_block = script[script.index("$verificationCode = @'") :]

    for requirement in (
        "torch.cuda.is_available()",
        "resolve_ffmpeg_executable()",
        "is_svd_model_cached",
        "Model acquisition required",
        "StableVideoDiffusionPipeline",
        "Windows native-SVD bootstrap verification passed.",
    ):
        assert requirement in svd_block, requirement
    assert "SkipSvdReadiness" not in svd_block


# --- Launcher behavior in a disposable fixture checkout (Windows) --------------------------------


@dataclass
class Checkout:
    root: Path
    work: Path
    record: Path
    bootstrap_log: Path
    decoy_marker: Path
    env: dict[str, str]

    @property
    def venv_python(self) -> Path:
        return self.root / ".venv" / "Scripts" / "python.exe"


@pytest.fixture(scope="module")
def template_venv(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("launch180-template") / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(path)], check=True, capture_output=True)
    return path


_STUB_MAIN = '''\
import json, os, sys
from pathlib import Path

Path(os.environ["STUB_RECORD"]).write_text(
    json.dumps({"executable": sys.executable, "argv": sys.argv[1:], "cwd": os.getcwd()}), encoding="utf-8"
)
raise SystemExit(int(os.environ.get("STUB_EXIT", "0")))
'''

_STUB_BOOTSTRAP = '''\
param([switch]$SkipSvdReadiness, [switch]$Recreate, [switch]$CheckOnly)
Add-Content -LiteralPath $env:STUB_BOOTSTRAP_LOG -Value "SkipSvdReadiness=$SkipSvdReadiness Recreate=$Recreate CheckOnly=$CheckOnly"
if ($env:STUB_BOOTSTRAP_FAIL) { Write-Host "stub bootstrap: simulated failure"; exit 5 }
Copy-Item -LiteralPath $env:STUB_TEMPLATE_VENV -Destination (Join-Path $PSScriptRoot "..\\.venv") -Recurse
Write-Host "stub bootstrap: created venv"
'''


def _make_checkout(
    tmp_path: Path,
    template_venv: Path,
    *,
    venv: bool = True,
    constraints: str = "# no pins\n",
    supported_minor: str | None = None,
) -> Checkout:
    root = tmp_path / "repo with spaces (x86)"
    (root / "scripts").mkdir(parents=True)
    (root / "tools" / "runtime").mkdir(parents=True)
    (root / "constraints").mkdir()
    (root / "src").mkdir()
    for name in ("launch_stablenew.ps1", "launch_stablenew.bat", "launch_stablenew_advanced.bat"):
        shutil.copy2(SCRIPTS / name, root / "scripts" / name)
    (root / "scripts" / "bootstrap_windows.ps1").write_text(_STUB_BOOTSTRAP, encoding="ascii")
    for name in ("check_launch_environment.py", "verify_runtime_pins.py"):
        text = (ROOT / "tools" / "runtime" / name).read_text(encoding="utf-8")
        if supported_minor is not None and name == "check_launch_environment.py":
            text = text.replace("SUPPORTED_PYTHON_MINOR = (3, 14)", f"SUPPORTED_PYTHON_MINOR = {supported_minor}")
        (root / "tools" / "runtime" / name).write_text(text, encoding="utf-8")
    (root / "constraints" / "windows-py314-cu130.txt").write_text(constraints, encoding="utf-8")
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "main.py").write_text(_STUB_MAIN, encoding="utf-8")
    if venv:
        shutil.copytree(template_venv, root / ".venv")

    work = tmp_path / "elsewhere"
    work.mkdir()
    decoys = tmp_path / "decoys"
    decoys.mkdir()
    decoy_marker = tmp_path / "decoy-was-invoked"
    for shim in ("python.cmd", "python3.cmd", "py.cmd"):
        (decoys / shim).write_text('@echo off\r\necho decoy>"%STUB_DECOY%"\r\nexit /b 99\r\n', encoding="ascii")
    record = tmp_path / "app-record.json"
    bootstrap_log = tmp_path / "bootstrap.log"
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHON_JIT", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}}
    env.update(
        PATH=f"{decoys}{os.pathsep}{env.get('PATH', '')}",
        STUB_DECOY=str(decoy_marker),
        STUB_RECORD=str(record),
        STUB_BOOTSTRAP_LOG=str(bootstrap_log),
        STUB_TEMPLATE_VENV=str(template_venv),
    )
    return Checkout(root, work, record, bootstrap_log, decoy_marker, env)


def _run(checkout: Checkout, *args: str, via: str = "ps1", script: str = "launch_stablenew") -> subprocess.CompletedProcess:
    scripts = checkout.root / "scripts"
    if via == "ps1":
        command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / f"{script}.ps1"), *args]
    else:
        quoted = " ".join(f'"{part}"' for part in (str(scripts / f"{script}.bat"), *args))
        command = f'cmd.exe /d /s /c "{quoted}"'
    return subprocess.run(
        command,
        cwd=checkout.work,
        env=checkout.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _app_record(checkout: Checkout) -> dict:
    return json.loads(checkout.record.read_text(encoding="utf-8"))


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _bootstrap_calls(checkout: Checkout) -> list[str]:
    return checkout.bootstrap_log.read_text(encoding="ascii").splitlines() if checkout.bootstrap_log.exists() else []


@windows_only
def test_healthy_venv_launches_src_main_with_the_venv_python_and_never_bootstraps(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv)

    result = _run(checkout, "--flag", "value with space")

    assert result.returncode == 0, result.stdout + result.stderr
    record = _app_record(checkout)
    assert _same_path(record["executable"], checkout.venv_python)
    assert _same_path(record["cwd"], checkout.root)  # resolved from the launcher, not the caller's cwd
    assert record["argv"] == ["--flag", "value with space"]
    assert _bootstrap_calls(checkout) == []
    assert not checkout.decoy_marker.exists()


@windows_only
def test_application_exit_code_is_forwarded(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv)
    checkout.env["STUB_EXIT"] = "7"

    assert _run(checkout).returncode == 7
    assert _app_record(checkout)["executable"]


@windows_only
def test_missing_venv_bootstraps_exactly_once_then_launches_the_venv_python(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv, venv=False)

    result = _run(checkout, "--first-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _bootstrap_calls(checkout) == ["SkipSvdReadiness=True Recreate=False CheckOnly=False"]
    record = _app_record(checkout)
    assert _same_path(record["executable"], checkout.venv_python)
    assert record["argv"] == ["--first-run"]
    assert not checkout.decoy_marker.exists()


@windows_only
def test_bootstrap_failure_does_not_launch_the_application(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv, venv=False)
    checkout.env["STUB_BOOTSTRAP_FAIL"] = "1"

    result = _run(checkout)

    assert result.returncode == 10
    output = result.stdout + result.stderr
    assert "StableNew was not started." in output and "simulated failure" in output
    assert len(_bootstrap_calls(checkout)) == 1
    assert not checkout.record.exists() and not checkout.venv_python.exists()
    assert not checkout.decoy_marker.exists()


@windows_only
def test_incomplete_venv_fails_actionably_and_is_left_untouched(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv, venv=False)
    leftover = checkout.root / ".venv" / "user-data.txt"
    leftover.parent.mkdir()
    leftover.write_text("keep", encoding="utf-8")

    result = _run(checkout)

    assert result.returncode == 11
    output = result.stdout + result.stderr
    assert "incomplete" in output and "-Recreate" in output
    assert leftover.read_text(encoding="utf-8") == "keep"
    assert _bootstrap_calls(checkout) == []
    assert not checkout.record.exists() and not checkout.decoy_marker.exists()


@windows_only
def test_drifted_venv_fails_actionably_without_repair_or_bare_python(tmp_path, template_venv) -> None:
    checkout = _make_checkout(
        tmp_path, template_venv, constraints="stablenew-surely-not-installed==1.0\n"
    )

    result = _run(checkout)

    assert result.returncode == 11
    output = result.stdout + result.stderr
    assert "not a supported StableNew environment" in output
    assert "stablenew-surely-not-installed: missing" in output
    assert "-CheckOnly -SkipSvdReadiness" in output and "-Recreate" in output
    assert checkout.venv_python.exists()  # never deleted or recreated
    assert _bootstrap_calls(checkout) == []  # never silently repaired
    assert not checkout.record.exists() and not checkout.decoy_marker.exists()


@windows_only
def test_unsupported_interpreter_in_an_existing_venv_fails_without_fallback(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv, supported_minor="(3, 99)")

    result = _run(checkout)

    assert result.returncode == 11
    output = result.stdout + result.stderr
    assert "UNSUPPORTED INTERPRETER" in output and "Python 3.99 is required" in output
    assert _bootstrap_calls(checkout) == []
    assert not checkout.record.exists() and not checkout.decoy_marker.exists()


@windows_only
def test_not_a_checkout_is_reported_before_anything_runs(tmp_path, template_venv) -> None:
    checkout = _make_checkout(tmp_path, template_venv)
    (checkout.root / "src" / "main.py").unlink()

    result = _run(checkout)

    assert result.returncode == 12
    assert "not a StableNew checkout" in result.stdout + result.stderr
    assert _bootstrap_calls(checkout) == [] and not checkout.record.exists()


@windows_only
@pytest.mark.parametrize("script", ["launch_stablenew", "launch_stablenew_advanced"])
def test_batch_launchers_reach_the_same_canonical_path(tmp_path, template_venv, script) -> None:
    checkout = _make_checkout(tmp_path, template_venv)
    checkout.env["STUB_EXIT"] = "4"

    result = _run(checkout, "--from-bat", "two words", via="bat", script=script)

    assert result.returncode == 4, result.stdout + result.stderr
    record = _app_record(checkout)
    assert _same_path(record["executable"], checkout.venv_python)
    assert record["argv"] == ["--from-bat", "two words"]
    assert not checkout.decoy_marker.exists()


@windows_only
def test_batch_launcher_failure_is_not_swallowed_and_does_not_start_the_app(tmp_path, template_venv) -> None:
    checkout = _make_checkout(
        tmp_path, template_venv, constraints="stablenew-surely-not-installed==1.0\n"
    )

    result = _run(checkout, via="bat", script="launch_stablenew_advanced")

    assert result.returncode == 11
    assert "StableNew was not started." in result.stdout + result.stderr
    assert not checkout.record.exists() and not checkout.decoy_marker.exists()
