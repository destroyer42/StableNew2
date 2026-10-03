"""Deterministic CPU-only coverage of source publication; no runtime or GUI."""

from __future__ import annotations

import hashlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageOps

from src.video.workflow_source_preparation import prepare_declared_workflow_source

POLICY = {
    "resize_policy": "cover_resize_center_crop",
    "portrait_target": {"width": 24, "height": 40},
    "landscape_target": {"width": 40, "height": 24},
}
TIMEOUT = 10


def _source(tmp_path, name="source.png", offset=0):
    path = tmp_path / name
    image = Image.new("RGB", (60, 80))
    image.putdata([
        ((x * 3 + offset) % 256, y * 3, (x + y) % 256)
        for y in range(80) for x in range(60)
    ])
    image.save(path)
    return path


def _prepare(source, output):
    return prepare_declared_workflow_source(source_path=source, output_root=output, policy=POLICY)


def _expected_path(source, output):
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    return output / "prepared_video_sources" / f"{digest}_24x40_cover_resize_center_crop.png"


def _assert_png(path, source, size=(24, 40)):
    with Image.open(source) as original:
        expected = ImageOps.fit(
            original.convert("RGB"), size,
            method=Image.Resampling.LANCZOS, centering=(0.5, 0.5),
        )
    with Image.open(path) as actual:
        assert actual.format == "PNG"
        actual.load()
        assert actual.size == size
        assert actual.tobytes() == expected.tobytes()


def _synchronize_saves(monkeypatch, callers):
    """Both calls pass the absent-final check and finish saving before either publishes.

    The old shared temporary pathname deterministically loses one replace here.
    """
    barrier = threading.Barrier(callers, timeout=TIMEOUT)
    saved = []
    original_save = Image.Image.save
    original_replace = Path.replace
    publication_lock = threading.Lock()

    def save(image, fp, *args, **kwargs):
        original_save(image, fp, *args, **kwargs)
        saved.append(Path(fp))
        barrier.wait()

    def replace(path, target):
        # Order completed replacements to reproduce loss of the old shared temp
        # even on Windows, where overlapping rename syscalls can both succeed.
        with publication_lock:
            return original_replace(path, target)

    monkeypatch.setattr(Image.Image, "save", save)
    monkeypatch.setattr(Path, "replace", replace)
    return saved


