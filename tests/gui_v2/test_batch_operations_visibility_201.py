"""PR-BATCH-OPS-201: the Batches view honours the same SFW/content-visibility policy as History."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.controller.batch_operations_service import build_batch_operations_service
from src.controller.content_visibility_resolver import REDACTED_TEXT
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.gui.gui_invoker import GuiInvoker
from src.gui.view_contracts.batch_operations_contract import BatchOperationsSession
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.queue.batch_membership import BatchKey, BatchKind
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager
from src.utils.watchdog_v2 import WatchdogConfig
from tests.gui_v2.test_batch_operations_session_201 import ManualRunner, Recorder
from tests.helpers.batch_ops_201 import admit, image_file, make_stack, review_njr
from tests.helpers.fake_pipeline_runner import FakePipelineRunner

KEY = BatchKey(BatchKind.REVIEW, "vis")


def _failed(message):
    return {"success": False, "error": message, "metadata": {"failure_evidence": {
        "contract": "webui_failure_evidence/1", "error_code": "connection_error",
        "webui_unavailable": True, "stage": "img2img"}}}


@pytest.fixture
def world(tmp_path):
    stack = make_stack(tmp_path)
    explicit_out = image_file(tmp_path / "out" / "result_a.png", 1)
    plain_out = image_file(tmp_path / "out" / "result_b.png", 2)
    admit(stack, [
        review_njr("v0", "vis", source=tmp_path / "s0.png", source_count=3, prompt="a nude portrait"),
        review_njr("v1", "vis", source=tmp_path / "s1.png", source_count=3, prompt="a mountain landscape"),
        review_njr("v2", "vis", source=tmp_path / "s2.png", source_count=3, prompt="a mountain landscape"),
    ])
    for job_id, message, out in ([
        ("v0", "backend refused: nude portrait payload", explicit_out),
        ("v1", "prompt echo: explicit adult scene rejected", plain_out),
        ("v2", "plain failure", None),
    ]):
        job = stack.queue.claim_next_job()
        assert job.job_id == job_id
        stack.queue.publish_result(
            job_id, status=__import__("src.queue.job_model", fromlist=["JobStatus"]).JobStatus.FAILED,
            result={**_failed(message), "variants": [{"stage": "img2img", "path": str(out)}] if out else [],
                    "metadata": {**_failed(message)["metadata"],
                                 **({"completed_output_paths": [str(out)]} if out else {})}},
            stage_checkpoints=[], error_message=message)
    return stack, explicit_out, plain_out


def _session(stack, mode):
    runner, recorder = ManualRunner(), Recorder()
    session = BatchOperationsSession(
        service=stack.operations, runner=runner, hooks=recorder.hooks(),
        on_change=lambda: None, visibility_mode=lambda: mode["value"])
    session.refresh()
    runner.drain()
    session.select_batch(KEY)
    runner.drain()
    return session, runner, recorder


def test_nsfw_mode_shows_everything_unchanged(world):
    stack, explicit_out, _ = world
    session, _, _ = _session(stack, {"value": "nsfw"})
    session.set_job_selection(["v0"])
    text = session.detail_text()
    assert "s0.png" in text and "nude portrait payload" in text and explicit_out.name in text
    assert [row.source for row in session.job_rows()] == ["s0.png", "s1.png", "s2.png"]


def test_sfw_mode_hides_a_job_the_policy_hides_but_keeps_counts_and_status_truthful(world):
    stack, explicit_out, _ = world
    session, _, _ = _session(stack, {"value": "sfw"})
    rows = {row.job_id: row for row in session.job_rows()}
    assert rows["v0"].source == REDACTED_TEXT and rows["v0"].model == REDACTED_TEXT and rows["v0"].outputs == "hidden"
    assert rows["v1"].source == "s1.png" and rows["v0"].status == "FAILED"
    assert session.detail.job_count == 3 and session.detail.counts.failed == 3  # structure is not falsified
    session.set_job_selection(["v0"])
    text = session.detail_text()
    assert "Content hidden in SFW mode" in text and "FAILED" in text and "Backend unavailable" in text
    assert "s0.png" not in text and "nude" not in text and explicit_out.name not in text
    assert "Message:" not in text


def test_sfw_mode_redacts_an_explicit_failure_message_of_an_otherwise_visible_job(world):
    stack, _, _ = world
    session, _, _ = _session(stack, {"value": "sfw"})
    session.set_job_selection(["v1"])
    text = session.detail_text()
    assert "s1.png" in text  # the job itself is visible ...
    assert f"Message: {REDACTED_TEXT}" in text and "explicit adult" not in text  # ... its echoed message is not
    session.set_job_selection(["v2"])
    assert "Message: plain failure" in session.detail_text()


def test_sfw_mode_never_opens_hidden_outputs(world):
    stack, explicit_out, plain_out = world
    session, runner, recorder = _session(stack, {"value": "sfw"})
    session.set_job_selection(["v0"])
    assert not session.review_state().enabled and "hidden in SFW mode" in session.review_state().reason
    assert not session.folder_state().enabled
    session.set_job_selection(["v0", "v1"])
    assert session.review_state().enabled
    session.open_outputs("review")
    runner.drain()
    assert recorder.reviewed == [(str(plain_out),)]  # the hidden job's image never reaches Review
    assert str(explicit_out) not in str(recorder.reviewed)


def test_sfw_mode_redacts_the_retry_review_but_not_its_substance(world):
    stack, _, _ = world
    session, runner, recorder = _session(stack, {"value": "sfw"})
    recorder.retry_answer = None
    session.set_job_selection(["v0", "v1"])
    session.retry_selected()
    runner.drain()
    shown = recorder.retry_plans[0]
    by_id = {item.job_id: item for item in shown.items}
    assert by_id["v0"].source_label == REDACTED_TEXT and by_id["v1"].source_label == "s1.png"
    assert all(item.eligible == (not item.reasons) for item in shown.items)
    assert shown.token and shown.key == KEY


def test_session_messages_never_carry_explicit_text_in_sfw_mode(world):
    stack, _, _ = world
    mode = {"value": "sfw"}
    session, _, _ = _session(stack, mode)
    session._say("Retry failed: nude_study.png is missing")
    assert session.message == REDACTED_TEXT
    mode["value"] = "nsfw"
    session._say("Retry failed: nude_study.png is missing")
    assert "nude_study.png" in session.message


def test_toggling_the_mode_changes_what_is_derived_without_a_reload(world):
    stack, _, _ = world
    mode = {"value": "nsfw"}
    changes = []
    runner = ManualRunner()
    session = BatchOperationsSession(service=stack.operations, runner=runner, on_change=lambda: changes.append(1),
                                     visibility_mode=lambda: mode["value"])
    session.refresh()
    runner.drain()
    session.select_batch(KEY)
    runner.drain()
    before = session.job_rows()
    mode["value"] = "sfw"
    count = len(changes)
    session.notify_visibility_changed()
    assert len(changes) == count + 1 and session.job_rows() != before


@pytest.mark.gui
def test_the_real_tab_rerenders_when_the_global_mode_toggles(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(PipelineTabFrame, "_surface_is_visible", staticmethod(lambda _w: True))
    repository = JobRepository(tmp_path / "tab.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, run_callable=lambda job: {"success": True},
                         watchdog_config=WatchdogConfig(enabled=False))
    admit(SimpleNamespace(service=service), [
        review_njr("t0", "vis", source=tmp_path / "x.png", source_count=1, prompt="a nude portrait")])
    app_state = AppStateV2()
    invoker = GuiInvoker(tk_root)
    controller = AppController(
        main_window=None, threaded=False, ui_scheduler=invoker.invoke,
        pipeline_runner=FakePipelineRunner(), job_service=service,
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"))
    controller.load_packs = lambda: None  # type: ignore[method-assign]
    tab = PipelineTabFrame(tk_root, app_state=app_state, app_controller=controller,
                           pipeline_controller=controller.pipeline_controller)
    tab.pack()
    try:
        panel, runner = tab.batches_panel, ManualRunner()
        panel.session._runner = runner
        panel.refresh()
        runner.drain()
        panel.session.select_batch(KEY)
        runner.drain()
        tk_root.update()
        assert panel.job_tree.item("t0", "values")[1] == "x.png"
        app_state.set_content_visibility_mode("sfw")
        tk_root.update()
        assert panel.job_tree.item("t0", "values")[1] == REDACTED_TEXT
        app_state.set_content_visibility_mode("nsfw")
        tk_root.update()
        assert panel.job_tree.item("t0", "values")[1] == "x.png"
        assert build_batch_operations_service(controller) is not None
    finally:
        tab.destroy()
        invoker.dispose()
        service.stop()
        repository.close()


# ------------------------------------------------------------------ independent-review regressions (S1-S4)


def test_a_message_written_before_the_toggle_is_redacted_when_the_mode_becomes_sfw(world):
    stack, explicit_out, _ = world
    mode = {"value": "nsfw"}
    session, _, _ = _session(stack, mode)
    session._say(f"Opened {explicit_out.parent}.")  # e.g. an Open Output Folder result for hidden-in-SFW v0
    assert str(explicit_out.parent) in session.message
    mode["value"] = "sfw"
    session.notify_visibility_changed()
    assert session.message == REDACTED_TEXT  # re-derived at read time, not frozen at write time
    mode["value"] = "nsfw"
    assert str(explicit_out.parent) in session.message


def test_service_refusals_that_name_a_hidden_job_are_redacted_even_with_innocuous_file_names(world):
    stack, _, _ = world
    stack_dir = stack.path.parent
    image_file(stack_dir / "s0.png", 3)  # v0's source now exists, so the retry plan is eligible
    mode = {"value": "sfw"}
    session, runner, recorder = _session(stack, mode)
    session.set_job_selection(["v0"])
    recorder.retry_answer = ()
    assert session.retry_selected()
    outcome, done = runner.run()
    done(outcome)  # the review dialog was accepted; the submit worker is queued
    (stack_dir / "s0.png").unlink()  # the source disappears before admission
    runner.drain()
    assert "s0.png" not in session.message and session.message == REDACTED_TEXT
    mode["value"] = "nsfw"
    assert "s0.png" in session.message  # the same raw text is shown when the policy allows it


def test_an_outputs_completion_that_lands_after_switching_to_sfw_hands_nothing_off(world):
    stack, explicit_out, _ = world
    mode = {"value": "nsfw"}
    session, runner, recorder = _session(stack, mode)
    session.set_job_selection(["v0"])
    assert session.open_outputs("review")
    mode["value"] = "sfw"  # toggled while the worker was resolving
    runner.drain()
    assert recorder.reviewed == [] and "display mode changed" in session.message
    assert str(explicit_out) not in session.message


def test_a_job_under_a_hidden_directory_is_hidden_even_with_a_clean_prompt_and_file_name(tmp_path):
    stack = make_stack(tmp_path)
    admit(stack, [review_njr("d0", "vis", source=tmp_path / "nude" / "IMG1.png", source_count=1,
                             prompt="a mountain landscape")])
    mode = {"value": "sfw"}
    session, _, _ = _session(stack, mode)
    assert session.job_rows()[0].source == REDACTED_TEXT
