"""Hermetic Remote Preview and failover acceptance tests."""

from __future__ import annotations

import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai_assist import remote_transport
from src.ai_assist.contracts import AiCancelToken, AssistRequest, OutcomeCode, SuggestionKind
from src.ai_assist.events import EventLog
from src.ai_assist.framing import build_json_schema
from src.ai_assist.host import GenerationActivity
from src.ai_assist.paths import events_path
from src.ai_assist.remote import RemoteAssist, RemoteState
from src.ai_assist.remote_preview import (
    DEFAULT_MODEL,
    ENDPOINT,
    RUNTIME_VERSION,
    SETTINGS_NAME,
    RemoteApproval,
    disable_remote_preview,
    enable_remote_preview,
    read_remote_settings,
    revoke_remote_approval,
    select_remote_model,
    write_remote_approval,
)
from src.ai_assist.remote_transport import TransportFailure, loopback_request
from src.ai_assist.service import AiAssistService, ServicePolicy
from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.controller.app_controller_services.ai_assist_integration import AiAssistIntegration
from src.gui.model_policy_panel_projection import ModelPolicyPanelProjection
from src.gui.prompt_ai_plan_sources import build_plan_snapshot
from src.gui_v2.ai_plan_advice import build_plan_request, judge_plan
from src.gui_v2.ai_suggestion_view import provider_outcome_text, result_provider_label
from src.services.operator_readiness_service import OperatorReadinessService, OperatorReadinessState
from tools.ai_assist_admin import main as admin

from .conftest import attest, idle, request_for, roomy
from .test_service_runtime import SpawnSpy

APPROVAL = RemoteApproval(ENDPOINT, DEFAULT_MODEL, "a" * 64, RUNTIME_VERSION)
LFM = RemoteApproval(ENDPOINT, "lfm3:1.7b", "b" * 64, RUNTIME_VERSION)
PROMPT = "private authored canary <lora:barn:0.8>"
REWRITE = {
    "schema": "ai_assist.suggestion/1",
    "status": "ok",
    "kind": "prompt_rewrite",
    "positive": "private improved canary <lora:barn:0.8>",
    "negative": "",
    "changes": ["clarified_wording"],
}


class Worker:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.digest = APPROVAL.digest
        self.version = APPROVAL.version
        self.other_models = []
        self.output = json.dumps(REWRITE)
        self.reply_model = APPROVAL.model_reference
        self.before_response = lambda _token: None

    def __call__(self, path, body, token, timeout, limit):
        assert timeout > 0 and limit > 0
        self.calls.append((path, body))
        if path in self.failures:
            failure = self.failures[path]
            if isinstance(failure, str):
                raise TransportFailure(failure)
            return failure, b"private error body"
        if path == "/api/version":
            return 200, json.dumps({"version": self.version}).encode()
        if path == "/api/tags":
            return 200, json.dumps(
                {"models": [{"name": APPROVAL.model, "digest": self.digest}, *self.other_models]}
            ).encode()
        self.before_response(token)
        return 200, json.dumps(
            {"model": self.reply_model, "done": True, "response": self.output}
        ).encode()


def assist_request():
    return AssistRequest("remote-case", SuggestionKind.PROMPT_REWRITE, positive_text=PROMPT)


def service_for(installation, worker, activity=idle, memory=roomy, *, attested=True):
    write_remote_approval(installation.root, APPROVAL)
    if attested:
        attest(installation)
    spy = SpawnSpy()
    remote = RemoteAssist(installation.root, transport=worker)
    service = AiAssistService(
        root=installation.root,
        runtime_manifest=installation.manifest,
        registry=installation.registry,
        activity_provider=activity,
        memory_probe=memory,
        runtime=installation.runtime(spy),
        policy=ServicePolicy(allow_preview=True, strict_offline=True),
        remote=remote,
    )
    return service, spy, remote


def test_approval_is_explicit_persistent_and_confined(tmp_path):
    args = [
        "--root",
        str(tmp_path),
        "approve-remote-preview",
        "--endpoint",
        ENDPOINT,
        "--version",
        RUNTIME_VERSION,
        "--digest",
        APPROVAL.digest,
        "--accept-ssh-transfer",
    ]
    assert admin(args) == 0
    assert RemoteAssist(tmp_path).settings().approval == APPROVAL
    with pytest.raises(ValueError, match="unsupported remote identity"):
        RemoteApproval("http://192.168.1.22:11434", DEFAULT_MODEL, APPROVAL.digest, RUNTIME_VERSION)
    assert admin(["--root", str(tmp_path), "disable-remote-preview"]) == 0
    assert not read_remote_settings(tmp_path).preferred