def test_first_preparation_and_repeat_preserve_filename_provenance_and_source(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "output"
    first = _prepare(source, output)
    final = _expected_path(source, output)
    assert first.to_stage_config() == {
        "original_source_path": str(source.resolve()),
        "prepared_image_path": str(final.resolve()),
        "source_dimensions": {"width": 60, "height": 80},
        "target_dimensions": {"width": 24, "height": 40},
        "prepared_dimensions": {"width": 24, "height": 40},
        "orientation": "portrait",
        "policy": "cover_resize_center_crop",
        "orientation_rule": "landscape when source width is greater than height; otherwise portrait",
    }
    _assert_png(final, source)
    final_bytes = final.read_bytes()

    def unexpected_save(*args, **kwargs):
        pytest.fail("An existing prepared file must be reused without saving")

    monkeypatch.setattr(Image.Image, "save", unexpected_save)
    assert _prepare(source, output) == first
    assert final.read_bytes() == final_bytes
    _assert_png(final, source)
    assert source.read_bytes() == original
    assert list(final.parent.iterdir()) == [final]


@pytest.mark.parametrize("callers", [2, 4])
def test_concurrent_first_preparations_publish_identical_complete_png(tmp_path, monkeypatch, callers):
    source = _source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "output"
    saved = _synchronize_saves(monkeypatch, callers)
    with ThreadPoolExecutor(max_workers=callers) as pool:
        futures = [pool.submit(_prepare, source, output) for _ in range(callers)]
        results = [future.result(timeout=TIMEOUT) for future in futures]
    final = _expected_path(source, output)
    assert all(result == results[0] for result in results)
    assert results[0].prepared_image_path == str(final.resolve())
    assert len(set(saved)) == callers
    assert all(path.parent == final.parent and path.suffix == ".png" for path in saved)
    assert final.with_suffix(".tmp.png") not in saved
    _assert_png(final, source)
    assert list(final.parent.iterdir()) == [final]
    assert source.read_bytes() == original


def test_experiment_preview_overlaps_normal_video_workflow_submission(tmp_path, monkeypatch):
    from src.controller.video_workflow_controller import VideoWorkflowController
    from src.video.workflow_catalog_wan_animate2 import (
        WAN_ANIMATE2_CONTROLS_VERSION,
        WAN_ANIMATE2_DRIVE_ID,
    )

    source = _source(tmp_path)
    original = source.read_bytes()
    clip = tmp_path / "driving.mp4"
    clip.write_bytes(b"fake driving clip; no backend is called")
    calls = []

    def submit(njrs, policy):
        calls.append(list(njrs))
        return ["normal-video-job"]

    output = tmp_path / "output"
    controller = VideoWorkflowController(app_controller=SimpleNamespace(
        output_dir=str(output), job_service=SimpleNamespace(submit_njrs=submit),
    ))
    form = {
        "workflow_id": WAN_ANIMATE2_DRIVE_ID,
        "workflow_version": WAN_ANIMATE2_CONTROLS_VERSION,
        "prompt": "A person in a studio",
        "pose_video_path": str(clip),
        "experimental_opt_in": True,
        "seed": "424242",
        "operator_controls": {"pose_strength": "1"},
    }
    normal_form = dict(form)
    saved = _synchronize_saves(monkeypatch, 2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        preview = pool.submit(
            controller.preview_experiment, source_image_path=source, form_data=form,
            variable_name="pose_strength", candidates=["1.5"],
        )
        normal = pool.submit(
            controller.submit_video_workflow_job, source_image_path=source, form_data=normal_form,
        )
        plan = preview.result(timeout=TIMEOUT)
        assert normal.result(timeout=TIMEOUT) == "normal-video-job"
    assert len(calls) == 1
    [normal_njr] = calls[0]
    final = Path(plan.frozen.prepared_source_path)
    assert normal_njr.input_image_paths == (str(final),)
    assert all(arm.njr.input_image_paths == (str(final),) for arm in plan.arms)
    expected_provenance = dict(plan.frozen.source_preparation)
    assert normal_njr.config["video_workflow"]["source_preparation"] == expected_provenance
    assert normal_form["_stable_new_submission_projection"]["source_preparation"] == expected_provenance
    assert plan.frozen.prepared_source_sha256 == hashlib.sha256(final.read_bytes()).hexdigest()
    assert len(set(saved)) == 2
    _assert_png(final, source, (480, 832))
    assert list(final.parent.iterdir()) == [final]
    assert source.read_bytes() == original


def test_concurrent_different_sources_remain_independent(tmp_path, monkeypatch):
    sources = [_source(tmp_path, f"source-{index}.png", index * 50) for index in range(2)]
    originals = [source.read_bytes() for source in sources]
    output = tmp_path / "output"
    saved = _synchronize_saves(monkeypatch, 2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_prepare, source, output) for source in sources]
        results = [future.result(timeout=TIMEOUT) for future in futures]
    assert len(set(saved)) == 2
    assert results[0].prepared_image_path != results[1].prepared_image_path
    for source, original, result in zip(sources, originals, results, strict=True):
        _assert_png(result.prepared_image_path, source)
        assert source.read_bytes() == original
    assert len(list((output / "prepared_video_sources").iterdir())) == 2


@pytest.mark.parametrize("winner_published", [False, True])
def test_publication_failure_cleans_only_own_temp_and_preserves_winner(
    tmp_path, monkeypatch, winner_published,
):
    source = _source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "output"
    # Independent successful preparation supplies the exact valid bytes of a concurrent winner.
    winner = _prepare(source, tmp_path / "winner")
    winner_bytes = Path(winner.prepared_image_path).read_bytes()
    final = _expected_path(source, output)
    attempted = []

    def fail_publication(temp, destination):
        attempted.append(temp)
        _assert_png(temp, source)  # publication never sees an incomplete PNG
        if winner_published:
            Path(destination).write_bytes(winner_bytes)
        raise OSError("injected publication failure")

    monkeypatch.setattr(Path, "replace", fail_publication)
    with pytest.raises(OSError, match="injected publication failure"):
        _prepare(source, output)
    assert len(attempted) == 1
    assert not attempted[0].exists()
    assert source.read_bytes() == original
    if winner_published:
        assert final.read_bytes() == winner_bytes
        _assert_png(final, source)
    else:
        assert not final.exists()
    assert set(final.parent.iterdir()) == ({final} if winner_published else set())


def test_save_failure_cleans_incomplete_temp(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "output"
    attempted = []

    def fail_save(image, fp, *args, **kwargs):
        path = Path(fp)
        attempted.append(path)
        path.write_bytes(b"incomplete PNG")
        raise OSError("injected save failure")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(OSError, match="injected save failure"):
        _prepare(source, output)
    assert len(attempted) == 1
    assert not attempted[0].exists()
    assert list(_expected_path(source, output).parent.iterdir()) == []
    assert source.read_bytes() == original


@pytest.mark.parametrize("destination", ["identical", "different", "missing"])
def test_permission_error_reuses_only_a_byte_identical_published_winner(
    tmp_path, monkeypatch, destination,
):
    source = _source(tmp_path)
    output = tmp_path / "output"
    final = _expected_path(source, output)
    attempted = []
    publication_error = PermissionError("injected replacement denial")

    def deny_replace(temp, target):
        attempted.append(temp)
        if destination == "identical":
            Path(target).write_bytes(temp.read_bytes())
        elif destination == "different":
            Path(target).write_bytes(b"corrupt or unrelated destination")
        raise publication_error

    monkeypatch.setattr(Path, "replace", deny_replace)
    if destination == "identical":
        result = _prepare(source, output)
        assert result.prepared_image_path == str(final.resolve())
        _assert_png(final, source)
    else:
        with pytest.raises(PermissionError) as error:
            _prepare(source, output)
        assert error.value is publication_error
        if destination == "different":
            assert final.read_bytes() == b"corrupt or unrelated destination"
        else:
            assert not final.exists()
    assert len(attempted) == 1
    assert not attempted[0].exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows readers can deny file replacement")
def test_concurrent_winner_can_be_read_while_second_caller_publishes(tmp_path, monkeypatch):
    source = _source(tmp_path)
    output = tmp_path / "output"
    saved = _synchronize_saves(monkeypatch, 2)
    replace = Path.replace
    first_published = threading.Event()
    reader_open = threading.Event()
    order_lock = threading.Lock()
    publication_count = 0

    def publish(path, target):
        nonlocal publication_count
        with order_lock:
            publication_count += 1
            index = publication_count
        if index == 1:
            result = replace(path, target)
            first_published.set()
            return result
        assert reader_open.wait(TIMEOUT)
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_prepare, source, output) for _ in range(2)]
        assert first_published.wait(TIMEOUT)
        final = _expected_path(source, output)
        try:
            with final.open("rb") as reader:
                reader_open.set()
                results = [future.result(timeout=TIMEOUT) for future in futures]
                assert reader.read() == final.read_bytes()
        finally:
            reader_open.set()
    assert results[0] == results[1]
    assert len(set(saved)) == 2
    _assert_png(final, source)
    assert list(final.parent.iterdir()) == [final]


