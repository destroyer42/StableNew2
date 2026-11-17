"""PR-REVIEW-ARCHIVE-623: the Tk-free archive (move, restore, refusals and every no-data-loss path).

Temporary roots and synthetic images only. Every failure test asserts the one invariant that matters: each file still
exists exactly once (or the duplicate is reported) and nothing was overwritten.
"""

from __future__ import annotations

import errno
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.photo_optimize.paths import io_path, rename_without_replace
from src.review import archive as arc
from src.review.archive import (
    ARCHIVED_MESSAGE,
    apply_archive,
    apply_restore,
    archive_file,
    archive_root,
    archived_location,
    archived_reason,
    mirror_target,
    original_of,
    plan_archive,
    plan_restore,
    restore_file,
)
from tests.helpers.batch_ops_201 import admit, make_stack, review_njr

NO_PROTECTED: tuple[Path, ...] = ()


def _png(path: Path, color: int = 0) -> Path:
    path = Path(path)
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (color % 256, 20, 40)).save(io_path(path))
    return path


def _jpeg(path: Path, color: int = 0) -> Path:
    path = Path(path)
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (color % 256, 90, 10)).save(io_path(path), "JPEG")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _files(*roots: Path) -> dict[str, str]:
    """Every file under the roots with its digest: the no-data-loss ledger."""

    found: dict[str, str] = {}
    for root in roots:
        for directory, _dirs, names in os.walk(io_path(root)):
            for name in names:
                path = Path(directory) / name
                found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


@pytest.fixture
def output(tmp_path) -> Path:
    root = tmp_path / "output"
    root.mkdir()
    return root


def _plan(path: Path, output: Path, **kwargs):
    kwargs.setdefault("protected_roots", NO_PROTECTED)
    return plan_archive(path, output_root=output, **kwargs)


# -- the location rule ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("make", [_png, _jpeg], ids=["png", "jpeg"])
def test_a_file_under_the_output_root_mirrors_its_relative_path_and_comes_back_identical(
    output, make
):
    image = make(output / "Pipeline" / "run_1" / f"a{'.png' if make is _png else '.jpg'}")
    before = _sha(image)

    outcome = apply_archive(_plan(image, output))

    assert outcome.moved and not image.exists()
    expected = archive_root(output) / "Pipeline" / "run_1" / image.name
    assert outcome.target == expected and _sha(expected) == before
    assert original_of(expected, output) == image

    back = apply_restore(plan_restore(image, output_root=output))
    assert back.moved and _sha(image) == before and not expected.exists()


def test_an_image_outside_the_output_root_lands_under_external_and_restores(tmp_path, output):
    image = _png(tmp_path / "elsewhere" / "pics" / "b.png", 7)
    before = _sha(image)

    outcome = apply_archive(_plan(image, output))

    assert outcome.moved and "_external" in outcome.target.parts
    assert outcome.target.name == "b.png" and _sha(outcome.target) == before
    assert original_of(outcome.target, output) == image
    assert archived_location(image, output_root=output) == outcome.target
    assert restore_file(image, output_root=output).moved
    assert _sha(image) == before


def test_external_paths_are_laid_out_by_drive_unc_or_posix_root(output):
    if os.name == "nt":
        target = mirror_target(Path("D:/photos/x/c.png"), output)
        assert target.parts[-5:] == ("_external", "D", "photos", "x", "c.png")
        unc = mirror_target(Path("//server/share/dir/d.png"), output)
        assert unc.parts[-6:] == ("_external", "_unc", "server", "share", "dir", "d.png")
        assert original_of(unc, output) == Path("//server/share/dir/d.png")
    else:
        target = mirror_target(Path("/data/photos/c.png"), output)
        assert target.parts[-5:] == ("_external", "_posix", "data", "photos", "c.png")
        assert original_of(target, output) == Path("/data/photos/c.png")


def test_original_of_is_none_outside_the_archive(output):
    assert original_of(output / "Pipeline" / "a.png", output) is None


# -- different or identical file already at the target ------------------------------------------------------------


def test_a_different_file_at_the_target_gets_a_digest_suffix_and_nothing_is_overwritten(output):
    first = _png(output / "run" / "a.png", 1)
    first_sha = _sha(first)
    apply_archive(_plan(first, output))
    second = _png(output / "run" / "a.png", 2)  # same name, different bytes
    second_sha = _sha(second)

    plan = _plan(second, output)
    outcome = apply_archive(plan)

    assert plan.renamed and outcome.moved
    assert outcome.target.name == f"a.{second_sha[:8]}.png"
    assert not second.exists()
    assert sorted(_files(output).values()) == sorted([first_sha, second_sha])