def test_legacy_approval_survives_multi_model_selection_and_independent_revocation(tmp_path):
    path = tmp_path / SETTINGS_NAME
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "preferred": True,
                "approval": {
                    "endpoint": ENDPOINT,
                    "model": APPROVAL.model,
                    "digest": APPROVAL.digest,
                    "version": RUNTIME_VERSION,
                },
            }
        ),
        encoding="utf-8",
    )
    assert read_remote_settings(tmp_path).approval == APPROVAL
    write_remote_approval(tmp_path, LFM)
    assert json.loads(path.read_bytes())["schema"] == 2
    assert read_remote_settings(tmp_path).approval == APPROVAL
    select_remote_model(tmp_path, LFM)
    assert read_remote_settings(tmp_path).approval == LFM
    disable_remote_preview(tmp_path)
    assert read_remote_settings(tmp_path).approval is None
    assert read_remote_settings(tmp_path).approvals == (APPROVAL, LFM)
    enable_remote_preview(tmp_path)
    assert read_remote_settings(tmp_path).approval == LFM
    revoke_remote_approval(tmp_path, LFM.model)
    assert read_remote_settings(tmp_path).approval is None
    assert read_remote_settings(tmp_path).approvals == (APPROVAL,)
    with pytest.raises(ValueError):
        select_remote_model(tmp_path, LFM)
    select_remote_model(tmp_path, APPROVAL)
    assert read_remote_settings(tmp_path).approval == APPROVAL


def test_default_prefers_qwen_without_overriding_explicit_lfm_choice(tmp_path):
    write_remote_approval(tmp_path, LFM)
    assert read_remote_settings(tmp_path).approval == LFM
    write_remote_approval(tmp_path, APPROVAL)
    assert read_remote_settings(tmp_path).approval == APPROVAL
    select_remote_model(tmp_path, LFM)
    write_remote_approval(tmp_path, APPROVAL)
    assert read_remote_settings(tmp_path).approval == LFM


@pytest.mark.parametrize("damage", ["duplicate", "unapproved_active", "conflicting_digests"])
def test_ambiguous_registry_fails_closed(tmp_path, damage):
    write_remote_approval(tmp_path, APPROVAL)
    write_remote_approval(tmp_path, LFM)
    path = tmp_path / SETTINGS_NAME
    raw = path.read_text(encoding="utf-8")
    if damage == "duplicate":
        raw = raw.replace('"schema": 2', '"schema": 1, "schema": 2')
    elif damage == "unapproved_active":
        raw = raw.replace('"active_model": "default"', '"active_model": "other"')
    else:
        raw = raw.replace(LFM.digest, APPROVAL.digest)
    path.write_text(raw, encoding="utf-8")
    settings = read_remote_settings(tmp_path)
    assert settings.damaged and settings.preferred and settings.approval is None
    with pytest.raises(ValueError):
        write_remote_approval(tmp_path, LFM)
    assert path.read_text(encoding="utf-8") == raw


def test_selection_uses_exact_displayed_identity_and_does_no_io_to_worker(installation):
    worker = Worker()
    worker.other_models = [{"name": LFM.model, "digest": LFM.digest}]
    worker.reply_model = LFM.model_reference
    service, spy, _remote = service_for(installation, worker)
    write_remote_approval(installation.root, LFM)
    stale = RemoteApproval(ENDPOINT, LFM.model, "c" * 64, RUNTIME_VERSION)
    with pytest.raises(ValueError):
        service.select_remote_model(stale)
    service.select_remote_model(LFM)
    assert not worker.calls
    outcome = service.run(assist_request())
    assert outcome.ok and LFM.model in result_provider_label(outcome)
    assert json.loads(worker.calls[-1][1])["model"] == LFM.model_reference
    assert spy.calls == 0


