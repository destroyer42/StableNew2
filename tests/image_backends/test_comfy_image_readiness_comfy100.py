"""PR-IMG-COMFY-100: offline installation, live object_info probe and resource floors (no Comfy, model or GPU)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.image_backends import comfy_image_readiness as readiness
from src.image_backends.comfy_image_graphs import QWEN_IMAGE_21_T2I, QWEN_IMAGE_21_TURBO_T2I
from src.image_backends.comfy_image_readiness import (
    ComfyImageResourceError,
    cached_sha256,
    check_installation,
    clear_hash_cache,
    evaluate_floors,
    probe_object_info,
)
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_PROFILE_V1 as BASE
from src.image_backends.comfy_qwen_image_profile import QWEN_IMAGE_21_TURBO_PROFILE_V1 as TURBO
from tests.helpers.comfy_image_fakes import GIB, install, object_info, small_profile, system_stats


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_hash_cache()
    yield
    clear_hash_cache()


def test_installed_files_pass_by_size_and_by_sha256(tmp_path: Path) -> None:
    base = small_profile(BASE)
    folders = install(tmp_path, [base])
    status = check_installation(base, folders=folders)
    assert status.ready and not status.sha256_verified and status.summary == "installed"
    assert set(status.paths) == {asset.filename for asset in base.assets}
    verified = check_installation(base, folders=folders, verify_sha256=True)
    assert verified.ready and verified.sha256_verified


def test_missing_truncated_and_corrupt_files_are_reported_without_downloading(
    tmp_path: Path,
) -> None:
    base, turbo = small_profile(BASE), small_profile(TURBO)
    folders = install(tmp_path, [base])
    missing = check_installation(turbo, folders=folders)
    assert not missing.ready
    assert missing.problems == (f"Model missing: {TURBO.model_name} (Comfy models/diffusion_models; StableNew never "
                                "downloads it)",)  # fmt: skip
    truncated = check_installation(
        base, folders=install(tmp_path / "t", [base], truncate=BASE.vae.filename)
    )
    assert (
        not truncated.ready
        and "size mismatch" in truncated.summary
        and BASE.vae.filename in truncated.summary
    )
    corrupt_root = tmp_path / "c"
    corrupt = install(corrupt_root, [base], corrupt=BASE.text_encoder.filename)
    assert check_installation(base, folders=corrupt).ready  # size alone cannot see it
    hashed = check_installation(base, folders=corrupt, verify_sha256=True)
    assert not hashed.ready and "SHA-256 mismatch" in hashed.summary


def test_hashing_is_cached_until_size_or_mtime_changes(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    calls: list[Path] = []

    def hasher(p: Path) -> str:
        calls.append(p)
        return "h" * 64

    assert cached_sha256(path, hasher=hasher) == "h" * 64
    cached_sha256(path, hasher=hasher)
    assert len(calls) == 1
    path.write_bytes(b"abcd")
    cached_sha256(path, hasher=hasher)
    assert len(calls) == 2


def test_an_unreadable_launch_configuration_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken():
        raise ValueError("Managed Comfy source directory is unknown")

    monkeypatch.setattr(readiness, "comfy_model_folders", broken)
    status = check_installation(BASE)
    assert not status.ready and "cannot be verified" in status.summary


def test_model_folders_come_from_the_managed_launch_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import src.video.comfy_process_manager as manager_module
    import src.video.workflow_asset_integrity as integrity

    config = SimpleNamespace(command=["python", "main.py"], working_dir=str(tmp_path))
    monkeypatch.setattr(manager_module, "get_global_comfy_process_manager", lambda: None)
    monkeypatch.setattr(manager_module, "build_default_comfy_process_config", lambda: config)
    seen: list[tuple] = []
    monkeypatch.setattr(
        integrity, "model_folders", lambda command, working: seen.append((command, working)) or {}
    )
    assert readiness.comfy_model_folders() == {}
    assert seen == [(("python", "main.py"), str(tmp_path))]
    monkeypatch.setattr(manager_module, "build_default_comfy_process_config", lambda: None)
    with pytest.raises(ValueError, match="no StableNew-managed ComfyUI"):
        readiness.comfy_model_folders()


@pytest.mark.parametrize("graph", [QWEN_IMAGE_21_T2I, QWEN_IMAGE_21_TURBO_T2I])
def test_probe_passes_on_the_pinned_node_set(graph) -> None:
    assert probe_object_info(graph, object_info()) == ()


def test_probe_reports_missing_nodes_files_and_encoder_type() -> None:
    assert (
        "no 'ManualSigmas' node"
        in probe_object_info(QWEN_IMAGE_21_TURBO_T2I, object_info(missing_class="ManualSigmas"))[0]
    )
    assert probe_object_info(QWEN_IMAGE_21_T2I, object_info(missing_class="ManualSigmas")) == ()
    dropped = probe_object_info(QWEN_IMAGE_21_T2I, object_info(drop_file=BASE.vae.filename))
    assert dropped == (f"ComfyUI does not list '{BASE.vae.filename}' for VAELoader.vae_name",)
    assert "CLIPLoader.type" in probe_object_info(QWEN_IMAGE_21_T2I, object_info(clip_types=()))[0]
    assert probe_object_info(QWEN_IMAGE_21_T2I, {}) == ("ComfyUI returned no node information",)


def test_floors_pass_and_record_the_readings() -> None:
    readings = evaluate_floors(BASE, system_stats(vram_free=11 * GIB, ram_free=20 * GIB))
    assert readings["vram_free_bytes"] == 11 * GIB and readings["ram_total_bytes"] == 32 * GIB
    assert "4070 Ti" in readings["device_name"]


@pytest.mark.parametrize(
    ("stats", "fragment"),
    [
        (system_stats(vram_free=6 * GIB), "free GPU memory"),
        (system_stats(ram_free=4 * GIB), "free host RAM"),
        ({"system": {}, "devices": []}, "did not report"),
        (None, "did not report"),
    ],
)
def test_floors_refuse_before_anything_is_queued(stats, fragment: str) -> None:
    with pytest.raises(ComfyImageResourceError, match=fragment):
        evaluate_floors(BASE, stats)