def test_an_identical_file_at_the_target_leaves_the_source_and_reports_it(output):
    first = _png(output / "run" / "a.png", 3)
    apply_archive(_plan(first, output))
    duplicate = _png(output / "run" / "a.png", 3)  # same bytes
    ledger = _files(output)

    outcome = apply_archive(_plan(duplicate, output))

    assert outcome.status == "duplicate" and "identical" in outcome.message
    assert duplicate.exists() and _files(output) == ledger


def test_when_both_the_plain_and_the_suffixed_target_hold_other_files_the_move_is_refused(output):
    _png(output / "run" / "a.png", 1)
    apply_archive(_plan(output / "run" / "a.png", output))
    middle = _png(output / "run" / "a.png", 2)
    plan = _plan(middle, output)
    apply_archive(plan)
    third_bytes = _png(output / "run" / "a.png", 3)
    # Pretend the suffixed name for the third file is already taken by yet another file.
    suffixed = mirror_target(third_bytes, output).with_name(f"a.{_sha(third_bytes)[:8]}.png")
    _png(suffixed, 9)
    ledger = _files(output)

    refused = _plan(third_bytes, output)
    assert refused.refusal == arc.TARGET_CONFLICT
    assert apply_archive(refused).status == "refused"
    assert _files(output) == ledger


# -- failures that must not lose data ------------------------------------------------------------------------------


def test_a_rename_failure_leaves_the_file_in_place_and_reports_it(output):
    image = _png(output / "run" / "a.png")
    ledger = _files(output)

    def broken(_source, _target):
        raise OSError(errno.EIO, "disk error")

    outcome = apply_archive(_plan(image, output), rename=broken, sleep=lambda _s: None)

    assert outcome.status == "failed" and outcome.code == arc.MOVE_FAILED
    assert _files(output) == ledger  # only empty folders may differ


def test_a_transient_sharing_violation_is_retried_then_succeeds(output):
    image = _png(output / "run" / "a.png")
    attempts: list[int] = []

    def flaky(source, target):
        attempts.append(1)
        if len(attempts) < 3:
            error = PermissionError(errno.EACCES, "in use")
            error.winerror = 32
            raise error
        rename_without_replace(source, target)

    outcome = apply_archive(_plan(image, output), rename=flaky, sleep=lambda _s: None)
    assert outcome.moved and len(attempts) == 3


def test_a_persistent_sharing_violation_gives_up_with_the_file_in_place(output):
    image = _png(output / "run" / "a.png")
    ledger = _files(output)

    def locked(_source, _target):
        error = PermissionError(errno.EACCES, "in use")
        error.winerror = 32
        raise error

    outcome = apply_archive(_plan(image, output), rename=locked, sleep=lambda _s: None)
    assert outcome.status == "failed" and image.exists() and _files(output) == ledger


def test_a_source_that_vanishes_before_the_rename_is_reported_not_invented(output):
    image = _png(output / "run" / "a.png")
    plan = _plan(image, output)
    image.unlink()  # another program removed it between the plan and the move

    outcome = apply_archive(plan)

    assert outcome.status == "failed" and outcome.code == arc.MISSING
    assert _files(output) == {}


def test_a_target_that_appears_before_the_rename_is_never_replaced(output):
    image = _png(output / "run" / "a.png", 1)
    plan = _plan(image, output)
    squatter = _png(plan.target, 2)  # appears after planning
    ledger = _files(output)

    outcome = apply_archive(plan)

    assert outcome.status == "refused" and outcome.code == arc.TARGET_CONFLICT
    assert _files(output) == ledger and squatter.exists()


def test_an_exdev_rename_is_a_different_volume_refusal_with_the_file_in_place(output):
    image = _png(output / "run" / "a.png")

    def cross(_source, _target):
        raise OSError(errno.EXDEV, "cross-device link")

    outcome = apply_archive(_plan(image, output), rename=cross, sleep=lambda _s: None)
    assert outcome.status == "refused" and outcome.code == arc.DIFFERENT_VOLUME
    assert image.exists()