WIRE_CASES = [
    (
        SuggestionKind.PROMPT_REWRITE,
        {"positive_text": PROMPT},
        {
            "positive": REWRITE["positive"],
            "negative": "",
        },
        {"positive": "missing protected token"},
    ),
    (
        SuggestionKind.TARGET_FIT_ADVICE,
        {"allowed_targets": ("juggernautXL_ragnarokBy",)},
        {
            "target": "juggernautXL_ragnarokBy",
        },
        {"target": "invented"},
    ),
    (
        SuggestionKind.WORKFLOW_CHOICE,
        {"allowed_workflows": ("svd_xt",)},
        {
            "workflow": "svd_xt",
        },
        {"workflow": "invented"},
    ),
    (
        SuggestionKind.PLAN_PROPOSAL,
        {
            "goal_text": "A barn",
            "allowed_targets": ("juggernautXL_ragnarokBy",),
            "allowed_stages": ("txt2img",),
        },
        {
            "steps": [
                {
                    "stage": "txt2img",
                    "target": "juggernautXL_ragnarokBy",
                    "workflow": None,
                    "count": 1,
                    "rationale": "Fits the goal",
                }
            ]
        },
        {"steps": []},
    ),
    (
        SuggestionKind.SLOT_VARIETY,
        {
            "goal_text": "More cakes",
            "matrix_slots": (("cake", ("chocolate cake",)),),
        },
        {"slots": [{"slot": "cake", "values": ["carrot cake"], "rationale": "More variety"}]},
        {"slots": [{"slot": "other", "values": ["carrot cake"], "rationale": "More variety"}]},
    ),
]


@pytest.mark.parametrize(
    "kind,inputs,fields,invalid", WIRE_CASES, ids=[case[0].value for case in WIRE_CASES]
)
def test_ollama_wire_schema_and_canonical_validation(installation, kind, inputs, fields, invalid):
    worker = Worker()
    service, spy, _remote = service_for(installation, worker)
    request = AssistRequest("wire", kind, **inputs)
    good = {"schema": REWRITE["schema"], "status": "ok", "kind": kind.value, **fields}
    for response, expected in [
        (json.dumps(good), OutcomeCode.SUGGESTION),
        ("{invalid", OutcomeCode.MALFORMED),
        (json.dumps(good | {"schema": "other"}), OutcomeCode.MALFORMED),
        (json.dumps(good | {"kind": "other"}), OutcomeCode.MALFORMED),
        (json.dumps(good | {"extra": 1}), OutcomeCode.MALFORMED),
        (json.dumps(good | invalid), OutcomeCode.MALFORMED),
        (
            json.dumps({key: value for key, value in good.items() if key not in fields}),
            OutcomeCode.MALFORMED,
        ),
        (
            json.dumps(
                {"schema": REWRITE["schema"], "status": "refused", "refusal_reason": "Declined"}
            ),
            OutcomeCode.REFUSED_BY_MODEL,
        ),
    ]:
        worker.output = response
        assert service.run(request).code is expected
        assert json.loads(worker.calls[-1][1])["format"] == build_json_schema(request)
    assert spy.calls == 0


@pytest.mark.parametrize(
    "change", ["missing_negative", "null_negative", "extra_null", "duplicate_status"]
)
def test_remote_contract_rejects_ambiguous_or_incomplete_envelope(installation, change):
    worker = Worker()
    response = REWRITE.copy()
    if change == "missing_negative":
        del response["negative"]
    elif change == "null_negative":
        response["negative"] = None
    elif change == "extra_null":
        response["workflow"] = None
    worker.output = json.dumps(response)
    if change == "duplicate_status":
        worker.output = worker.output.replace(
            '"status": "ok"', '"status": "refused", "status": "ok"'
        )
    service, spy, _remote = service_for(installation, worker)
    outcome = service.run(assist_request())
    assert outcome.code is OutcomeCode.MALFORMED and outcome.suggestion is None
    assert spy.calls == 0


def test_startup_does_only_prompt_free_checks_off_the_caller_thread(installation):
    entered, release, checked = threading.Event(), threading.Event(), threading.Event()
    worker = Worker()

    def transport(path, body, *args):
        entered.set()
        assert release.wait(5)
        result = worker(path, body, *args)
        if path == "/api/tags":
            checked.set()
        return result

    write_remote_approval(installation.root, APPROVAL)
    remote = RemoteAssist(installation.root, transport=transport)
    owner = AiAssistIntegration(
        lambda: None,
        Mock(),
        root=installation.root,
        runtime_manifest=installation.manifest,
        registry=installation.registry,
        remote=remote,
    )
    try:
        assert entered.wait(5)
        assert remote.state() is RemoteState.RECOVERING
        assert owner.availability()[0] is None
        release.set()
        assert checked.wait(5)
    finally:
        release.set()
        assert owner.shutdown()
    assert worker.calls == [("/api/version", None), ("/api/tags", None)]


