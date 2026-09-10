"""PromptPack user-storage authority and composition checks for PR-PACKS-001."""

from __future__ import annotations

from pathlib import Path

from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.gui.prompt_pack_adapter_v2 import PromptPackAdapterV2
from src.promptpacks.paths import resolve_prompt_pack_dir
from src.promptpacks.storage import CURRENT_PROMPTPACK_SCHEMA_VERSION, save_prompt_pack_document
from src.utils.config import ConfigManager
from src.utils.prompt_packs import discover_packs
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


def _native_document() -> dict[str, object]:
    return {
        "schema_version": CURRENT_PROMPTPACK_SCHEMA_VERSION,
        "pack_data": {"slots": [{"index": 0, "text": "hero"}]},
        "preset_data": {},
    }


def test_resolver_precedence_and_platform_locations(tmp_path: Path) -> None:
    injected = tmp_path / "injected"
    assert resolve_prompt_pack_dir(
        injected,
        environ={"STABLENEW_PROMPTPACK_DIR": str(tmp_path / "environment")},
        system_name="Windows",
    ) == injected
    assert resolve_prompt_pack_dir(
        environ={"STABLENEW_PROMPTPACK_DIR": str(tmp_path / "environment")},
        system_name="Windows",
    ) == tmp_path / "environment"
    assert resolve_prompt_pack_dir(
        environ={"LOCALAPPDATA": str(tmp_path / "local")},
        system_name="Windows",
    ) == tmp_path / "local" / "StableNew" / "PromptPacks"
    assert resolve_prompt_pack_dir(
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        system_name="Linux",
    ) == tmp_path / "xdg" / "StableNew" / "PromptPacks"
    assert resolve_prompt_pack_dir(
        environ={}, system_name="Linux", home_dir=tmp_path / "home"
    ) == tmp_path / "home" / ".local" / "share" / "StableNew" / "PromptPacks"


def test_config_manager_uses_override_or_exact_injected_path(
    tmp_path: Path, monkeypatch
) -> None:
    environment_dir = tmp_path / "environment"
    monkeypatch.setenv("STABLENEW_PROMPTPACK_DIR", str(environment_dir))
    defaulted = ConfigManager(presets_dir=tmp_path / "default-presets")
    injected = ConfigManager(
        presets_dir=tmp_path / "injected-presets", packs_dir=tmp_path / "injected"
    )

    assert defaulted.packs_dir == environment_dir
    assert injected.packs_dir == tmp_path / "injected"
    assert injected._pack_config_path("sample.txt") == tmp_path / "injected" / "sample.json"


def test_discovery_skips_migration_metadata_and_invalid_json(tmp_path: Path) -> None:
    save_prompt_pack_document(tmp_path / "native.json", _native_document())
    (tmp_path / ".migration_manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".reconciliation_report.json").write_text("{", encoding="utf-8")
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")

    assert [info.name for info in discover_packs(tmp_path)] == ["native"]


def test_production_consumers_share_the_injected_config_directory(tmp_path: Path) -> None:
    packs_dir = tmp_path / "user-packs"
    config = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir)
    app_controller = AppController(
        None,
        threaded=False,
        config_manager=config,
        job_service=make_stubbed_job_service(),
    )
    pipeline_controller = PipelineController(config_manager=config)
    builder = pipeline_controller._get_prompt_pack_builder()
    adapter = PromptPackAdapterV2(config.packs_dir)

    assert app_controller._packs_dir == packs_dir
    assert builder is not None
    assert builder._packs_dir == packs_dir
    assert adapter.packs_dir == packs_dir


def test_save_path_and_production_sources_never_target_repo_packs(tmp_path: Path) -> None:
    packs_dir = tmp_path / "user-packs"
    config = ConfigManager(presets_dir=tmp_path / "presets", packs_dir=packs_dir)
    target = config._pack_config_path("saved-pack")
    save_prompt_pack_document(target, _native_document())

    assert target == packs_dir / "saved-pack.json"
    assert target.exists()

    source_files = (
        Path("src/utils/config.py"),
        Path("src/utils/prompt_packs.py"),
        Path("src/controller/app_controller.py"),
        Path("src/controller/pipeline_controller.py"),
        Path("src/pipeline/prompt_pack_job_builder.py"),
        Path("src/gui/prompt_pack_adapter_v2.py"),
        Path("src/gui/views/prompt_tab_frame_v2.py"),
    )
    for source_file in source_files:
        source = source_file.read_text(encoding="utf-8")
        assert 'Path("packs")' not in source
        assert '"packs_dir", "packs"' not in source