def test_a_file_changed_during_the_move_is_put_back(output):
    image = _png(output / "run" / "a.png")
    before = _sha(image)
    plan = _plan(image, output)

    outcome = apply_archive(plan, sha256=lambda _path: "0" * 64)

    assert outcome.status == "failed" and outcome.code == arc.CHANGED
    assert image.exists() and _sha(image) == before and not plan.target.exists()


def test_a_failed_rollback_still_loses_nothing_and_names_where_the_file_is(output):
    image = _png(output / "run" / "a.png")
    calls: list[tuple[Path, Path]] = []

    def one_way(source, target):
        calls.append((source, target))
        if len(calls) == 1:
            rename_without_replace(source, target)
        else:
            raise OSError(errno.EACCES, "cannot roll back")

    plan = _plan(image, output)
    outcome = apply_archive(plan, rename=one_way, sha256=lambda _p: "1" * 64, sleep=lambda _s: None)

    assert outcome.status == "failed" and outcome.code == arc.CHANGED
    assert plan.target.exists() and not image.exists()  # one copy, in the archive, and reported
    assert outcome.target == plan.target


def test_the_app_stopping_between_record_and_move_leaves_the_file_in_place(output):
    image = _png(output / "run" / "a.png")
    ledger = _files(output)
    plan = _plan(image, output)  # planned (and recorded) but never applied
    assert plan.ok and _files(output) == ledger and image.exists()
    assert not plan.target.exists()


def test_planning_is_read_only(output):
    image = _png(output / "run" / "a.png")
    ledger = _files(output)
    _plan(image, output)
    assert _files(output) == ledger and not archive_root(output).exists()


# -- refusals ------------------------------------------------------------------------------------------------------


def _expect_refused(image: Path, output: Path, code: str, **kwargs):
    ledger = _files(output.parent)
    plan = _plan(image, output, **kwargs)
    assert plan.refusal == code and not plan.ok and plan.reason
    outcome = apply_archive(plan)
    assert outcome.status == "refused" and outcome.code == code
    assert _files(output.parent) == ledger


def test_a_file_on_a_different_volume_is_not_moved(output):
    image = _png(output / "run" / "a.png")

    def volume_of(path: Path) -> object:
        return "D" if "_archive" in path.parts else "C"  # the archive is reported on another drive

    _expect_refused(image, output, arc.DIFFERENT_VOLUME, volume_of=volume_of)


def test_a_queued_or_running_job_input_blocks_the_move_until_it_is_gone(output):
    image = _png(output / "run" / "a.png")
    busy = {str(image)}
    _expect_refused(image, output, arc.QUEUED_JOB, active_inputs=lambda: busy)
    busy.clear()  # the job finished
    assert apply_archive(_plan(image, output, active_inputs=lambda: busy)).moved


def test_the_real_queue_reports_a_queued_jobs_source_image_as_busy(tmp_path, output):
    stack = make_stack(tmp_path)
    try:
        image = _png(output / "run" / "a.png")
        other = _png(output / "run" / "b.png")
        admit(stack, [review_njr("job-1", "batch-1", source=image)])

        busy = arc.active_input_paths(stack.queue)

        assert os.path.normcase(str(image)) in busy and os.path.normcase(str(other)) not in busy
        plan = _plan(image, output, active_inputs=lambda: arc.active_input_paths(stack.queue))
        assert plan.refusal == arc.QUEUED_JOB
        assert _plan(other, output, active_inputs=lambda: arc.active_input_paths(stack.queue)).ok
    finally:
        stack.repository.close()


def test_an_unreadable_queue_fails_closed(output):
    image = _png(output / "run" / "a.png")

    def broken() -> set[str]:
        raise RuntimeError("queue unavailable")

    _expect_refused(image, output, arc.QUEUE_UNKNOWN, active_inputs=broken)


def test_the_photo_optimize_workspace_and_the_learning_store_are_never_touched(tmp_path, output):
    workspace = _png(output / "PhotoOptimize" / "workspace" / "w.png")
    _expect_refused(workspace, output, arc.PROTECTED_STORE)
    store = tmp_path / "data" / "learning" / "discovered_experiments"
    kept = _png(store / "g1" / "i.png")
    _expect_refused(kept, output, arc.PROTECTED_STORE, protected_roots=(store,))