def test_active_generation_and_local_quarantine_do_not_gate_remote(installation, caplog):
    worker = Worker()
    activity = Mock(return_value=GenerationActivity(1, True))
    memory = Mock(return_value=None)
    service, spy, _ = service_for(installation, worker, activity, memory, attested=False)
    outcome = service.run(assist_request())
    assert outcome.ok
    assert outcome.details == {
        "provider": "remote",
        "trust_tier": "preview",
        "model_sha256": APPROVAL.digest,
        "model_name": APPROVAL.model,
        "runtime_build_id": f"ollama-{RUNTIME_VERSION}",
        "fallback": False,
    }
    activity.assert_not_called()
    memory.assert_not_called()
    assert spy.calls == 0
    assert [path for path, _body in worker.calls] == ["/api/version", "/api/tags", "/api/generate"]
    assert all(body is None for _path, body in worker.calls[:2])
    payload = json.loads(worker.calls[-1][1])
    assert payload["model"] == f"sha256-{APPROVAL.digest}:local"
    assert payload["think"] is False and payload["stream"] is False
    assert isinstance(payload["format"], dict)
    assert PROMPT in payload["prompt"]
    assert 'set status to "ok"' in payload["prompt"]
    assert '"refusal_reason": "..."' not in payload["prompt"]
    event = EventLog(events_path(installation.root)).tail(1)[0]
    assert event["provider"] == "remote" and event["strict_offline"] is False
    assert event["model_sha256_prefix"] == APPROVAL.digest[:12]
    assert "private" not in json.dumps(event) and "private" not in caplog.text
    assert "Remote AI Assist Preview" in result_provider_label(outcome)


@pytest.fixture
def sdxl_plan():
    name = "juggernautXL_ragnarokBy"
    panel = SimpleNamespace(
        _model_combo={"values": (name,)},
        _normalize_model_name=lambda raw: raw,
        model_var=SimpleNamespace(get=lambda: name),
    )
    evidence = CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
    policy_panel = ModelPolicyPanelProjection(
        panel, family_lookup=lambda _name: evidence, backend_id_provider=lambda: "forge_webui"
    )
    panel.project_checkpoint_candidates = policy_panel.project_checkpoint_candidates
    snapshot = build_plan_snapshot(panel, None, "sfw", policy_panel.refresh())
    request = build_plan_request(
        "sdxl-remote-plan",
        "Plan a landscape image.",
        targets=snapshot.targets,
        workflows=snapshot.workflows,
        stages=snapshot.stages,
        target_policy_id=snapshot.target_policy_id,
        current_target=snapshot.current_target,
        current_target_label=snapshot.current_target_label,
        current_target_stages=snapshot.current_target_stages,
    )
    plan = {
        "schema": "ai_assist.suggestion/1",
        "status": "ok",
        "kind": "plan_proposal",
        "steps": [
            {
                "stage": "txt2img",
                "target": name,
                "workflow": None,
                "count": 1,
                "rationale": "Start with one view of the landscape.",
            },
        ],
    }
    return request, snapshot.facts, plan


