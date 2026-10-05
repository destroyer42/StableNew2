from __future__ import annotations

from pathlib import PureWindowsPath

from src.prompting import global_prompt_paths
from src.prompting.global_prompt_paths import resolve_global_prompt_dir


def test_explicit_path_wins_over_environment_and_platform(tmp_path):
    explicit = tmp_path / "explicit"

    resolved = resolve_global_prompt_dir(
        explicit,
        environ={"STABLENEW_GLOBAL_PROMPT_DIR": str(tmp_path / "env"), "LOCALAPPDATA": "C:/ignored"},
        system_name="Windows",
    )

    assert resolved == explicit


def test_environment_override_wins_when_no_explicit_path(tmp_path):
    override = tmp_path / "env"

    resolved = resolve_global_prompt_dir(
        environ={"STABLENEW_GLOBAL_PROMPT_DIR": str(override), "LOCALAPPDATA": "C:/ignored"},
        system_name="Windows",
    )

    assert resolved == override


def test_windows_resolves_under_local_app_data(tmp_path):
    local_app_data = tmp_path / "Local"

    resolved = resolve_global_prompt_dir(
        environ={"LOCALAPPDATA": str(local_app_data)}, system_name="Windows"
    )

    assert resolved == local_app_data / "StableNew" / "GlobalPrompts"


def test_windows_fallback_without_local_app_data_is_deterministic(tmp_path):
    resolved = resolve_global_prompt_dir(environ={}, system_name="Windows", home_dir=tmp_path)

    assert resolved == tmp_path / "AppData" / "Local" / "StableNew" / "GlobalPrompts"


def test_non_windows_uses_xdg_data_home_then_local_share(tmp_path):
    xdg = resolve_global_prompt_dir(
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")}, system_name="Linux", home_dir=tmp_path
    )
    fallback = resolve_global_prompt_dir(environ={}, system_name="Linux", home_dir=tmp_path)

    assert xdg == tmp_path / "xdg" / "StableNew" / "GlobalPrompts"
    assert fallback == tmp_path / ".local" / "share" / "StableNew" / "GlobalPrompts"


def test_production_windows_shape_is_documented_path():
    resolved = resolve_global_prompt_dir(
        environ={"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}, system_name="Windows"
    )

    assert PureWindowsPath(resolved).parts[-2:] == ("StableNew", "GlobalPrompts")


def test_resolver_has_no_filesystem_side_effects(tmp_path):
    target = tmp_path / "never-created"

    assert resolve_global_prompt_dir(target) == target
    assert resolve_global_prompt_dir(environ={"LOCALAPPDATA": str(tmp_path / "L")}, system_name="Windows")
    assert not target.exists()
    assert not (tmp_path / "L").exists()
    assert global_prompt_paths.GLOBAL_POSITIVE_FILENAME == "global_positive.txt"
    assert global_prompt_paths.GLOBAL_NEGATIVE_FILENAME == "global_negative.txt"
