"""ConfigManager keeps Global Prompt TEXT in per-user state, never in the repository presets."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.utils.config import (
    DEFAULT_GLOBAL_NEGATIVE_PROMPT,
    DEFAULT_GLOBAL_POSITIVE_PROMPT,
    ConfigManager,
)
from tests.helpers.global_prompt_isolation import real_global_prompt_store_untouched  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(
        presets_dir=tmp_path / "presets",
        packs_dir=tmp_path / "packs",
        global_prompt_dir=tmp_path / "global-prompts",
    )


def _preset_prompt_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "presets").glob("global_*.txt"))


def test_first_read_returns_code_defined_defaults_and_persists_them_per_user(tmp_path):
    manager = _manager(tmp_path)

    assert manager.get_global_positive_prompt() == DEFAULT_GLOBAL_POSITIVE_PROMPT
    assert manager.get_global_negative_prompt() == DEFAULT_GLOBAL_NEGATIVE_PROMPT
    store = tmp_path / "global-prompts"
    assert (store / "global_positive.txt").read_text(encoding="utf-8") == DEFAULT_GLOBAL_POSITIVE_PROMPT
    assert (store / "global_negative.txt").read_text(encoding="utf-8") == DEFAULT_GLOBAL_NEGATIVE_PROMPT


def test_positive_and_negative_roundtrip_with_surrounding_whitespace_stripped(tmp_path):
    manager = _manager(tmp_path)

    assert manager.save_global_positive_prompt("  sharp focus \n")
    assert manager.save_global_negative_prompt("\tblur  ")

    assert manager.get_global_positive_prompt() == "sharp focus"
    assert manager.get_global_negative_prompt() == "blur"
    store = tmp_path / "global-prompts"
    assert (store / "global_positive.txt").read_text(encoding="utf-8") == "sharp focus"
    assert (store / "global_negative.txt").read_text(encoding="utf-8") == "blur"


def test_explicitly_blank_negative_survives_and_is_not_replaced_by_the_default(tmp_path):
    manager = _manager(tmp_path)

    assert manager.save_global_negative_prompt("   ")

    assert manager.get_global_negative_prompt() == ""
    assert _manager(tmp_path).get_global_negative_prompt() == ""


def test_fresh_manager_instance_sees_persisted_user_store_values(tmp_path):
    first = _manager(tmp_path)
    assert first.save_global_positive_prompt("positive text")
    assert first.save_global_negative_prompt("negative text")

    second = _manager(tmp_path)

    assert second.get_global_positive_prompt() == "positive text"
    assert second.get_global_negative_prompt() == "negative text"


def test_saves_and_reads_never_touch_repository_style_preset_prompt_files(tmp_path):
    manager = _manager(tmp_path)

    manager.get_global_positive_prompt()
    manager.get_global_negative_prompt()
    manager.save_global_positive_state("p", True)
    manager.save_global_negative_state("n", False)

    assert _preset_prompt_files(tmp_path) == []
    assert manager.global_prompt_dir == tmp_path / "global-prompts"


def test_legacy_preset_files_are_ignored_and_never_seed_or_fall_back(tmp_path):
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "global_positive.txt").write_text("LEGACY-POSITIVE-SENTINEL", encoding="utf-8")
    (presets / "global_negative.txt").write_text("LEGACY-NEGATIVE-SENTINEL", encoding="utf-8")
    store = tmp_path / "global-prompts"
    store.mkdir()
    (store / "global_positive.txt").write_text("user positive", encoding="utf-8")
    (store / "global_negative.txt").write_text("user negative", encoding="utf-8")

    manager = _manager(tmp_path)
    assert manager.get_global_positive_prompt() == "user positive"
    assert manager.get_global_negative_prompt() == "user negative"

    # Remove the user store: the code-defined defaults return, not the legacy sentinels.
    (store / "global_positive.txt").unlink()
    (store / "global_negative.txt").unlink()
    fresh = _manager(tmp_path)
    assert fresh.get_global_positive_prompt() == DEFAULT_GLOBAL_POSITIVE_PROMPT
    assert fresh.get_global_negative_prompt() == DEFAULT_GLOBAL_NEGATIVE_PROMPT
    assert (store / "global_positive.txt").read_text(encoding="utf-8") == DEFAULT_GLOBAL_POSITIVE_PROMPT
    assert (store / "global_negative.txt").read_text(encoding="utf-8") == DEFAULT_GLOBAL_NEGATIVE_PROMPT
    # The legacy files are neither consumed nor rewritten.
    assert (presets / "global_positive.txt").read_text(encoding="utf-8") == "LEGACY-POSITIVE-SENTINEL"
    assert (presets / "global_negative.txt").read_text(encoding="utf-8") == "LEGACY-NEGATIVE-SENTINEL"


def test_state_saves_write_text_to_user_store_and_enablement_to_settings(tmp_path):
    manager = _manager(tmp_path)

    assert manager.get_global_positive_enabled() is False
    assert manager.get_global_negative_enabled() is True
    assert manager.save_global_positive_state("pos", True)
    assert manager.save_global_negative_state("neg", False)

    store = tmp_path / "global-prompts"
    assert (store / "global_positive.txt").read_text(encoding="utf-8") == "pos"
    assert (store / "global_negative.txt").read_text(encoding="utf-8") == "neg"
    settings = json.loads((tmp_path / "presets" / "settings.json").read_text(encoding="utf-8"))
    assert settings["global_positive_enabled"] is True
    assert settings["global_negative_enabled"] is False
    reloaded = _manager(tmp_path)
    assert reloaded.get_global_positive_enabled() is True
    assert reloaded.get_global_negative_enabled() is False


def test_environment_override_redirects_the_default_constructed_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("STABLENEW_GLOBAL_PROMPT_DIR", str(tmp_path / "from-env"))
    manager = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path / "packs")

    assert manager.save_global_positive_prompt("env positive")

    assert (tmp_path / "from-env" / "global_positive.txt").read_text(encoding="utf-8") == "env positive"


def test_constructing_a_manager_does_not_create_the_prompt_store(tmp_path):
    _manager(tmp_path)

    assert not (tmp_path / "global-prompts").exists()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False
    )


@pytest.fixture
def _git_checkout():
    probe = _git("rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        pytest.skip("repository contract needs a git checkout")


def test_repository_no_longer_tracks_global_prompt_text(_git_checkout):
    tracked = set(_git("ls-files", "presets").stdout.splitlines())

    assert "presets/global_positive.txt" not in tracked
    assert "presets/global_negative.txt" not in tracked


def test_exact_ignore_rules_block_re_adding_prompt_text_without_hiding_other_presets(_git_checkout):
    ignored = _git(
        "check-ignore", "presets/global_positive.txt", "presets/global_negative.txt"
    ).stdout.splitlines()
    assert sorted(ignored) == ["presets/global_negative.txt", "presets/global_positive.txt"]

    for still_tracked in ("presets/settings.json", "presets/default.json", "presets/other.txt"):
        assert _git("check-ignore", still_tracked).returncode == 1, still_tracked
