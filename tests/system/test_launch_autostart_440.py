"""LAUNCH-AUTOSTART-440: owner-run desktop shortcut and per-user autostart at Windows sign-in.

The behavior tests run the real ``scripts/manage_stablenew_shortcuts.ps1`` against this checkout, with the Desktop
and Startup folders redirected to disposable folders (paths with spaces), so the owner's real folders are never
touched. They are Windows-only; the static contract tests run everywhere.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
MANAGER = SCRIPTS / "manage_stablenew_shortcuts.ps1"
LAUNCHER = SCRIPTS / "launch_stablenew.bat"
POWERSHELL = shutil.which("powershell.exe") if sys.platform == "win32" else None
windows_only = pytest.mark.skipif(POWERSHELL is None, reason="Windows shortcut behavior")


def _code(path: Path) -> str:
    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


# --- Static contract ----------------------------------------------------------------------------


def test_manager_is_per_user_and_changes_nothing_machine_wide() -> None:
    code = _code(MANAGER).lower()

    assert 'getfolderpath("desktop")' in code and 'getfolderpath("startup")' in code
    for machine_wide in (
        "hklm:",
        "hkcu:",
        "registry",
        "set-itemproperty",
        "register-scheduledtask",
        "schtasks",
        "new-service",
        "commonstartup",
        "commondesktop",
        "runas",
        "start-process",
    ):
        assert machine_wide not in code, machine_wide


def test_manager_only_writes_or_deletes_its_own_shortcut_name() -> None:
    code = _code(MANAGER)

    assert '$ShortcutName = "StableNew.lnk"' in code
    assert code.count("Remove-Item") == 1 and "Remove-Item -LiteralPath $state.Path" in code
    assert code.count(".Save()") == 1
    # The removal and the save sit behind the foreign-shortcut guard.
    assert code.index('if ($state.Kind -eq "foreign")') < code.index("Remove-Item")


def test_old_desktop_script_forwards_to_the_manager() -> None:
    code = _code(SCRIPTS / "create_desktop_shortcut.ps1")

    assert code.splitlines() == [
        '& (Join-Path $PSScriptRoot "manage_stablenew_shortcuts.ps1") -Desktop @args',
        "exit $LASTEXITCODE",
    ]


def test_runbook_documents_install_status_and_remove() -> None:
    text = (ROOT / "docs" / "runbooks" / "windows_runtime_bootstrap.md").read_text(encoding="utf-8")

    assert "manage_stablenew_shortcuts.ps1" in text
    for command in ("-Status", "-Remove", "-Autostart -Remove", "-Desktop -Remove"):
        assert command in text, command


# --- Behavior (Windows) -------------------------------------------------------------------------


def _ps(script: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _run(folders: tuple[Path, Path], *switches: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    desktop, startup = folders
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MANAGER),
            *switches,
            "-DesktopDir",
            str(desktop),
            "-StartupDir",
            str(startup),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_link(path: Path) -> dict:
    result = _ps(
        f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({_quote(path)}); "
        "@{ target = $l.TargetPath; workdir = $l.WorkingDirectory; style = $l.WindowStyle; "
        "description = $l.Description } | ConvertTo-Json -Compress"
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _write_link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _ps(
        f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({_quote(path)}); "
        f"$l.TargetPath = {_quote(Path(target))}; $l.Save()"
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    # Startup does not exist yet: the manager must create it, as Windows may not have.
    desktop = tmp_path / "Owner Desktop (test)"
    desktop.mkdir()
    return desktop, tmp_path / "Start Menu" / "Programs" / "Startup"


@windows_only
def test_install_creates_both_shortcuts_to_this_checkouts_launcher(folders) -> None:
    desktop, startup = folders

    result = _run(folders)

    assert result.returncode == 0, result.stdout + result.stderr
    desk = _read_link(desktop / "StableNew.lnk")
    auto = _read_link(startup / "StableNew.lnk")
    for link in (desk, auto):
        assert Path(link["target"]) == LAUNCHER.resolve()
        assert Path(link["workdir"]) == ROOT.resolve()
    assert desk["style"] == 1
    assert auto["style"] == 7  # minimized console at sign-in
    assert "created" in result.stdout


@windows_only
def test_install_is_idempotent(folders) -> None:
    desktop, startup = folders
    assert _run(folders).returncode == 0
    before = {
        p: p.stat().st_mtime_ns for p in (desktop / "StableNew.lnk", startup / "StableNew.lnk")
    }

    again = _run(folders)

    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout.count("already installed") == 2
    assert {p: p.stat().st_mtime_ns for p in before} == before


@windows_only
def test_install_retargets_a_shortcut_from_another_checkout(folders, tmp_path) -> None:
    _desktop, startup = folders
    other = tmp_path / "Old Checkout" / "scripts" / "launch_stablenew.bat"
    _write_link(startup / "StableNew.lnk", str(other))

    result = _run(folders, "-Autostart")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "updated" in result.stdout and str(other) in result.stdout
    assert Path(_read_link(startup / "StableNew.lnk")["target"]) == LAUNCHER.resolve()


@windows_only
def test_a_foreign_shortcut_of_the_same_name_is_never_overwritten_or_removed(folders) -> None:
    desktop, _startup = folders
    foreign = desktop / "StableNew.lnk"
    _write_link(foreign, r"C:\Windows\notepad.exe")
    before = foreign.read_bytes()

    install = _run(folders, "-Desktop")
    remove = _run(folders, "-Desktop", "-Remove")

    assert install.returncode == 2 and "left untouched" in install.stdout
    assert remove.returncode == 2 and "left untouched" in remove.stdout
    assert foreign.read_bytes() == before


@windows_only
def test_remove_is_selective_and_repeatable(folders) -> None:
    desktop, startup = folders
    assert _run(folders).returncode == 0

    first = _run(folders, "-Autostart", "-Remove")
    second = _run(folders, "-Autostart", "-Remove")

    assert first.returncode == 0 and "removed" in first.stdout
    assert second.returncode == 0 and "nothing to remove" in second.stdout
    assert not (startup / "StableNew.lnk").exists()
    assert (desktop / "StableNew.lnk").exists()

    assert _run(folders, "-Remove").returncode == 0
    assert not (desktop / "StableNew.lnk").exists()


@windows_only
def test_status_reports_and_changes_nothing(folders) -> None:
    desktop, startup = folders

    empty = _run(folders, "-Status")
    assert empty.returncode == 0 and empty.stdout.count("not installed") == 2
    assert not (desktop / "StableNew.lnk").exists() and not startup.exists()

    assert _run(folders, "-Desktop").returncode == 0
    mixed = _run(folders, "-Status")
    assert "Desktop shortcut: installed" in mixed.stdout
    assert "Autostart at sign-in: not installed" in mixed.stdout


@windows_only
def test_remove_and_status_together_are_rejected(folders) -> None:
    result = _run(folders, "-Remove", "-Status")

    assert result.returncode == 1
    assert "either -Remove or -Status" in result.stdout
