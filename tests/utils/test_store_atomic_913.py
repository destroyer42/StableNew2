"""STORE-ATOMIC-913: live durable stores publish through ``atomic_io``, so a failure mid-write keeps the previous file.

The failure is injected at the publish (replace) step, after the new content was staged: with a plain truncate-then-write
the target would already be empty or partial; with ``atomic_io`` the previous content survives and no staging file is left.
Deterministic simulation only; real power-loss behaviour is not demonstrated here.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import webui_process_manager
from src.gui.prompt_pack_list_manager import PromptPackListManager
from src.pipeline.executor import Pipeline
from src.pipeline.last_run_store_v2_5 import LastRunConfigV2_5, LastRunStoreV2_5
from src.utils import atomic_io
from src.utils import config as config_module
from src.utils.config import ConfigManager
from src.utils.image_metadata import (
    PORTABLE_REVIEW_KEY,
    build_review_sidecar_path,
    write_review_sidecar,
)
from src.utils.logger import StructuredLogger
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.svd_config import SVDConfig
from src.video.svd_registry import write_svd_run_manifest
from tests.video.test_svd_registry import _FakeResult

PREVIOUS = "previous-content"


def _fail_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(source: str, target: Path) -> None:
        raise OSError("simulated failure at the publish step")

    monkeypatch.setattr(atomic_io, "_replace_with_retry", _boom)


def _assert_untouched(target: Path) -> None:
    assert target.read_text(encoding="utf-8") == PREVIOUS
    assert [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")] == []


def _seed(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PREVIOUS, encoding="utf-8")
    return target


def _config_manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(
        tmp_path / "presets", packs_dir=tmp_path / "packs", global_prompt_dir=tmp_path / "prompts"
    )


def test_global_negative_prompt_survives_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _config_manager(tmp_path)
    target = _seed(tmp_path / "prompts" / manager._global_negative_path.name)
    _fail_replace(monkeypatch)
    assert manager.save_global_negative_prompt("replacement") is False
    _assert_untouched(target)


def test_global_positive_prompt_survives_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _config_manager(tmp_path)
    target = _seed(tmp_path / "prompts" / manager._global_positive_path.name)
    _fail_replace(monkeypatch)
    assert manager.save_global_positive_prompt("replacement") is False
    _assert_untouched(target)


def test_global_prompts_still_round_trip_and_keep_an_explicit_blank(tmp_path: Path) -> None:
    manager = _config_manager(tmp_path)
    assert manager.save_global_negative_prompt("  no hands  ") is True
    assert manager.save_global_negative_prompt("") is True
    fresh = _config_manager(tmp_path)
    assert fresh.get_global_negative_prompt() == ""
    assert manager.save_global_positive_prompt("masterpiece") is True
    assert _config_manager(tmp_path).get_global_positive_prompt() == "masterpiece"


def test_first_read_default_prompt_is_written_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _config_manager(tmp_path)
    _fail_replace(monkeypatch)
    manager.get_global_negative_prompt()  # the failed default write is logged, never raised
    assert not manager._global_negative_path.exists()


def test_last_run_payload_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "state" / "last_run.json")
    monkeypatch.setattr(config_module, "LAST_RUN_PATH", target)
    manager = _config_manager(tmp_path)
    _fail_replace(monkeypatch)
    manager.write_last_run({"model": "x"})
    _assert_untouched(target)


def test_last_run_payload_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "state" / "last_run.json"
    monkeypatch.setattr(config_module, "LAST_RUN_PATH", target)
    manager = _config_manager(tmp_path)
    manager.write_last_run({"model": "café"})
    assert manager.load_last_run() == {"model": "café"}
    assert "café" in target.read_text(encoding="utf-8")  # ensure_ascii=False is preserved


def test_last_run_store_survives_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "last_run_v2_5.json")
    store = LastRunStoreV2_5(target)
    _fail_replace(monkeypatch)
    store.save(LastRunConfigV2_5(model="m"))
    _assert_untouched(target)


def test_last_run_store_round_trips(tmp_path: Path) -> None:
    store = LastRunStoreV2_5(tmp_path / "last_run_v2_5.json")
    store.save(LastRunConfigV2_5(model="m", steps=31))
    loaded = store.load()
    assert loaded is not None and loaded.model == "m" and loaded.steps == 31


def test_executor_manifest_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "manifests" / "image.json")
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        Pipeline._write_manifest_file(SimpleNamespace(), manifest_path=target, metadata={"a": 1})
    _assert_untouched(target)


def test_executor_manifest_round_trips_unicode(tmp_path: Path) -> None:
    target = tmp_path / "manifests" / "image.json"
    Pipeline._write_manifest_file(
        SimpleNamespace(), manifest_path=target, metadata={"prompt": "café"}
    )
    assert json.loads(target.read_text(encoding="utf-8")) == {"prompt": "café"}
    assert "café" in target.read_text(encoding="utf-8")


def test_logger_manifests_rollup_and_status_survive_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = StructuredLogger(str(tmp_path / "output"))
    run_dir = tmp_path / "run"
    manifest = _seed(run_dir / "manifests" / "img.json")
    pack_manifest = _seed(tmp_path / "pack" / "manifests" / "img.json")
    status = _seed(run_dir / "run_status.json")
    rollup = _seed(run_dir / "rollup_manifest.json")
    other = run_dir / "manifests" / "other.json"
    other.write_text("{}", encoding="utf-8")
    _fail_replace(monkeypatch)
    assert logger.save_manifest(run_dir, "img", {"a": 1}) is False
    assert logger.save_pack_manifest(tmp_path / "pack", "img", {"a": 1}) is False
    assert logger.record_run_status(run_dir, "success") is False
    assert logger.create_rollup_manifest(run_dir) is False
    for target in (manifest, pack_manifest, status, rollup):
        assert target.read_text(encoding="utf-8") == PREVIOUS
    assert [p.name for p in run_dir.rglob("*.tmp")] == []


def test_logger_writers_still_publish_readable_json(tmp_path: Path) -> None:
    logger = StructuredLogger(str(tmp_path / "output"))
    run_dir = tmp_path / "run"
    assert logger.save_manifest(run_dir, "img", {"a": 1}) is True
    assert logger.record_run_status(run_dir, "success", "ok") is True
    assert logger.create_rollup_manifest(run_dir) is True
    assert json.loads((run_dir / "manifests" / "img.json").read_text(encoding="utf-8")) == {"a": 1}
    assert json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))["reason"] == "ok"
    rollup = json.loads((run_dir / "rollup_manifest.json").read_text(encoding="utf-8"))
    assert rollup["run_info"]["total_images"] == 1


def test_review_sidecar_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "image.png"
    sidecar = _seed(build_review_sidecar_path(image))
    _fail_replace(monkeypatch)
    result = write_review_sidecar(image, {"rating": 5})
    assert result.success is False
    _assert_untouched(sidecar)


def test_review_sidecar_round_trips(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    assert write_review_sidecar(image, {"rating": 5}).success is True
    stored = json.loads(build_review_sidecar_path(image).read_text(encoding="utf-8"))
    assert stored[PORTABLE_REVIEW_KEY] == {"rating": 5}


def test_prompt_pack_lists_survive_a_failed_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "lists.json")
    manager = PromptPackListManager(target)
    _fail_replace(monkeypatch)
    assert manager.save_list("mine", ["a"]) is False
    _assert_untouched(target)


def test_prompt_pack_lists_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "lists.json"
    manager = PromptPackListManager(target)
    assert manager.save_list("mine", ["a", "b"]) is True
    assert PromptPackListManager(target).get_list("mine") == ["a", "b"]


def test_svd_manifest_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "manifests" / "svd_stem.json")
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        write_svd_run_manifest(
            run_dir=tmp_path,
            config=SVDConfig(),
            result=_FakeResult(tmp_path),
            artifact_stem="svd_stem",
        )
    _assert_untouched(target)


def test_comfy_video_manifest_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "manifests" / "clip.json")
    request = SimpleNamespace(
        output_dir=str(tmp_path),
        input_image_path=None,
        end_anchor_path=None,
        mid_anchor_paths=[],
        prompt="p",
        negative_prompt="n",
        motion_profile=None,
        stage_name="video",
    )
    resolved = {
        "primary_path": str(tmp_path / "clip.mp4"),
        "output_paths": [str(tmp_path / "clip.mp4")],
        "video_path": str(tmp_path / "clip.mp4"),
        "video_paths": [str(tmp_path / "clip.mp4")],
        "gif_path": None,
        "gif_paths": [],
        "frame_paths": [],
        "thumbnail_path": None,
    }
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        ComfyWorkflowVideoBackend._write_manifest(
            SimpleNamespace(backend_id="comfy"),
            request=request,
            prompt_id="pid",
            spec=SimpleNamespace(workflow_id="w", workflow_version="1"),
            compiled={},
            dependency_probe={},
            queue_response={},
            history_entry={},
            resolved_outputs=resolved,
            conditioning={},
        )
    _assert_untouched(target)


def test_webui_cache_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _seed(tmp_path / "data" / "webui_cache.json")
    monkeypatch.setattr(webui_process_manager, "_WEBUI_CACHE_FILE", target)
    _fail_replace(monkeypatch)
    webui_process_manager._save_webui_cache({"workdir": "w"})  # swallows by contract
    _assert_untouched(target)


def test_webui_cache_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "data" / "webui_cache.json"
    monkeypatch.setattr(webui_process_manager, "_WEBUI_CACHE_FILE", target)
    webui_process_manager._save_webui_cache({"workdir": "w"})
    assert webui_process_manager._load_webui_cache() == {"workdir": "w"}