def test_registry_backed_remote_plan_is_valid_during_generation(installation, sdxl_plan):
    request, facts, plan = sdxl_plan
    worker = Worker()
    worker.output = json.dumps(plan)
    activity = Mock(return_value=GenerationActivity(1, False))
    service, spy, _ = service_for(installation, worker, activity)
    outcome = service.run(request)
    assert outcome.ok and outcome.suggestion is not None
    assert outcome.suggestion.steps[0].target == request.current_target
    assert judge_plan(outcome.suggestion, facts).all_valid
    assert outcome.details["provider"] == "remote"
    assert request.allowed_targets == ("juggernautXL_ragnarokBy",)
    assert request.target_policy_id == "sdxl"
    assert (
        "Use this id for it: juggernautXL_ragnarokBy." in json.loads(worker.calls[-1][1])["prompt"]
    )
    activity.assert_not_called()
    assert spy.calls == 0

    worker.failures["/api/generate"] = "disconnected"
    fallback = service.run(request)
    assert fallback.code is OutcomeCode.GENERATION_ACTIVE and fallback.suggestion is None
    assert fallback.details["fallback"] is True and spy.calls == 0
    activity.assert_called_once()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"target": "invented-checkpoint"}, "target_not_in_closed_list"),
        ({"target": "juggernautXL_ragnarokBy (SDXL)"}, "target_not_in_closed_list"),
        ({"stage": "unsupported"}, "stage_not_in_closed_list"),
        ({"workflow": "video-workflow"}, "step_workflow_with_image_stage"),
        ({"unexpected": "field"}, "step_fields_invalid"),
        ({"count": 9}, "step_count_out_of_bounds"),
    ],
)
def test_invalid_registry_backed_remote_plan_is_rejected_without_repair(
    installation, sdxl_plan, override, reason
):
    request, _facts, plan = sdxl_plan
    plan["steps"][0].update(override)
    worker = Worker()
    worker.output = json.dumps(plan)
    service, spy, _ = service_for(installation, worker)
    outcome = service.run(request)
    assert outcome.code is OutcomeCode.MALFORMED and outcome.reason == reason
    assert outcome.suggestion is None and outcome.details["fallback"] is False
    assert [path for path, _body in worker.calls] == ["/api/version", "/api/tags", "/api/generate"]
    assert spy.calls == 0


@pytest.mark.parametrize("broken_path", ["/api/version", "/api/tags", "/api/generate"])
def test_confirmed_disconnect_falls_back_once_and_next_request_recovers(installation, broken_path):
    worker = Worker()
    worker.failures[broken_path] = "disconnected"
    service, spy, remote = service_for(installation, worker)
    fallback = service.run(request_for())
    assert fallback.ok
    assert fallback.details["provider"] == "local"
    assert fallback.details["fallback"] is True
    assert fallback.details["fallback_reason"] == "remote_disconnected"
    assert spy.calls == 1
    assert remote.state() is RemoteState.UNAVAILABLE

    worker.failures.clear()
    next_outcome = service.run(assist_request())
    assert next_outcome.ok and next_outcome.details["provider"] == "remote"
    assert remote.state() is RemoteState.RESTORED
    assert spy.calls == 1
    records = EventLog(events_path(installation.root)).tail(3)
    assert [event["provider"] for event in records] == ["local", "remote"]


def test_outage_does_not_override_local_admission(installation):
    worker = Worker()
    worker.failures["/api/version"] = "disconnected"
    service, spy, remote = service_for(
        installation,
        worker,
        activity=lambda: GenerationActivity(1, False),
        attested=False,
    )
    assert service.run(assist_request()).code is OutcomeCode.EGRESS_NOT_ATTESTED
    attest(installation)
    blocked = service.run(assist_request())
    assert blocked.code is OutcomeCode.GENERATION_ACTIVE
    assert blocked.details["fallback"] is True
    assert "Remote unavailable. Local AI is blocked" in provider_outcome_text(blocked)
    assert remote.state() is RemoteState.UNAVAILABLE and spy.calls == 0


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("version", OutcomeCode.INTEGRITY_FAILED),
        ("digest", OutcomeCode.INTEGRITY_FAILED),
        ("reply_model", OutcomeCode.INTEGRITY_FAILED),
        ("refused", OutcomeCode.REFUSED_BY_MODEL),
        ("malformed", OutcomeCode.MALFORMED),
        ("protected", OutcomeCode.MALFORMED),
        ("timeout", OutcomeCode.TIMEOUT),
        ("overload", OutcomeCode.UNAVAILABLE),
        ("redirect", OutcomeCode.INTEGRITY_FAILED),
    ],
)
def test_non_transport_failures_never_use_local(installation, failure, expected, caplog):
    worker = Worker()
    service, spy, _ = service_for(installation, worker)
    if failure == "version":
        worker.version = "0.0.1"
    elif failure == "digest":
        worker.digest = "b" * 64
    elif failure == "reply_model":
        worker.reply_model = "unexpected"
    elif failure == "refused":
        worker.output = '{"schema":"ai_assist.suggestion/1","status":"refused","refusal_reason":"private canary"}'
    elif failure == "malformed":
        worker.output = "private canary {invalid"
    elif failure == "protected":
        worker.output = json.dumps(dict(REWRITE, positive="missing protected token"))
    elif failure == "timeout":
        worker.failures["/api/generate"] = "timeout"
    else:
        worker.failures["/api/generate"] = 503 if failure == "overload" else 302

    outcome = service.run(assist_request())
    assert outcome.code is expected and outcome.suggestion is None
    assert not outcome.details["fallback"] and spy.calls == 0
    if failure in ("version", "digest"):
        assert all(body is None for _path, body in worker.calls)
    assert "private" not in caplog.text


