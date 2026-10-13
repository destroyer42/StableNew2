"""PR-QUEUE-GPU-180: the Batches view names the hold that is actually in force (WebUI outage vs GPU quarantine).

The ``stack`` has a video batch (``vid``, independent of the WebUI: native/Comfy video) with five queued jobs and a
Review image batch (``rev``, WebUI-dependent) with six.
"""
from __future__ import annotations

import pytest

from tests.gui_v2.test_batch_operations_session_201 import REV, VID, loaded
from tests.helpers.batch_ops_201 import admit, make_stack, review_njr, settle_fifo, video_njr

INCIDENT = {"incident_id": "gpu-labels-1", "evidence_class": "confirmed_device_loss"}


@pytest.fixture
def stack(tmp_path):
    stack = make_stack(tmp_path)
    admit(stack, [video_njr(f"v{i:02d}", "vid", i, 10) for i in range(10)])
    admit(stack, [review_njr(f"r{i}", "rev", source_count=6) for i in range(6)])
    settle_fifo(stack, count=5)  # v00..v04 finish; v05..v09 and r0..r5 stay queued
    return stack


def _notes(session):
    return {row.token: row.note for row in session.batch_rows()}


def _queued_statuses(session):
    return [row.status for row in session.job_rows() if row.status.startswith("QUEUED")]


def test_gpu_quarantine_is_labelled_as_gpu_not_as_a_webui_outage(stack):
    assert stack.queue.quarantine_gpu_dispatch(INCIDENT)
    session, _runner, _recorder = loaded(stack, VID)
    notes = _notes(session)
    # Video is independent of the WebUI but not of the GPU, so both batches are held by the quarantine.
    assert notes[VID.to_token()] == "5 held (GPU quarantine)"
    assert notes[REV.to_token()] == "6 held (GPU quarantine)"
    assert all("WebUI" not in note for note in notes.values())
    statuses = _queued_statuses(session)
    assert statuses and all(status == "QUEUED (held - GPU)" for status in statuses)
    summary = session.summary_text()
    assert "held by a GPU device-loss quarantine" in summary and "WebUI outage" not in summary


def test_webui_hold_keeps_its_original_labels(stack):
    assert stack.queue.hold_webui_dispatch(reason="webui_down", incident_id="webui-1")
    session, _runner, _recorder = loaded(stack, REV)
    notes = _notes(session)
    assert notes[REV.to_token()] == "6 held (WebUI)"
    assert notes[VID.to_token()] == ""  # independent video is not held by a WebUI outage
    statuses = _queued_statuses(session)
    assert statuses and all(status == "QUEUED (held)" for status in statuses)
    assert "held by a WebUI outage" in session.summary_text()


def test_both_holds_name_both_sources(stack):
    stack.queue.hold_webui_dispatch(reason="webui_down", incident_id="webui-1")
    stack.queue.quarantine_gpu_dispatch(INCIDENT)
    session, _runner, _recorder = loaded(stack, REV)
    notes = _notes(session)
    assert "6 held (GPU quarantine)" in notes[REV.to_token()] and "6 held (WebUI)" in notes[REV.to_token()]
    assert notes[VID.to_token()] == "5 held (GPU quarantine)"
    summary = session.summary_text()
    assert "WebUI outage" in summary and "GPU device-loss quarantine" in summary


def test_queue_reports_the_hold_source_per_job(stack):
    stack.queue.quarantine_gpu_dispatch(INCIDENT)
    assert stack.queue.is_job_held_by_gpu_loss("v05") and stack.queue.is_job_held("v05")
    assert not stack.queue.is_job_held_by_webui("v05")  # video: independent of the WebUI
    stack.queue.release_gpu_quarantine()
    stack.queue.hold_webui_dispatch(reason="webui_down", incident_id="webui-1")
    assert stack.queue.is_job_held_by_webui("r0") and not stack.queue.is_job_held_by_gpu_loss("r0")
    assert not stack.queue.is_job_held_by_webui("v05")
    assert not stack.queue.is_job_held_by_gpu_loss("no-such-job")
