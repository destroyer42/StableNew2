"""Prompt-tab operator journey with controllable synthetic completion; no model/process/network."""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai_assist.contracts import SUGGESTION_SCHEMA_ID, AssistOutcome, OutcomeCode, SuggestionKind
from src.ai_assist.service import Submission
from src.ai_assist.status import STATE_READY, AiAssistStatus
from src.ai_assist.validators import validate_output
from src.controller.app_controller_services.ai_assist_integration import AiAssistIntegration
from src.gui.app_state_v2 import AppStateV2
from src.gui.views.prompt_tab_frame_v2 import PromptTabFrame
from src.gui_v2.ai_suggestion_view import OUTCOME_TEXT
from tests.gui_v2.test_prompt_target_130b import KLEIN, SDXL, _projection, _resolver

pytestmark = pytest.mark.gui


class ControlledService:
    def __init__(self):
        self.requests = []
        self.callbacks = []
        self.cancelled = []
        self.closed = False

    def submit(self, request, done):
        self.requests.append(request)
        self.callbacks.append(done)
        return Submission(True)

    def cancel(self, request_id):
        self.cancelled.append(request_id)
        return True

    def begin_shutdown(self):
        self.closed = True

    def shutdown(self, _timeout):
        return True


@pytest.fixture
def journey(tk_root, tmp_path):
    state = AppStateV2()
    frame = PromptTabFrame(tk_root, app_state=state, packs_dir=tmp_path / "packs")
    frame.target_lora_resolver = _resolver({})
    frame.workspace_state.set_slot_text(0, "a red barn <lora:kept:0.8> [[season]]")
    frame.workspace_state.set_slot_negative(0, "blurry")
    frame._refresh_editor()
    frame.on_model_projection(_projection(SDXL))
    frame.workspace_state.dirty = False
    scheduled = []
    owner = AiAssistIntegration(lambda: None, scheduled.append, root=tmp_path / "ai")
    service = ControlledService()
    owner.service = service
    owner.status = lambda: AiAssistStatus(STATE_READY, "Synthetic ready", egress="attested")
    targets = [(SDXL, "SDXL"), (KLEIN, "Klein")]
    flow = frame.ai_suggestions
    flow.bind(owner, targets=lambda: tuple(targets))
    bundle = SimpleNamespace(
        frame=frame,
        flow=flow,
        state=state,
        owner=owner,
        service=service,
        targets=targets,
        scheduled=scheduled,
        root=tk_root,
    )
    yield bundle
    flow.destroy()
    owner.shutdown()
    if frame.winfo_exists():
        frame.destroy()


def start(j, kind=SuggestionKind.PROMPT_REWRITE):
    dialog = j.flow.open()
    assert dialog is not None
    j.flow.request(kind)
    assert j.service.requests
    return dialog


def successful(j, *, positive=None, negative="less blur", target=None, workflow=None):
    request = j.service.requests[-1]
    doc = {
        "schema": SUGGESTION_SCHEMA_ID,
        "status": "ok",
        "kind": request.kind.value,
        "changes": ["clarified_wording"],
    }
    if request.kind is SuggestionKind.PROMPT_REWRITE:
        doc.update(
            positive=positive or request.positive_text.replace("red", "crimson"), negative=negative
        )
    elif request.kind is SuggestionKind.TARGET_FIT_ADVICE:
        doc["target"] = target or KLEIN
    else:
        doc["workflow"] = workflow
    validated = validate_output(json.dumps(doc), request)
    assert validated.suggestion is not None
    return AssistOutcome(
        OutcomeCode.SUGGESTION, request.request_id, suggestion=validated.suggestion
    )


def finish(j, outcome=None):
    j.service.callbacks[-1](outcome or successful(j))
    assert j.scheduled
    j.scheduled.pop(0)()


def test_missing_installation_journey_has_discoverable_disabled_action_and_no_submit(journey):
    j = journey
    j.owner.status = lambda: AiAssistStatus("not_installed", "No qualified installation")
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    j.flow.refresh()
    assert j.flow.button.cget("text") == "Suggest…"
    assert j.flow.button.master is j.frame.adapt_button.master
    assert j.flow.button.instate(["disabled"])
    assert "qualified" in j.flow.explanation.cget("text")
    assert j.flow.open() is None
    j.flow.button.invoke()
    assert not j.service.requests
    assert j.frame.workspace_state.current_pack == before and not j.frame.workspace_state.dirty