def test_present_but_damaged_approval_fails_closed_and_explicit_disable_allows_local(installation):
    worker = Worker()
    service, spy, remote = service_for(installation, worker)
    (installation.root / SETTINGS_NAME).write_text(
        '{"schema":1,"preferred":true}', encoding="utf-8"
    )
    assert remote.state() is RemoteState.UNTRUSTED
    assert service.run(assist_request()).code is OutcomeCode.INTEGRITY_FAILED
    assert not worker.calls and spy.calls == 0
    disable_remote_preview(installation.root)
    assert service.run(request_for()).ok
    assert not worker.calls and spy.calls == 1


@pytest.mark.parametrize("end", ["continue", "cancel", "shutdown", "reapprove"])
def test_in_flight_remote_fences_late_results_without_local_yield(installation, end):
    worker = Worker()
    entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
    activity = Mock(return_value=GenerationActivity())
    outcomes = []

    def wait_to_reply(_token):
        entered.set()
        assert release.wait(5)
        # Deliberately return success even after cancellation, to exercise the service fence.

    def completed(outcome):
        outcomes.append(outcome)
        delivered.set()

    worker.before_response = wait_to_reply
    service, spy, remote = service_for(installation, worker, activity=activity)
    assert service.submit(assist_request(), completed).accepted
    try:
        assert entered.wait(5)
        assert remote.state() is RemoteState.RUNNING
        assert service.run(assist_request()).code is OutcomeCode.BUSY
        with pytest.raises(ValueError, match="request active"):
            service.select_remote_model(LFM)
        activity.return_value = GenerationActivity(1, True)
        if end == "cancel":
            assert service.cancel("remote-case")
        elif end == "shutdown":
            service.begin_shutdown()
        elif end == "reapprove":
            write_remote_approval(
                installation.root,
                RemoteApproval(
                    ENDPOINT,
                    DEFAULT_MODEL,
                    "b" * 64,
                    RUNTIME_VERSION,
                ),
            )
        release.set()
        assert delivered.wait(5)
    finally:
        release.set()
        assert service.shutdown()
    assert len(outcomes) == 1 and spy.calls == 0
    assert (
        outcomes[0].code
        is {
            "continue": OutcomeCode.SUGGESTION,
            "cancel": OutcomeCode.CANCELLED,
            "shutdown": OutcomeCode.CANCELLED,
            "reapprove": OutcomeCode.INTEGRITY_FAILED,
        }[end]
    )
    activity.assert_not_called()


def test_queued_remote_success_is_refused_when_approval_changes_before_delivery(installation):
    worker = Worker()
    queued, actions, outcomes = threading.Event(), [], []

    def dispatch(invoke):
        actions.append(invoke)
        queued.set()

    write_remote_approval(installation.root, APPROVAL)
    owner = AiAssistIntegration(
        lambda: None,
        dispatch,
        root=installation.root,
        runtime_manifest=installation.manifest,
        registry=installation.registry,
        remote=RemoteAssist(installation.root, transport=worker),
    )
    try:
        result = owner.submit_plan(
            assist_request(),
            lambda _outcome: "judged",
            lambda outcome, judge: outcomes.append((outcome, judge)),
        )
        assert result.accepted and queued.wait(5)
        disable_remote_preview(installation.root)
        actions[0]()
        outcome, judgement = outcomes[0]
        assert (outcome.code, outcome.suggestion, judgement) == (
            OutcomeCode.INTEGRITY_FAILED,
            None,
            None,
        )
    finally:
        assert owner.shutdown()