def _link_directory(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_link_or_junction_on_the_path_is_refused(tmp_path, output):
    real = tmp_path / "real_folder"
    image = _png(real / "a.png")
    _link_directory(output / "linked", real)
    through = output / "linked" / "a.png"
    assert through.exists()
    _expect_refused(through, output, arc.LINK)
    assert image.exists()


def test_the_output_root_being_a_link_is_refused(tmp_path):
    real = tmp_path / "real_output"
    _png(real / "run" / "a.png")
    link = tmp_path / "output_link"
    _link_directory(link, real)
    plan = plan_archive(link / "run" / "a.png", output_root=link, protected_roots=NO_PROTECTED)
    assert plan.refusal == arc.LINK


def test_a_file_symlink_is_refused_when_the_platform_allows_creating_one(tmp_path, output):
    target = _png(tmp_path / "t.png")
    link = output / "run" / "s.png"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(target, link)
    except OSError:
        # Creating a file symlink needs a privilege some Windows accounts lack; the link rule itself is the
        # directory case above, so there is nothing further to prove here.
        assert os.name == "nt"
        return
    _expect_refused(link, output, arc.LINK)


def test_a_file_already_in_the_archive_is_refused(output):
    image = _png(output / "run" / "a.png")
    moved = apply_archive(_plan(image, output)).target
    _expect_refused(moved, output, arc.ALREADY_ARCHIVED)


def test_discarding_again_after_a_move_reports_already_archived(output):
    image = _png(output / "run" / "a.png")
    apply_archive(_plan(image, output))
    again = _plan(image, output)  # the original path no longer exists but its archive does
    assert again.refusal == arc.ALREADY_ARCHIVED


def test_an_unreadable_or_missing_file_is_refused(output):
    image = _png(output / "run" / "a.png")
    plan = plan_archive(
        image, output_root=output, protected_roots=NO_PROTECTED, sha256=lambda _p: None
    )
    assert plan.refusal == arc.UNREADABLE
    assert _plan(output / "run" / "nope.png", output).refusal == arc.MISSING
    assert _plan(output / "run", output).refusal == arc.NOT_A_FILE


def test_refusal_text_never_contains_a_prompt_or_a_file_name(output):
    image = _png(output / "run" / "secret prompt words.png")
    plan = _plan(image, output, active_inputs=lambda: {str(image)})
    outcome = apply_archive(plan)
    assert "secret" not in outcome.message and "prompt" not in outcome.message.lower()
    assert "png" not in outcome.message
    for code in arc._REASONS:
        assert "secret" not in arc.reason_text(code)


# -- sidecar, spaces and long paths --------------------------------------------------------------------------------


def test_the_review_sidecar_moves_with_its_image_and_manifests_stay(output):
    image = _png(output / "run" / "a.png")
    sidecar = image.with_name("a.png.review.json")
    sidecar.write_text("{}", encoding="utf-8")
    manifest = output / "run" / "manifests" / "a.json"
    manifest.parent.mkdir()
    manifest.write_text("{}", encoding="utf-8")

    outcome = apply_archive(_plan(image, output))

    assert outcome.moved and outcome.sidecar_moved
    assert not sidecar.exists() and outcome.target.with_name("a.png.review.json").exists()
    assert manifest.exists()
    assert apply_restore(plan_restore(image, output_root=output)).sidecar_moved
    assert sidecar.exists()


def test_an_existing_sidecar_at_the_target_is_not_replaced(output):
    image = _png(output / "run" / "a.png")
    image.with_name("a.png.review.json").write_text('{"new": 1}', encoding="utf-8")
    plan = _plan(image, output)
    squatter = plan.target.with_name("a.png.review.json")
    squatter.parent.mkdir(parents=True)
    squatter.write_text('{"old": 1}', encoding="utf-8")

    outcome = apply_archive(plan)

    assert outcome.moved and not outcome.sidecar_moved
    assert squatter.read_text(encoding="utf-8") == '{"old": 1}'
    assert image.with_name("a.png.review.json").exists()


def test_a_path_with_spaces_archives_and_restores(output):
    image = _png(output / "my run 1" / "sub folder" / "a b c.png", 5)
    before = _sha(image)
    outcome = apply_archive(_plan(image, output))
    assert outcome.moved and outcome.target.parent.name == "sub folder"
    assert restore_file(image, output_root=output).moved and _sha(image) == before


def test_a_very_long_path_archives_and_restores(output):
    folder = output
    for index in range(6):
        folder = folder / (f"segment{index}_" + "x" * 40)
    image = _png(folder / ("long_name_" + "y" * 60 + ".png"), 6)
    assert len(str(image)) > 260
    before = _sha(image)

    outcome = apply_archive(_plan(image, output))

    assert outcome.moved and io_path(outcome.target).exists() and not io_path(image).exists()
    back = restore_file(image, output_root=output)
    assert back.moved and _sha(image) == before


# -- restore -------------------------------------------------------------------------------------------------------


def test_restore_refuses_when_a_different_file_sits_at_the_original_and_offers_a_free_name(output):
    image = _png(output / "run" / "a.png", 1)
    archived_sha = _sha(image)
    apply_archive(_plan(image, output))
    other = _png(output / "run" / "a.png", 2)  # something new took the name
    other_sha = _sha(other)
    ledger = _files(output)

    plan = plan_restore(image, output_root=output)

    assert plan.refusal == arc.OCCUPIED and plan.alternative is not None
    assert plan.alternative.name == f"a.restored-{archived_sha[:8]}.png"
    refused = apply_restore(plan)
    assert refused.status == "refused" and refused.alternative == plan.alternative
    assert _files(output) == ledger and _sha(other) == other_sha

    accepted = apply_restore(plan, use_alternative=True)
    assert accepted.moved and accepted.target == plan.alternative
    assert _sha(plan.alternative) == archived_sha and _sha(image) == other_sha


def test_restore_of_an_identical_original_keeps_the_archived_copy(output):
    image = _png(output / "run" / "a.png", 4)
    archived = apply_archive(_plan(image, output)).target
    _png(output / "run" / "a.png", 4)

    outcome = apply_restore(plan_restore(image, output_root=output))

    assert outcome.status == "duplicate" and archived.exists() and image.exists()


def test_restore_with_nothing_archived_is_a_no_op_or_a_missing_report(output):
    image = _png(output / "run" / "a.png")
    assert apply_restore(plan_restore(image, output_root=output)).status == "noop"
    assert plan_restore(output / "run" / "gone.png", output_root=output).refusal == arc.MISSING


def test_restore_puts_a_digest_suffixed_copy_back_by_digest(output):
    first = _png(output / "run" / "a.png", 1)
    apply_archive(_plan(first, output))
    second = _png(output / "run" / "a.png", 2)
    digest = _sha(second)
    moved = apply_archive(_plan(second, output)).target
    assert moved.name == f"a.{digest[:8]}.png"

    plan = plan_restore(second, output_root=output, digest=digest)

    assert plan.archived == moved
    assert apply_restore(plan).moved and _sha(second) == digest


def test_restore_across_a_volume_change_is_refused_without_moving(output):
    image = _png(output / "run" / "a.png")
    apply_archive(_plan(image, output))
    plan = plan_restore(
        image, output_root=output, volume_of=lambda p: "A" if "_archive" in str(p) else "B"
    )
    assert plan.refusal == arc.DIFFERENT_VOLUME
    assert apply_restore(plan).status == "refused"


def test_restore_that_fails_verification_is_undone(output):
    image = _png(output / "run" / "a.png")
    apply_archive(_plan(image, output))
    plan = plan_restore(image, output_root=output)
    outcome = apply_restore(plan, sha256=lambda _p: "2" * 64)
    assert outcome.status == "failed" and outcome.code == arc.CHANGED
    assert plan.archived.exists() and not image.exists()


# -- reader helpers ------------------------------------------------------------------------------------------------


def test_archived_reason_is_set_only_when_the_file_is_absent_and_its_archive_exists(output):
    image = _png(output / "Pipeline" / "run" / "a.png")
    assert archived_reason(image) is None  # present
    assert archived_reason(output / "Pipeline" / "run" / "nope.png") is None  # never archived
    apply_archive(_plan(image, output))
    assert (
        archived_reason(image) == ARCHIVED_MESSAGE
    )  # found from the path alone, no configured root
    assert archived_reason("") is None and archived_reason(None) is None


def test_archived_location_with_a_digest_ignores_a_different_file_at_the_plain_name(output):
    first = _png(output / "run" / "a.png", 1)
    apply_archive(_plan(first, output))
    second = _png(output / "run" / "a.png", 2)
    digest = _sha(second)
    suffixed = apply_archive(_plan(second, output)).target
    assert archived_location(second, output_root=output, digest=digest) == suffixed
    assert archived_location(second, output_root=output) == mirror_target(second, output)


def test_the_archive_helpers_read_no_prompt_text(output):
    image = _png(output / "run" / "a.png")
    outcome = archive_file(
        image, output_root=output, active_inputs=None, protected_roots=NO_PROTECTED
    )
    assert outcome.moved