def test_accept_edits_only_authored_fields_refreshes_and_invalidates_preview(journey):
    j = journey
    slot = j.frame.workspace_state.get_current_slot()
    slot.loras = [("operator_lora", 0.7)]
    slot.positive_embeddings = [("embedding", 0.8)]
    original = copy.deepcopy(j.frame.workspace_state.current_pack)
    revision = j.state.preview_revision
    dialog = start(j)
    assert dialog.cancel_button.instate(["!disabled"])
    finish(j)
    assert j.frame.workspace_state.current_pack == original and not j.frame.workspace_state.dirty
    assert dialog.accept_button.instate(["!disabled"])
    assert "Deterministic target compatibility" in dialog.preview.get("1.0", "end")
    j.flow.accept()
    assert slot.text == "a crimson barn <lora:kept:0.8> [[season]]"
    assert slot.negative == "less blur"
    assert (
        slot.loras == original.slots[0].loras
        and slot.positive_embeddings == original.slots[0].positive_embeddings
    )
    assert j.frame.workspace_state.dirty and j.state.preview_revision > revision
    assert j.frame.editor.get("1.0", "end-1c") == slot.text
    assert not list(j.frame._packs_dir.glob("*.json"))
    after_revision = j.state.preview_revision
    j.flow.accept()
    assert j.state.preview_revision == after_revision


def test_reject_and_close_never_apply_or_save(journey):
    j = journey
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    dialog = start(j)
    finish(j)
    dialog.close()
    assert j.frame.workspace_state.current_pack == before and not j.frame.workspace_state.dirty
    j.flow.accept()
    assert j.frame.workspace_state.current_pack == before


@pytest.mark.parametrize(
    "change",
    [
        "pack",
        "slot",
        "positive",
        "negative",
        "template",
        "matrix",
        "target",
        "choices",
        "pending-widget",
    ],
)
def test_changed_material_invalidates_acceptance(journey, change):
    j = journey
    dialog = start(j)
    finish(j)
    ws = j.frame.workspace_state
    if change == "pack":
        ws.current_pack = copy.deepcopy(ws.current_pack)
    elif change == "slot":
        ws.set_current_slot_index(1)
    elif change == "positive":
        ws.set_slot_text(0, "new operator content")
    elif change == "negative":
        ws.set_slot_negative(0, "new negative")
    elif change == "template":
        ws.get_slot(0).template_variables["subject"] = "new template content"
    elif change == "matrix":
        ws.current_pack.matrix.limit += 1
    elif change == "target":
        j.frame.on_model_projection(_projection(KLEIN))
    elif change == "choices":
        j.targets.pop()
    else:
        j.frame.editor.insert("end", " unsynchronized newer edit")
    before = copy.deepcopy(ws.current_pack)
    j.flow.accept()
    assert ws.current_pack == before
    assert dialog.accept_button.instate(["disabled"])
    assert not dialog.preview.get("1.0", "end").strip()


def test_template_rewrite_is_disabled_and_authored_material_never_flattened(journey):
    j = journey
    j.frame.workspace_state.get_slot(0).template_id = "structured-template"
    dialog = j.flow.open()
    rewrite = dialog._requests[0][0]
    assert rewrite.instate(["disabled"])
    j.flow.request(SuggestionKind.PROMPT_REWRITE)
    assert not j.service.requests
    assert "structured templates" in dialog.status_var.get()


def test_advice_is_closed_list_and_cannot_change_model_or_authoring(journey):
    j = journey
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    dialog = start(j, SuggestionKind.TARGET_FIT_ADVICE)
    finish(j)
    assert KLEIN in dialog.preview.get("1.0", "end")
    assert dialog.accept_button.instate(["disabled"])
    assert "Advice only" in dialog.status_var.get()
    j.flow.accept()
    assert j.frame._model_projection.model_name == SDXL
    assert j.frame.workspace_state.current_pack == before
    assert dialog._requests[2][0].instate(["disabled"])
    assert "eligibility" in dialog._explanations[SuggestionKind.WORKFLOW_CHOICE]