def test_operator_readiness_reports_untrusted_separately_from_local(installation):
    (installation.root / SETTINGS_NAME).write_text(
        '{"schema":1,"preferred":true}', encoding="utf-8"
    )
    owner = AiAssistIntegration(
        lambda: None,
        Mock(),
        root=installation.root,
        runtime_manifest=installation.manifest,
        registry=installation.registry,
    )
    try:
        readiness = OperatorReadinessService(ai_assist_status_provider=owner.operator_status)
        record = readiness._ai_assist_record()
        assert record.state is OperatorReadinessState.ACTION_REQUIRED
        assert "Remote AI requires verification" in record.summary
    finally:
        assert owner.shutdown()


class FakeSocket:
    def __init__(self, raw):
        self.raw = raw
        self.writes = []
        self.connected = None
        self.timeout = None
        self.reader = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.connected = address

    def sendall(self, data):
        self.writes.append(data)

    def makefile(self, *_args, **_kwargs):
        return io.BytesIO(self.raw)

    def close(self):
        pass


@pytest.mark.parametrize(
    ("reply", "limit", "expected"),
    [
        (b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}", 64, (200, b"{}")),
        (
            b"HTTP/1.1 302 Found\r\nLocation: http://outside.invalid\r\nContent-Length: 0\r\n\r\n",
            64,
            (302, b""),
        ),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n{}", 64, "disconnected"),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n", 8, "response_too_large"),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n",
            64,
            (200, b"{}"),
        ),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\ninvalid\r\n", 64, "invalid_http"),
    ],
)
def test_transport_direct_loopback_and_bounded_http(monkeypatch, reply, limit, expected):
    connection = FakeSocket(reply)
    monkeypatch.setattr(remote_transport, "_RequestSocket", lambda *_args: connection)
    monkeypatch.setenv("HTTP_PROXY", "http://outside.invalid")
    if isinstance(expected, str):
        with pytest.raises(TransportFailure, match=expected):
            loopback_request("/api/version", None, AiCancelToken(), 1.0, limit)
    else:
        assert loopback_request("/api/version", None, AiCancelToken(), 1.0, limit) == expected
    assert connection.connected == ("127.0.0.1", 11435)
    assert len(connection.writes) == 1
    assert connection.writes[0].startswith(b"GET /api/version HTTP/1.1\r\n")
    assert b"outside.invalid" not in connection.writes[0]


def test_lost_generation_response_does_not_fall_back(installation, monkeypatch):
    connection = FakeSocket(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n{}")
    monkeypatch.setattr(remote_transport, "_RequestSocket", lambda *_args: connection)
    worker = Worker()

    def transport(path, body, *args):
        if path == "/api/generate":
            return loopback_request(path, body, *args)
        return worker(path, body, *args)

    service, spy, _remote = service_for(installation, transport)
    outcome = service.run(assist_request())
    assert outcome.code is OutcomeCode.UNAVAILABLE and outcome.reason == "remote_response_lost"
    assert not outcome.details["fallback"] and spy.calls == 0
    assert connection.writes[0].startswith(b"POST /api/generate HTTP/1.1\r\n")


def test_transport_reader_enforces_deadline_across_multiple_partial_reads(monkeypatch):
    clock = iter([0.0, 0.15, 0.3])
    monkeypatch.setattr(remote_transport, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    token = AiCancelToken()
    receiver = Mock()
    receiver.recv_into.return_value = 1
    with remote_transport._DeadlineReader(receiver, token, 0.2) as reader:
        assert reader.readinto(bytearray(1)) == 1
        assert reader.readinto(bytearray(1)) == 1
        with pytest.raises(TransportFailure, match="timeout"):
            reader.readinto(bytearray(1))


def test_cancel_before_connect_and_reject_non_capability_paths(monkeypatch):
    socket_factory = Mock(side_effect=AssertionError("connection should never be attempted"))
    monkeypatch.setattr(remote_transport, "_RequestSocket", socket_factory)
    with pytest.raises(TransportFailure, match="invalid_endpoint"):
        loopback_request("/api/pull", b"{}", AiCancelToken(), 1.0, 64)
    token = AiCancelToken()
    token.cancel()
    with pytest.raises(TransportFailure, match="cancelled"):
        loopback_request("/api/version", None, token, 1.0, 64)
    socket_factory.assert_not_called()
