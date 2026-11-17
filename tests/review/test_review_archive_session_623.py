"""PR-REVIEW-ARCHIVE-623: the Review workspace session over real moves (Tk-free, temporary roots, inline worker).

Discard moves the file on the worker, Undo / Restore / Retain move it back, a refusal keeps the item discarded with the
reason, and every state is re-derived from the file system and the evidence rows (item key and lookup by original
path and digest).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.controller.app_controller_services.background_task_coordinator import (
    BackgroundTaskCoordinator,
)
from src.gui.view_contracts.edit_work_runner import EditWorkRunner
from src.gui.view_contracts.review_workspace_contract import (
    LOC_ARCHIVED,
    LOC_IN_PLACE,
    ItemState,
    ReviewWorkspaceSession,
    ViewFilter,
    item_key,
)
from src.learning.learning_record import LearningRecordWriter
from src.review import archive as arc
from src.review.review_evidence import (
    build_review_rating_record,
    lookup_disposition,
    save_disposition,
)
from tests.gui_v2.edit_work_helpers import ManualRegistry, manual_runner
from tests.helpers.batch_ops_201 import image_file


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inline() -> EditWorkRunner:
    return EditWorkRunner(BackgroundTaskCoordinator(run_inline=True), is_alive=lambda: True)


class Archiving:
    """A session wired to the real archive functions, as the Review tab wires it."""

    def __init__(self, tmp_path: Path, *, runner=None, count: int = 3, busy=None):
        self.output = tmp_path / "output"
        self.writer = LearningRecordWriter(tmp_path / "records.jsonl")
        self.images = [
            image_file(self.output / "Pipeline" / "run" / f"img_{i}.png", i + 1)
            for i in range(count)
        ]
        self.busy: set[str] = busy if busy is not None else set()
        self.session = self.new_session(runner or _inline())

    def _write(self, path, digest, job_id, disposition):
        save_disposition(
            self.writer,
            image_path=path,
            disposition=disposition,
            artifact_sha256=digest or None,
            source_job_id=job_id,
        )

    def new_session(self, runner) -> ReviewWorkspaceSession:
        return ReviewWorkspaceSession(
            runner=runner,
            records_path=lambda: self.writer.records_path,
            write_disposition=self._write,
            output_root=lambda: self.output,
            archive=lambda path, _digest: arc.archive_file(
                path,
                output_root=self.output,
                active_inputs=lambda: self.busy,
                protected_roots=(),
            ),
            restore=lambda path, digest, alternative: arc.restore_file(
                path, output_root=self.output, digest=digest or None, use_alternative=alternative
            ),
        )

    def key(self, index: int) -> str:
        return item_key(self.images[index])

    def where(self, index: int) -> Path:
        return arc.mirror_target(self.images[index], self.output)


@pytest.fixture
def lab(tmp_path):
    return Archiving(tmp_path)


def test_discard_moves_the_file_and_the_decision_still_resolves_by_digest(lab):
    session, image = lab.session, lab.images[0]
    digest = _sha(image)
    session.set_items(lab.images)

    assert session.decide(lab.key(0), "discard")

    assert not image.exists() and _sha(lab.where(0)) == digest
    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED
    assert session.facts_of(lab.key(0)).location == LOC_ARCHIVED
    assert "moved to the archive" in session.message
    assert lookup_disposition(lab.writer.records_path, image, digest).identity == "digest"

    session.refresh()  # re-derived from disk: the digest is read from the archived copy
    facts = session.facts_of(lab.key(0))
    assert facts.digest == digest and facts.location == LOC_ARCHIVED and facts.identity == "digest"
    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED
    assert session.row_text(session.items[0]).startswith("[Archived] img_0.png (in archive)")


def test_a_saved_rating_still_resolves_by_digest_while_the_file_is_archived(lab):
    session, image = lab.session, lab.images[0]
    digest = _sha(image)
    lab.writer.append_record(
        build_review_rating_record({"image_path": str(image), "rating": 4}, artifact_sha256=digest)
    )
    session.set_items(lab.images)
    assert session.facts_of(lab.key(0)).rating == 4

    session.decide(lab.key(0), "discard")
    assert not image.exists()
    session.refresh()

    facts = session.facts_of(lab.key(0))
    assert facts.rating == 4 and facts.digest == digest
    assert session.restore(lab.key(0))
    assert image.exists() and session.facts_of(lab.key(0)).rating == 4


def test_undo_and_restore_return_the_file_with_identical_bytes(lab):
    session = lab.session
    digests = [_sha(path) for path in lab.images]
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    session.decide(lab.key(1), "discard")
    assert not lab.images[0].exists() and not lab.images[1].exists()

    assert session.undo()  # the last discard (image 1)
    assert lab.images[1].exists() and _sha(lab.images[1]) == digests[1]
    assert session.state_of(lab.key(1)) is ItemState.TO_REVIEW
    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED

    assert session.restore(lab.key(0))
    assert lab.images[0].exists() and _sha(lab.images[0]) == digests[0]
    assert session.state_of(lab.key(0)) is ItemState.TO_REVIEW
    assert not lab.where(0).exists() and not lab.where(1).exists()

    session.refresh()
    assert session.facts_of(lab.key(0)).location == LOC_IN_PLACE


def test_retain_and_rework_on_an_archived_image_put_the_file_back_first(lab):
    session = lab.session
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    assert session.decide(lab.key(0), "retain")
    assert lab.images[0].exists() and session.state_of(lab.key(0)) is ItemState.RETAINED
    session.decide(lab.key(1), "discard")
    assert session.decide(lab.key(1), "rework")
    assert lab.images[1].exists() and session.state_of(lab.key(1)) is ItemState.REWORK_MARKED


def test_a_refusal_keeps_the_item_discarded_in_place_with_the_reason_and_retry_works(lab):
    session, image = lab.session, lab.images[0]
    lab.busy.add(str(image))
    session.set_items(lab.images)

    session.decide(lab.key(0), "discard")

    assert image.exists()  # a queued job still needs it
    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED
    assert session.facts_of(lab.key(0)).location == LOC_IN_PLACE
    assert "not moved" in session.message and "queued or running job" in session.message
    assert "(not moved)" in session.row_text(session.items[0])
    assert "queued or running job" in session.archive_line(lab.key(0))
    assert "Discard again" in session.archive_line(lab.key(0))

    lab.busy.clear()  # the job finished
    assert session.decide(lab.key(0), "discard")  # retry
    assert not image.exists() and lab.where(0).exists()
    assert session.facts_of(lab.key(0)).location == LOC_ARCHIVED
    assert lab.key(0) not in session.archive_notes


def test_restoring_or_undoing_a_discard_that_never_moved_just_clears_it(lab):
    session = lab.session
    lab.busy.add(str(lab.images[0]))
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    assert session.undo()
    assert lab.images[0].exists() and session.state_of(lab.key(0)) is ItemState.TO_REVIEW


def test_restore_is_refused_when_a_different_file_took_the_original_path(lab):
    session = lab.session
    original_digest = _sha(lab.images[0])
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    squatter = image_file(lab.images[0], 99)  # a new, different file at the original path
    squatter_digest = _sha(squatter)

    assert session.restore(lab.key(0))

    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED  # nothing was recorded
    assert "different file" in session.message and "new name" in session.message
    assert _sha(squatter) == squatter_digest and lab.where(0).exists()
    offer = session.take_restore_offer()
    assert offer is not None and offer.key == lab.key(0) and not offer.alternative.exists()
    assert session.take_restore_offer() is None

    assert session.restore(lab.key(0), use_alternative=True)
    assert _sha(offer.alternative) == original_digest and _sha(squatter) == squatter_digest
    assert not lab.where(0).exists()
    assert session.item(item_key(offer.alternative)) is not None  # the restored file joins the set


def test_a_blocked_undo_keeps_its_entry_so_it_can_be_retried(lab):
    session = lab.session
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    image_file(lab.images[0], 77)  # takes the original path
    assert session.undo()
    assert session.state_of(lab.key(0)) is ItemState.ARCHIVED and session.can_undo
    lab.images[0].unlink()
    assert session.undo()
    assert lab.images[0].exists() and session.state_of(lab.key(0)) is ItemState.TO_REVIEW


def test_discarding_several_images_moves_each_once(lab):
    session = lab.session
    session.set_items(lab.images)
    assert session.decide_many([lab.key(0), lab.key(1), lab.key(0)], "discard") == 2
    assert [path.exists() for path in lab.images] == [False, False, True]
    assert all(lab.where(i).exists() for i in (0, 1))
    assert len(lab.writer.records_path.read_text(encoding="utf-8").splitlines()) == 2


def test_the_archived_filter_lists_archived_images_from_records_after_a_restart(lab):
    first = lab.session
    first.set_items(lab.images)
    first.decide(lab.key(0), "discard")
    first.decide(lab.key(2), "discard")
    lab.busy.add(str(lab.images[1]))
    first.decide(lab.key(1), "discard")  # refused: stays in place
    assert lab.images[1].exists()

    # A new process opens the folder: the scan lists only what is still there.
    scanned = [path for path in lab.images if path.exists()]
    second = lab.new_session(_inline())
    second.set_items(scanned, folder=lab.output)
    second.set_filter(ViewFilter.ARCHIVED)

    names = [item.name for item in second.visible_items()]
    assert sorted(names) == ["img_0.png", "img_1.png", "img_2.png"]
    rows = {item.name: second.row_text(item) for item in second.visible_items()}
    assert "(in archive)" in rows["img_0.png"] and "(in archive)" in rows["img_2.png"]
    assert "(not moved)" in rows["img_1.png"]
    assert second.counts_text().endswith("Archived 3")
    assert "in the archive folder" in second.archive_line(lab.key(0))


def test_a_file_restored_by_hand_is_not_listed_twice(lab):
    first = lab.session
    first.set_items(lab.images)
    first.decide(lab.key(0), "discard")
    arc.restore_file(lab.images[0], output_root=lab.output)  # put back outside Review
    second = lab.new_session(_inline())
    second.set_items([p for p in lab.images if p.exists()], folder=lab.output)
    assert [item.name for item in second.items].count("img_0.png") == 1
    assert second.facts_of(lab.key(0)).location == LOC_IN_PLACE


def test_archived_images_outside_the_opened_folder_are_not_listed(lab, tmp_path):
    lab.session.set_items(lab.images)
    lab.session.decide(lab.key(0), "discard")
    other = tmp_path / "other_folder"
    other.mkdir()
    second = lab.new_session(_inline())
    second.set_items([], folder=other)
    assert second.items == []


def test_a_refresh_that_began_before_the_move_does_not_undo_the_location(tmp_path):
    registry = ManualRegistry()
    lab = Archiving(tmp_path, runner=manual_runner(registry))
    session = lab.session
    session.set_items(lab.images)
    registry.run_all()
    session.refresh()  # begins now; its worker has not run yet
    session.decide(lab.key(0), "discard")
    registry.run_next()  # the refresh reads the disk first (file still in place)...
    registry.run_all()  # ...then the discard moves it and records it

    assert not lab.images[0].exists()
    facts = session.facts_of(lab.key(0))
    assert facts.disposition == "discard" and facts.location == LOC_ARCHIVED


def test_the_session_without_archive_functions_stays_logical(tmp_path):
    output = tmp_path / "output"
    image = image_file(output / "a.png")
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    session = ReviewWorkspaceSession(
        runner=_inline(),
        records_path=lambda: writer.records_path,
        write_disposition=lambda path, digest, job, disposition: save_disposition(
            writer,
            image_path=path,
            disposition=disposition,
            artifact_sha256=digest or None,
            source_job_id=job,
        ),
    )
    session.set_items([image])
    session.decide(item_key(image), "discard")
    assert image.exists() and session.state_of(item_key(image)) is ItemState.ARCHIVED
    assert session.archive_line(item_key(image)) == ""
    assert session.row_text(session.items[0]) == "[Archived] a.png"


def test_status_text_never_contains_prompt_text(lab):
    session = lab.session
    lab.busy.add(str(lab.images[0]))
    session.set_items(lab.images)
    session.decide(lab.key(0), "discard")
    text = " ".join([session.message, session.archive_line(lab.key(0))]).lower()
    assert "prompt" not in text