def test_all_three_contract_kinds_share_the_flow_when_a_canonical_list_exists(journey):
    j = journey
    # Inject already eligibility-checked canonical id/version pairs; production does not invent a video source context.
    j.flow._workflows = lambda: (("approved-id@1.3.0", "Approved test catalog option"),)
    dialog = start(j, SuggestionKind.WORKFLOW_CHOICE)
    finish(j, successful(j, workflow="approved-id@1.3.0"))
    assert "approved-id@1.3.0" in dialog.preview.get("1.0", "end")
    assert dialog.accept_button.instate(["disabled"])


def test_worker_completion_is_queued_and_never_touches_tk_until_delivery(journey):
    j = journey
    dialog = start(j)
    outcome = successful(j)
    worker = threading.Thread(target=lambda: j.service.callbacks[-1](outcome))
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert dialog.accept_button.instate(["disabled"]) and "running" in dialog.status_var.get()
    j.scheduled.pop(0)()
    assert dialog.accept_button.instate(["!disabled"])


def test_visibility_switch_scrubs_destroyed_controls_even_when_tab_is_unmapped(journey):
    j = journey
    dialog = start(j)
    finish(j, successful(j, positive="a nude PRIVATE_CANARY barn <lora:kept:0.8> [[season]]"))
    assert "PRIVATE_CANARY" in dialog.preview.get("1.0", "end")
    assert not j.frame.winfo_ismapped()
    j.state.set_content_visibility_mode("sfw")
    assert j.flow.dialog is None and j.flow.snapshot is None and j.flow.outcome is None
    assert not dialog.winfo_exists()
    j.flow.accept()
    assert "PRIVATE_CANARY" not in j.frame.workspace_state.get_slot(0).text


def test_hidden_source_is_never_submitted_as_redacted_placeholder(journey):
    j = journey
    j.frame.workspace_state.set_slot_text(0, "nude PRIVATE_CANARY")
    j.state.set_content_visibility_mode("sfw")
    j.frame._refresh_editor()
    j.flow.refresh()
    assert j.flow.button.instate(["disabled"])
    assert j.flow.open() is None and not j.service.requests


@pytest.mark.parametrize(
    "code", [code for code in OutcomeCode if code is not OutcomeCode.SUGGESTION]
)
def test_every_failure_outcome_is_truthful_content_free_and_not_acceptable(journey, code, caplog):
    j = journey
    dialog = start(j)
    request = j.service.requests[-1]
    finish(
        j,
        AssistOutcome(
            code, request.request_id, reason="PRIVATE_CANARY", details={"stdout": "PRIVATE_CANARY"}
        ),
    )
    text = dialog.status_var.get() + dialog.preview.get("1.0", "end") + caplog.text
    assert OUTCOME_TEXT[code] in text and "PRIVATE_CANARY" not in text
    assert dialog.accept_button.instate(["disabled"]) and dialog.cancel_button.instate(["disabled"])


def test_cancel_close_stale_and_repeated_completion_are_safe(journey):
    j = journey
    before = copy.deepcopy(j.frame.workspace_state.current_pack)
    dialog = start(j)
    first_callback = j.service.callbacks[-1]
    first_outcome = successful(j)
    j.flow.cancel()
    j.flow.cancel()
    assert set(j.service.cancelled) == {j.service.requests[-1].request_id}
    dialog.close()
    first_callback(first_outcome)
    j.scheduled.pop(0)()
    assert j.flow.dialog is None
    j.flow.refresh()
    new_dialog = start(j)
    first_callback(first_outcome)
    j.scheduled.pop(0)()
    assert "running" in new_dialog.status_var.get()
    finish(j)
    text = new_dialog.preview.get("1.0", "end")
    j.service.callbacks[-1](successful(j))
    j.scheduled.pop(0)()
    assert new_dialog.preview.get("1.0", "end") == text
    assert j.frame.workspace_state.current_pack == before


def test_cancel_while_success_is_queued_does_not_offer_acceptance(journey):
    j = journey
    dialog = start(j)
    j.service.callbacks[-1](successful(j))
    j.flow.cancel()
    j.scheduled.pop(0)()
    assert dialog.accept_button.instate(["disabled"])
    assert "cancelled for review" in dialog.status_var.get()
    j.flow.accept()
    assert not j.frame.workspace_state.dirty


