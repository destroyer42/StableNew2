"""PR-REVIEW-ARCHIVE-623: readers say "archived by Review" (never reading the archived copy) and enumerators skip it.

Temporary roots and synthetic images only; the readers are the real History projection, replay input verification,
batch retry preflight and batch output resolution.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from src.gui.view_contracts import history_comparison_artifact as comparison
from src.gui.view_contracts.history_artifact_contract import (
    resolve_recorded_artifact,
    resolve_single_still_image,
)
from src.gui_v2.history_compare_model import ComparisonRefused
from src.learning import output_scanner
from src.learning.output_scanner import OutputScanner
from src.pipeline.replay_input_verification import InputCheck, verify_inputs
from src.queue.batch_membership import BatchKey, BatchKind
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus
from src.review import archive as arc
from src.review.archive import ARCHIVED_MESSAGE, apply_archive, plan_archive, restore_file
from src.review.workspace_io import scan_image_folder
from src.state.output_routing import iter_output_run_dirs, resolve_output_artifact_path
from tests.helpers.batch_ops_201 import admit, image_file, make_stack, review_njr, settle_fifo

REVIEW = BatchKey(BatchKind.REVIEW, "rev")


def _archive(image: Path, output: Path) -> Path:
    outcome = apply_archive(plan_archive(image, output_root=output, protected_roots=()))
    assert outcome.moved
    return outcome.target


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def output(tmp_path) -> Path:
    root = tmp_path / "output"
    root.mkdir()
    return root


# -- History -------------------------------------------------------------------------------------------------------


def test_history_projection_says_archived_and_returns_no_path_then_works_after_restore(output):
    image = image_file(output / "Pipeline" / "run" / "a.png", 1)
    result = {"artifact": {"primary_path": str(image)}, "image_count": 1}
    archived = _archive(image, output)

    for projection in (resolve_recorded_artifact(result), resolve_single_still_image(result)):
        assert projection.path is None and projection.kind == "image"
        assert "archived by Review" in projection.message and "Restore" in projection.message
    assert archived.exists()  # nothing read it in place of the original

    restore_file(image, output_root=output)
    assert resolve_single_still_image(result).path == str(image)


def test_a_file_that_was_never_archived_still_reports_missing(output):
    gone = output / "Pipeline" / "run" / "gone.png"
    projection = resolve_recorded_artifact({"artifact": {"primary_path": str(gone)}})
    assert projection.path is None and "missing" in projection.message


def test_compare_with_parent_refuses_an_archived_image_without_naming_the_file(output):
    image = image_file(output / "Pipeline" / "run" / "secret prompt.png", 2)
    entry = JobHistoryEntry(
        job_id="job-1",
        created_at=datetime.now(),
        status=JobStatus.COMPLETED,
        result={"artifact": {"primary_path": str(image)}, "image_count": 1},
    )
    assert comparison.verify_image(entry).sha256 == _sha(image)

    archived = _archive(image, output)
    with pytest.raises(ComparisonRefused) as raised:
        comparison.verify_image(entry)
    message = str(raised.value)
    assert "archived by Review" in message and "Restore" in message
    assert "secret" not in message and "png" not in message
    assert archived.exists()

    restore_file(image, output_root=output)
    assert comparison.verify_image(entry).sha256 == _sha(image)


# -- replay and batch retry ----------------------------------------------------------------------------------------


def test_replay_input_verification_names_the_archive_and_never_reads_the_copy(output):
    image = image_file(output / "Pipeline" / "run" / "a.png", 3)
    digest = _sha(image)
    _archive(image, output)
    hashed: list[str] = []

    issues = verify_inputs(
        [InputCheck("source image", str(image), digest)],
        hash_file=lambda path: hashed.append(path) or digest,
    )

    assert len(issues) == 1 and not hashed
    described = issues[0].describe()
    assert "archived by Review; Restore to use it" in described
    assert "missing or was moved" not in described

    restore_file(image, output_root=output)
    assert verify_inputs([InputCheck("source image", str(image), digest)]) == []


def test_replay_input_verification_still_reports_a_plain_missing_input():
    issues = verify_inputs([InputCheck("source image", str(Path("nowhere") / "x.png"))])
    assert issues[0].reason == "is missing or was moved"


def test_batch_retry_preflight_reports_an_archived_source_then_passes_after_restore(tmp_path):
    stack = make_stack(tmp_path)
    try:
        output = tmp_path / "output"
        sources = [image_file(output / "Pipeline" / "src" / f"s{i}.png", i) for i in range(2)]
        digests = [_sha(path) for path in sources]
        admit(
            stack,
            [
                review_njr(
                    f"rev-{i}", "rev", source=sources[i], source_count=2, artifact_sha256=digests[i]
                )
                for i in range(2)
            ],
        )
        failure = {
            "success": False,
            "error": "no route",
            "metadata": {
                "failure_evidence": {
                    "contract": "webui_failure_evidence/1",
                    "error_code": "connection_error",
                    "webui_unavailable": True,
                    "stage": "img2img",
                }
            },
        }
        settle_fifo(stack, {0: "failed", 1: "failed"}, result=failure)
        assert stack.operations.preflight_retry(REVIEW, ["rev-0"]).submittable

        _archive(sources[0], output)
        plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-1"])
        by_job = {item.job_id: item for item in plan.items}
        assert "archived by Review; Restore to use it" in by_job["rev-0"].reasons[0]
        assert not by_job["rev-1"].reasons

        restore_file(sources[0], output_root=output)
        assert stack.operations.preflight_retry(REVIEW, ["rev-0"]).submittable
    finally:
        stack.repository.close()


def test_batch_output_resolution_says_archived_and_lists_no_image(tmp_path):
    stack = make_stack(tmp_path)
    try:
        output = tmp_path / "output"
        kept = image_file(output / "Pipeline" / "run" / "o0.png", 0)
        gone = image_file(output / "Pipeline" / "run" / "o1.png", 1)
        admit(stack, [review_njr(f"o-{i}", "rev", source_count=2) for i in range(2)])
        settle_fifo(
            stack,
            results={
                index: {"success": True, "variants": [{"stage": "img2img", "path": str(path)}]}
                for index, path in enumerate((kept, gone))
            },
        )
        _archive(gone, output)

        resolution = stack.operations.resolve_outputs(REVIEW, ["o-0", "o-1"])

        assert resolution.images == (str(kept),)
        assert [(job, reason) for job, _path, reason in resolution.unavailable] == [
            ("o-1", ARCHIVED_MESSAGE)
        ]
        assert "missing or unreadable" in resolution.messages[0]
    finally:
        stack.repository.close()


# -- the artifact resolver -----------------------------------------------------------------------------------------


def test_the_artifact_resolver_never_returns_an_archived_path(output):
    image = image_file(output / "Pipeline" / "run" / "a.png", 4)
    archived = _archive(image, output)

    assert resolve_output_artifact_path(image, base_output_dir=output) == str(
        image
    )  # unresolved: unchanged
    assert resolve_output_artifact_path(archived, base_output_dir=output) == str(archived)
    stale = Path("elsewhere") / "output" / "Testing" / "run" / "a.png"
    assert resolve_output_artifact_path(stale, base_output_dir=output) == str(stale)
    for raw in (image, archived, stale, "Pipeline/run/a.png"):
        resolved = resolve_output_artifact_path(raw, base_output_dir=output)
        assert resolved == str(raw) or not arc.is_under_archive(resolved, output)

    other = image_file(output / "Pipeline" / "run" / "b.png", 5)
    assert resolve_output_artifact_path(other, base_output_dir=output) == str(other.resolve())


def test_the_artifact_resolver_still_follows_a_rebalanced_route(output):
    moved = image_file(output / "Testing" / "run" / "a.png", 6)
    stale = output / "Pipeline" / "run" / "a.png"
    assert resolve_output_artifact_path(stale, base_output_dir=output) == str(moved.resolve())


# -- enumerators ---------------------------------------------------------------------------------------------------


def test_review_folder_scan_skips_the_archive(output):
    keep = image_file(output / "Pipeline" / "run" / "keep.png", 1)
    moved = image_file(output / "Pipeline" / "run" / "moved.png", 2)
    _archive(moved, output)

    scan = scan_image_folder(output, skip=(arc.archive_root(output),))

    assert scan.paths == (keep,) and not scan.too_many
    explicit = scan_image_folder(arc.archive_root(output), skip=())
    assert [path.name for path in explicit.paths] == [
        "moved.png"
    ]  # opening the archive on purpose still works


def test_review_folder_scan_default_skip_is_the_configured_archive(output, monkeypatch):
    keep = image_file(output / "run" / "keep.png", 1)
    moved = image_file(output / "run" / "moved.png", 2)
    _archive(moved, output)
    monkeypatch.chdir(output.parent)  # the default output root ("output") is then this temp root

    assert scan_image_folder(output).paths == (keep,)


def test_the_archived_files_do_not_count_toward_the_folder_limit(output):
    image_file(output / "run" / "a.png", 1)
    moved = image_file(output / "run" / "b.png", 2)
    _archive(moved, output)
    scan = scan_image_folder(output, limit=1, skip=(arc.archive_root(output),))
    assert not scan.too_many and len(scan.paths) == 1


def test_learning_output_scan_skips_the_archive(output, monkeypatch):
    live = image_file(output / "Pipeline" / "run" / "live.png", 1)
    moved = image_file(output / "Pipeline" / "run" / "moved.png", 2)
    _archive(moved, output)
    manifest = output / "Pipeline" / "run" / "manifests" / "live.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    archived_manifest = arc.archive_root(output) / "Pipeline" / "run" / "manifests" / "stray.json"
    archived_manifest.parent.mkdir(parents=True)
    archived_manifest.write_text("{}", encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(
        output_scanner, "_record_from_embedded", lambda path: seen.append(path) or None
    )

    scanner = OutputScanner(output)
    scanner.scan_full()
    scanner.scan_incremental()

    assert seen == [live]
    assert all(arc.ARCHIVE_DIR_NAME not in str(key) for key in scanner.get_updated_index())


def test_output_run_dir_enumeration_skips_the_archive_but_lists_everything_else(output):
    (output / "Pipeline" / "run_a").mkdir(parents=True)
    (output / "loose_run").mkdir()
    image = image_file(output / "loose_run" / "a.png", 1)
    _archive(image, output)

    names = sorted(path.name for path in iter_output_run_dirs(output))

    assert names == ["loose_run", "run_a"]
    assert "_archive" not in names


def test_the_archive_folder_is_not_an_output_route():
    from src.state.output_routing import ARCHIVE_DIR_NAME, KNOWN_OUTPUT_ROUTE_DIRS

    assert ARCHIVE_DIR_NAME not in KNOWN_OUTPUT_ROUTE_DIRS
