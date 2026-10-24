"""Both GUI transports admit compiled optimizer policy through JobService/SQLite."""

import pytest

from tests.controller.test_matrix_preview_admission_560 import Harness


@pytest.mark.parametrize("transport", ["send_job", "run_now"])
@pytest.mark.parametrize("accepted_preview", [False, True])
def test_send_and_run_now_preserve_compiled_optimizer_policy(tmp_path, transport, accepted_preview):
    harness = Harness(tmp_path, {"enabled": False, "slots": []})
    selected = {
        "enabled": False,
        "dedupe_enabled": False,
        "preserve_lora_relative_order": False,
        "opt_out_pipeline_names": ["adetailer"],
    }
    harness.config_manager._config["prompt_optimizer"] = selected
    harness.app_state.add_packs_to_job_draft([harness.entry()])
    if accepted_preview:
        harness.app_state.set_preview_jobs(harness._compile())
    if transport == "send_job":
        assert harness.controller.submit_preview_jobs_to_queue() == 1
    else:
        assert harness.controller._submit_preview_jobs_for_run(
            run_mode="queue",
            source="run_now_button",
            prompt_source="pack",
            prompt_pack_id=None,
        )
    [preview] = harness.app_state.preview_jobs
    [queued] = harness.queued()
    assert harness.compiles == 1
    for record in (preview, queued):
        for key, value in selected.items():
            assert record.config["prompt_optimizer"][key] == value
    assert preview.positive_prompt == queued.positive_prompt
    assert preview.negative_prompt == queued.negative_prompt
    selected["enabled"] = True
    assert queued.config["prompt_optimizer"]["enabled"] is False


def test_send_job_dispatches_the_already_compiled_record_without_recompilation(tmp_path):
    from tests.controller.test_app_controller_queue_control_150 import _Stack

    (tmp_path / "compile").mkdir()
    (tmp_path / "send").mkdir()
    harness = Harness(tmp_path / "compile", {"enabled": False, "slots": []})
    harness.config_manager._config["prompt_optimizer"] = {"enabled": False, "dedupe_enabled": False}
    [record] = harness.accept_preview()
    stack = _Stack(tmp_path / "send", auto_run=False)
    try:
        ids = stack.service.submit_njrs([record])
        # Send Job operates on the durable queue; later editor changes do not compile again.
        harness.config_manager._config["prompt_optimizer"]["enabled"] = True
        assert stack.controller.on_queue_send_job_v2() is True
        stack.wait_until(lambda: stack.executed == ids)
        [stored] = stack.repository.list_job_models()
        assert stored._normalized_record.config["prompt_optimizer"]["enabled"] is False
        assert harness.compiles == 1
    finally:
        stack.close()