@pytest.mark.parametrize("shutdown", [False, True])
def test_completion_after_destroy_or_shutdown_cannot_touch_tk(journey, shutdown):
    j = journey
    start(j)
    outcome = successful(j)
    j.service.callbacks[-1](outcome)
    if shutdown:
        j.owner.begin_shutdown()
    else:
        j.frame.destroy()
    j.scheduled.pop(0)()
    assert not j.frame.workspace_state.dirty


def test_transient_admission_refusal_can_retry_without_restart(journey):
    j = journey
    dialog = j.flow.open()
    submit = j.service.submit
    j.service.submit = lambda request, done: Submission(
        False, AssistOutcome(OutcomeCode.GENERATION_ACTIVE, request.request_id)
    )
    j.flow.request(SuggestionKind.PROMPT_REWRITE)
    assert "Generation is running" in dialog.status_var.get()
    assert dialog._requests[0][0].instate(["!disabled"])
    j.service.submit = submit
    j.flow.request(SuggestionKind.PROMPT_REWRITE)
    finish(j)
    assert dialog.accept_button.instate(["!disabled"])


def test_new_installation_and_attestation_are_rechecked_without_restart(journey):
    j = journey
    j.owner.status = lambda: AiAssistStatus("not_installed", "not installed")
    j.flow.refresh()
    assert j.flow.button.instate(["disabled"])
    j.owner.status = lambda: AiAssistStatus(STATE_READY, "ready", egress="not_attested")
    j.flow.refresh()
    assert "attested" in j.flow.explanation.cget("text") and j.flow.button.instate(["disabled"])
    j.owner.status = lambda: AiAssistStatus(STATE_READY, "ready", egress="attested")
    j.flow.refresh()
    assert j.flow.button.instate(["!disabled"])


def test_target_choices_use_actual_picker_policy_and_visibility(monkeypatch):
    from src.gui import prompt_ai_targets as choices

    def project(name, backend):
        assert backend == "forge_webui"
        return _projection(name)

    monkeypatch.setattr(choices, "configured_image_backend_id", lambda: "forge_webui")
    monkeypatch.setattr(choices, "project_model_selection", project)
    base = SimpleNamespace(
        _model_combo={"values": (SDXL, KLEIN, "mystery.safetensors")},
        _normalize_model_name=lambda name: name,
    )
    offered = choices.prompt_ai_targets(base, "sfw")
    assert tuple(key for key, _label in offered) == (SDXL, KLEIN)
    assert choices.prompt_ai_targets(None, "sfw") == ()


def test_real_application_and_window_bind_one_dormant_service(tk_root, tmp_path, monkeypatch):
    from src.controller import app_controller as controller_module
    from src.gui.main_window_v2 import MainWindowV2
    from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue

    monkeypatch.setenv("STABLENEW_AI_DIR", str(tmp_path / "absent-ai"))
    real = controller_module.AiAssistIntegration
    owners = []

    def create(*args, **kwargs):
        owner = real(*args, **kwargs)
        owners.append(owner)
        return owner

    monkeypatch.setattr(controller_module, "AiAssistIntegration", create)
    jobs, queue, _ = make_stubbed_job_service_with_queue()
    controller = controller_module.AppController(None, threaded=False, job_service=jobs)
    controller._shutdown_webui = Mock()  # runtime state is outside this GUI wiring test
    window = MainWindowV2(
        tk_root,
        app_state=controller.app_state,
        app_controller=controller,
        pipeline_controller=controller,
    )
    try:
        assert owners == [controller.ai_assist]
        assert window.prompt_tab.ai_suggestions.owner is controller.ai_assist
        assert controller.ai_assist._dispatch == window._invoker.invoke
        service = controller.ai_assist.service
        for _ in range(2):
            window.prompt_tab.ai_suggestions.refresh()
            assert window.prompt_tab.ai_suggestions.open() is None
        assert service is controller.ai_assist.service and service._worker is None
        assert queue.list_jobs() == []
        assert not (tmp_path / "absent-ai").exists()
    finally:
        controller.shutdown_app("ai112-test")
        window.cleanup()
    assert controller.ai_assist.quiescent is True and controller._shutdown_completed
