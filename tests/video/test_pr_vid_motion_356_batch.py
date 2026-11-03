"""PR-VID-MOTION-356: batch conversion of a folder of mocap files, against a fake Blender.

No Blender, GPU, model, network or queue is used.  Real MP4 encoding uses CPU-only FFmpeg and those tests are skipped where
FFmpeg is absent.  The batch is an offline asset operation: these tests also pin that it adds no job, queue or runner.
"""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.video.motion_conversion import batch as bt
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion import diagnostics as diag
from src.video.motion_conversion import inventory as inv
from src.video.motion_conversion.conversion_service import (
    OWNER_MARKER,
    WORK_DIRNAME,
    MotionConverter,
    verify_published,
)
from src.video.motion_conversion.workbench import ConversionWorkbench
from tests.helpers.motion_conversion_354 import (
    MIXAMO_BONES,
    fake_environ,
    fake_install,
    write_bvh,
    write_fbx,
)
from tests.helpers.motion_library_353 import FFMPEG, needs_ffmpeg, new_store

BVH_LONG = (
    "HIERARCHY\nROOT Hips\n{\n OFFSET 0 0 0\n CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n"
    " End Site\n {\n  OFFSET 0 10 0\n }\n}\nMOTION\nFrames: 2\nFrame Time: 0.0333333\n0 0 0 0 0 0\n0 0 0 0 0 0\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _settings(**changes) -> bt.BatchSettings:
    values = {"frames": 9, "width": 256, "height": 272}
    values.update(changes)
    return bt.BatchSettings(**values)


def _env(tmp_path: Path, **fake_env: str):
    store = new_store(tmp_path)
    install = fake_install(tmp_path / "bin")
    environ = fake_environ(**fake_env)
    bench = ConversionWorkbench(
        library_root=store.root,
        blender=install,
        ffmpeg=FFMPEG or "ffmpeg",
        converter_factory=lambda inst, root, ffmpeg: MotionConverter(
            inst, root, ffmpeg=ffmpeg, environ=environ, diagnostics_dir=tmp_path / "diag"
        ),
    )
    return SimpleNamespace(
        store=store,
        bench=bench,
        runner=bt.BatchRunner(bench, store),
        source=tmp_path / "assets",
        tmp=tmp_path,
    )


def _assets(env) -> None:
    root = env.source
    write_fbx(root / "mixamo" / "walk.fbx")
    write_fbx(root / "mixamo" / "run.fbx", curves=4)
    write_fbx(root / "xsens" / "skeleton.fbx", mesh=False, skin=False)
    write_fbx(root / "xsens" / "curves_only.fbx", mesh=False, skin=False, bones=())
    write_bvh(root / "bvh" / "capture.bvh")
    write_bvh(root / "bvh" / "broken.bvh", valid=False)
    (root / "mixamo" / "walk_copy.fbx").write_bytes((root / "mixamo" / "walk.fbx").read_bytes())
    (root / "notes.txt").write_text("not an asset", encoding="utf-8")
    with zipfile.ZipFile(root / "pack.zip", "w") as archive:
        archive.writestr("inside.fbx", b"x")


def _scan(env, **settings) -> bt.BatchInventory:
    return bt.scan_for_batch(env.bench, env.source, _settings(**settings))


def _run(env, inventory, entries=None, **kwargs) -> bt.BatchSummary:
    return env.runner.run(
        inventory,
        inventory.to_convert if entries is None else entries,
        confirmation=inventory.confirmation(),
        **kwargs,
    )


def _snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ dry run


def test_the_dry_run_says_what_will_happen_to_every_file_and_writes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _assets(env)
    before = _snapshot(env.source)
    inventory = _scan(env)
    assert (
        _snapshot(env.source) == before
    )  # nothing created, changed or extracted inside the scanned folder
    where = {e.relative_path: e for e in inventory.entries}
    assert where["mixamo/walk.fbx"].disposition == bt.DISP_CONVERT
    assert where["mixamo/walk.fbx"].profile == cp.PROFILE_CHARACTER
    assert where["xsens/skeleton.fbx"].disposition == bt.DISP_CONVERT
    assert (
        where["xsens/skeleton.fbx"].profile == cp.PROFILE_SKELETON
    )  # never retargeted onto a character
    assert where["bvh/capture.bvh"].disposition == bt.DISP_CONVERT
    assert where["bvh/capture.bvh"].profile == cp.PROFILE_SKELETON
    assert where["mixamo/walk_copy.fbx"].disposition == bt.DISP_DUPLICATE
    assert where["xsens/curves_only.fbx"].disposition == bt.DISP_INELIGIBLE
    assert (
        "no rig" in where["xsens/curves_only.fbx"].reason.lower()
        or "skeleton" in where["xsens/curves_only.fbx"].reason.lower()
    )
    assert where["bvh/broken.bvh"].disposition == bt.DISP_INELIGIBLE
    assert where["notes.txt"].disposition == bt.DISP_INELIGIBLE
    assert where["pack.zip"].disposition == bt.DISP_ARCHIVE
    assert where["pack.zip!inside.fbx"].disposition == bt.DISP_ARCHIVE
    assert [e.relative_path for e in inventory.to_convert] == [
        "bvh/capture.bvh",
        "mixamo/run.fbx",
        "mixamo/walk.fbx",
        "xsens/skeleton.fbx",
    ]


def test_the_dry_run_states_destination_budget_and_its_uncertainty(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _assets(env)
    inventory = _scan(env)
    estimate = inventory.estimate
    assert 0 < estimate.low_bytes < estimate.expected_bytes < estimate.high_bytes
    assert estimate.temporary_bytes > 0 and "default" in estimate.basis
    assert inventory.destination == str(env.store.root / "conversions")
    confirmation = inventory.confirmation()
    assert confirmation.file_count == 4 and confirmation.destination == inventory.destination
    assert confirmation.budget_bytes == estimate.high_bytes + estimate.temporary_bytes
    assert inventory.free_bytes > 0


def test_the_scan_is_bounded_never_follows_links_and_skips_the_output_folder(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    write_fbx(env.source / "a" / "b" / "c" / "deep.fbx")
    write_fbx(env.source / "top.fbx")
    write_fbx(
        env.source / "conversions" / "own_output.fbx"
    )  # inside the destination: never scanned
    destination = env.store.root / "conversions"
    report = inv.scan_inventory(env.source, max_depth=1, exclude=[env.source / "conversions"])
    names = {e.relative_path for e in report.entries}
    assert names == {"top.fbx"} and any("deeper than" in s for s in report.skipped)
    assert any("(excluded)" in s for s in report.skipped)
    outside = tmp_path / "outside"
    write_fbx(outside / "secret.fbx")
    link = env.source / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        junction = subprocess.run(  # a Windows junction needs no privilege and leads out of the folder the same way
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=False
        )
        if junction.returncode != 0:
            pytest.skip("neither symbolic links nor junctions are available here")
    linked = inv.scan_inventory(env.source, exclude=[env.source / "conversions"])
    assert "link/secret.fbx" not in {e.relative_path for e in linked.entries}
    assert destination.parent == env.store.root
    assert inv.scan_inventory(env.source, max_files=1).truncated is True


def test_a_file_over_the_size_limit_is_listed_but_never_read(tmp_path: Path) -> None:
    env = _env(tmp_path)
    write_fbx(env.source / "big.fbx")
    report = inv.scan_inventory(env.source, max_file_bytes=10)
    entry = report.entries[0]
    assert entry.state == inv.STATE_UNSUPPORTED and entry.sha256 == "" and "limit" in entry.reason


def test_a_sample_shows_each_kind_of_input_first(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _assets(env)
    sample = _scan(env).sample()
    assert len(sample) == bt.SAMPLE_SIZE
    assert {(e.route) for e in sample} >= {
        inv.ROUTE_FBX_CHARACTER,
        inv.ROUTE_FBX_SKELETON,
        inv.ROUTE_BVH_SKELETON,
    }


# ------------------------------------------------------------------ confirmation and refusals


def test_a_batch_needs_a_confirmation_that_matches_the_scan_exactly(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _assets(env)
    inventory = _scan(env)
    stale = bt.BatchConfirmation(
        inventory.confirmation().file_count + 1,
        inventory.destination,
        inventory.confirmation().budget_bytes,
    )
    with pytest.raises(bt.BatchRefused, match="confirmation"):
        env.runner.run(inventory, inventory.to_convert, confirmation=stale)
    elsewhere = bt.BatchConfirmation(
        inventory.confirmation().file_count,
        str(tmp_path / "other"),
        inventory.confirmation().budget_bytes,
    )
    with pytest.raises(bt.BatchRefused, match="confirmation"):
        env.runner.run(inventory, inventory.to_convert, confirmation=elsewhere)
    assert not (env.store.root / "conversions" / "converted").exists()


def test_only_files_of_the_confirmed_scan_can_be_run_and_blender_and_space_are_required(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    _assets(env)
    inventory = _scan(env)
    stranger = bt.BatchEntry(
        "x.fbx", "x.fbx", "0" * 64, "fbx", "fbx_character", "", bt.DISP_CONVERT, ""
    )
    with pytest.raises(bt.BatchRefused, match="Not part of the confirmed batch"):
        _run(env, inventory, [stranger])
    full = bt.BatchRunner(env.bench, env.store, free_bytes=lambda _p: 1024)
    with pytest.raises(bt.BatchRefused, match="Not enough free space"):
        full.run(inventory, inventory.to_convert, confirmation=inventory.confirmation())
    bare = ConversionWorkbench(library_root=env.store.root)
    with pytest.raises(bt.BatchRefused, match="Blender"):
        bt.BatchRunner(bare, env.store).run(
            inventory, inventory.to_convert, confirmation=inventory.confirmation()
        )


def test_frames_are_fitted_to_what_the_animation_can_supply_and_never_padded() -> None:
    short = cp.AnimationProbe(
        cp.parse_rational(24),
        cp.parse_rational(0),
        cp.parse_rational(30),
        MIXAMO_BONES,
        True,
        "4.2.3",
    )  # 1.25 s: room for 31 frames
    assert bt.fit_frames(_settings(frames=49), short) == 29  # the longest 4n+1 length that fits
    assert bt.fit_frames(_settings(frames=17), short) == 17
    assert bt.fit_frames(_settings(frames=49, legal_frames=(17, 33, 49)), short) == 17
    tiny = cp.AnimationProbe(
        cp.parse_rational(24),
        cp.parse_rational(0),
        cp.parse_rational(2),
        MIXAMO_BONES,
        True,
        "4.2.3",
    )
    with pytest.raises(cp.ConversionPlanError, match="fewer than the shortest"):
        bt.fit_frames(_settings(frames=17), tiny)
    with pytest.raises(cp.ConversionPlanError, match="after the end"):
        bt.fit_frames(_settings(start_seconds="9"), short)


# ------------------------------------------------------------------ running


@needs_ffmpeg
def test_every_eligible_file_is_converted_verified_registered_and_originals_are_untouched(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    _assets(env)
    before = _snapshot(env.source)
    inventory = _scan(env)
    seen: list[bt.BatchProgress] = []
    summary = _run(env, inventory, progress=seen.append)
    assert _snapshot(env.source) == before
    assert (
        summary.counts[bt.ITEM_CONVERTED] == 4
        and not summary.failures
        and not summary.stopped_reason
    )
    assert [p.relative_path for p in seen] == [e.relative_path for e in inventory.to_convert]
    for result in summary.results:
        assert result.ok and verify_published(result.directory) == "" and result.asset_id
    assets = env.store.assets()
    assert len(assets) == 4 and all(bt.BATCH_TAG in a.tags for a in assets)
    report = Path(summary.report_path)
    assert report.is_file() and report.parent.name == bt.REPORTS_DIRNAME
    text = report.read_text(encoding="utf-8")
    assert str(tmp_path) not in text  # a summary names files relative to the scanned folder


@needs_ffmpeg
def test_restarting_skips_identical_verified_results_without_starting_blender(
    tmp_path: Path,
) -> None:
    log = tmp_path / "blender.log"
    env = _env(tmp_path, FAKE_BLENDER_LOG=str(log))
    _assets(env)
    first = _run(env, _scan(env))
    assert first.counts[bt.ITEM_CONVERTED] == 4
    calls_after_first = log.read_text(encoding="utf-8").count("\n")

    again = _scan(env)  # a fresh scan, as after an application restart
    assert again.counts[bt.DISP_CONVERT] == 0 and again.counts[bt.DISP_EXISTING] == 4
    restarted = bt.BatchRunner(env.bench, env.store)
    summary = restarted.run(
        again, again.to_convert, confirmation=again.confirmation(), include_existing=True
    )
    assert summary.counts[bt.ITEM_EXISTING] == 4 and summary.counts[bt.ITEM_CONVERTED] == 0
    assert (
        log.read_text(encoding="utf-8").count("\n") == calls_after_first
    )  # Blender was not started
    assert len(env.store.assets()) == 4  # nothing was registered twice


@needs_ffmpeg
def test_a_changed_setting_makes_a_new_conversion_instead_of_reusing_the_old(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    write_fbx(env.source / "walk.fbx")
    _run(env, _scan(env))
    different = _scan(env, camera=cp.CAMERA_SIDE)
    assert different.counts[bt.DISP_CONVERT] == 1 and different.counts[bt.DISP_EXISTING] == 0
    for frames in (5, 13):  # another length is another conversion, never "close enough"
        assert _scan(env, frames=frames).counts[bt.DISP_CONVERT] == 1
    assert _scan(env, frames=9).counts[bt.DISP_EXISTING] == 1


@needs_ffmpeg
def test_a_short_animation_is_probed_then_reused_on_restart_without_rendering_again(
    tmp_path: Path,
) -> None:
    log = tmp_path / "blender.log"
    env = _env(tmp_path, FAKE_BLENDER_LOG=str(log), FAKE_BLENDER_LAST="13/1")  # room for 13 frames
    write_fbx(env.source / "short.fbx")
    first = _run(env, _scan(env, frames=17))
    assert first.results[0].status == bt.ITEM_CONVERTED and first.results[0].frames == 13
    renders = log.read_text(encoding="utf-8").count('"render"')
    again = _scan(
        env, frames=17
    )  # 13 on disk is not 17, so the dry run cannot prove it: it is probed, then reused
    summary = _run(env, again)
    assert summary.results[0].status == bt.ITEM_REUSED
    assert log.read_text(encoding="utf-8").count('"render"') == renders
    assert len(env.store.assets()) == 1


@needs_ffmpeg
def test_a_failing_file_does_not_block_the_valid_files_and_is_not_retried(tmp_path: Path) -> None:
    log = tmp_path / "blender.log"
    env = _env(
        tmp_path,
        FAKE_BLENDER_LOG=str(log),
        FAKE_BLENDER_FAIL_ON="run.fbx",
        FAKE_BLENDER_FAIL_MODE="oom",
    )
    _assets(env)
    summary = _run(env, _scan(env))
    by_name = {r.relative_path: r for r in summary.results}
    bad = by_name["mixamo/run.fbx"]
    assert bad.status == bt.ITEM_FAILED and bad.kind == diag.KIND_MEMORY and bad.diagnostic_path
    assert Path(bad.diagnostic_path).is_file()
    others = [r for name, r in by_name.items() if name != "mixamo/run.fbx"]
    assert len(others) == 3 and all(r.status == bt.ITEM_CONVERTED for r in others)
    assert not summary.stopped_reason  # one bad file is not a reason to stop
    assert "run.fbx" in summary.text() and "ran out of memory" in summary.text().lower()
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if "run.fbx" in line]
    assert len(calls) == 1  # probe only: the failed file was neither retried nor rendered again
    assert len(env.store.assets()) == 3


@needs_ffmpeg
def test_a_file_that_renders_blank_or_static_is_refused_while_the_rest_continue(
    tmp_path: Path,
) -> None:
    for mode, fragment in (("blank", "no visible subject"), ("static", "not applied")):
        env = _env(tmp_path / mode, FAKE_BLENDER_FAIL_ON="walk.fbx", FAKE_BLENDER_FAIL_MODE=mode)
        _assets(env)
        summary = _run(env, _scan(env))
        failed = {r.relative_path: r for r in summary.failures}
        assert set(failed) == {"mixamo/walk.fbx"}
        assert (
            failed["mixamo/walk.fbx"].kind == diag.KIND_OUTPUT
            and fragment in failed["mixamo/walk.fbx"].reason
        )
        assert summary.counts[bt.ITEM_CONVERTED] == 3


def test_a_file_changed_after_the_scan_is_refused_by_identity(tmp_path: Path) -> None:
    env = _env(tmp_path)
    write_fbx(env.source / "walk.fbx")
    inventory = _scan(env)
    (env.source / "walk.fbx").write_bytes((env.source / "walk.fbx").read_bytes() + b"tampered")
    summary = _run(env, inventory)
    only = summary.results[0]
    assert only.status == bt.ITEM_FAILED and only.kind == diag.KIND_SOURCE


def test_a_missing_blender_capability_stops_the_batch_instead_of_repeating_it(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, FAKE_BLENDER_MODE="gpu")  # every render would report a non-CPU device
    _assets(env)
    summary = _run(env, _scan(env))
    assert summary.counts[bt.ITEM_FAILED] == 1 and summary.counts[bt.ITEM_NOT_RUN] == 3
    assert "every file would fail" in summary.stopped_reason


def test_repeated_blender_crashes_stop_the_batch_after_a_bounded_run(tmp_path: Path) -> None:
    env = _env(tmp_path, FAKE_BLENDER_MODE="crash")
    for index in range(bt.MAX_CONSECUTIVE_SYSTEMIC + 3):
        write_fbx(env.source / f"clip{index:02d}.fbx", curves=3 + index)
    summary = _run(env, _scan(env))
    assert summary.counts[bt.ITEM_FAILED] == bt.MAX_CONSECUTIVE_SYSTEMIC
    assert summary.counts[bt.ITEM_NOT_RUN] == 3
    assert (
        "in a row" in summary.stopped_reason and "skipped on the next run" in summary.stopped_reason
    )


def test_a_nearly_full_destination_stops_the_batch(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _assets(env)
    inventory = _scan(env)
    readings = iter([10**12, 10**12, 10**12, 5])  # roomy for the preflight, then nearly full
    runner = bt.BatchRunner(env.bench, env.store, free_bytes=lambda _p: next(readings, 5))
    summary = runner.run(inventory, inventory.to_convert, confirmation=inventory.confirmation())
    assert "nearly full" in summary.stopped_reason
    assert summary.counts[bt.ITEM_NOT_RUN] >= 1


# ------------------------------------------------------------------ cancellation, interruption, corruption


def _fake_blender_processes(tmp_path: Path) -> list[int]:
    import psutil

    script = str(tmp_path / "bin" / "fake_blender.py")
    found = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if script in (process.info.get("cmdline") or []):
                found.append(process.info["pid"])
        except (psutil.Error, OSError):
            continue
    return found


def test_cancelling_stops_the_current_file_leaves_no_blender_process_and_skips_the_rest(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, FAKE_BLENDER_MODE="hang")
    _assets(env)
    inventory = _scan(env)
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    started = time.monotonic()
    summary = _run(env, inventory, cancel=cancel)
    assert time.monotonic() - started < 60
    assert summary.counts[bt.ITEM_CANCELLED] == 1 and summary.counts[bt.ITEM_NOT_RUN] == 3
    assert "Cancelled" in summary.stopped_reason
    deadline = time.monotonic() + 10
    while _fake_blender_processes(tmp_path) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert _fake_blender_processes(tmp_path) == []  # no unowned Blender survives a cancelled batch
    assert not list((env.store.root / "conversions" / WORK_DIRNAME).glob("run-*"))
    assert not (env.store.root / "conversions" / "converted").exists()


def test_interrupted_runs_leave_only_stale_owned_work_folders_which_are_swept(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    work = env.store.root / "conversions" / WORK_DIRNAME
    stale = work / "run-aaaa"
    stale.mkdir(parents=True)
    (stale / OWNER_MARKER).write_text("run-aaaa", encoding="utf-8")
    (stale / "frames").mkdir()
    old = time.time() - 7200
    import os

    os.utime(stale, (old, old))
    fresh = work / "run-bbbb"  # a live run's folder: recent, so left alone
    fresh.mkdir()
    (fresh / OWNER_MARKER).write_text("run-bbbb", encoding="utf-8")
    foreign = work / "not-ours"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("mine", encoding="utf-8")
    os.utime(foreign, (old, old))
    impostor = work / "run-cccc"
    impostor.mkdir()
    (impostor / OWNER_MARKER).write_text("another name", encoding="utf-8")
    os.utime(impostor, (old, old))
    assert env.bench.prepare_batch() == 1
    assert (
        not stale.exists()
        and fresh.is_dir()
        and (foreign / "keep.txt").is_file()
        and impostor.is_dir()
    )


@needs_ffmpeg
def test_a_corrupt_published_video_is_not_reused_and_is_republished_beside_it(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path)
    write_fbx(env.source / "walk.fbx")
    first = _run(env, _scan(env))
    video = Path(first.results[0].directory)
    mp4 = next(video.glob("*.mp4"))
    mp4.write_bytes(mp4.read_bytes() + b"corrupt")
    assert verify_published(video) != ""
    again = _scan(env)
    assert again.counts[bt.DISP_EXISTING] == 0 and again.counts[bt.DISP_CONVERT] == 1
    second = _run(env, again)
    assert second.counts[bt.ITEM_CONVERTED] == 1
    assert (
        second.results[0].directory != first.results[0].directory
    )  # published beside, never over the damaged one
    assert mp4.read_bytes().endswith(b"corrupt")  # the existing media file was never overwritten


# ------------------------------------------------------------------ boundaries


def test_the_batch_adds_no_job_queue_runner_or_second_catalog() -> None:
    source = Path(bt.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "JobService",
        "NormalizedJobRecord",
        "PipelineRunner",
        "run_njr",
        "submit_njrs",
        "JobRepository",
        "sqlite3",
        "import_video(",
    ):
        assert forbidden not in source, forbidden
    assert "MotionLibraryStore" in source  # registration goes through the existing library