def test_published_png_stays_complete_while_another_caller_is_still_saving(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = source.read_bytes()
    output = tmp_path / "output"
    first_at_save = threading.Event()
    second_partial = threading.Event()
    release_second = threading.Event()
    original_save = Image.Image.save

    def save(image, fp, *args, **kwargs):
        if threading.current_thread().name.startswith("first"):
            first_at_save.set()
            assert second_partial.wait(TIMEOUT)
        else:
            assert first_at_save.wait(TIMEOUT)
            Path(fp).write_bytes(b"incomplete PNG")
            second_partial.set()
            assert release_second.wait(TIMEOUT)
        original_save(image, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", save)
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as first_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="second") as second_pool,
    ):
        first = first_pool.submit(_prepare, source, output)
        assert first_at_save.wait(TIMEOUT)
        second = second_pool.submit(_prepare, source, output)
        try:
            result = first.result(timeout=TIMEOUT)
            final = Path(result.prepared_image_path)
            _assert_png(final, source)
            final_bytes = final.read_bytes()
            assert not second.done()
        finally:
            release_second.set()
        assert second.result(timeout=TIMEOUT) == result
    assert final.read_bytes() == final_bytes
    _assert_png(final, source)
    assert list(final.parent.iterdir()) == [final]
    assert source.read_bytes() == original
