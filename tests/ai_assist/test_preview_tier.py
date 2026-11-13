"""AI Assist Preview (owner decision D13): enablement, admission, labelling and revocation; hermetic fake child only."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.ai_assist.attestation import record_attestation
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.events import EventLog
from src.ai_assist.manifests import ModelRegistry, RuntimeManifest, record_active
from src.ai_assist.paths import events_path, preview_enablement_path
from src.ai_assist.preview import (
    PREVIEW_LABEL,
    PreviewRefused,
    enable_preview,
    preview_enabled_for,
    read_preview_enablement,
    revoke_preview,
)
from src.ai_assist.service import ServicePolicy
from src.ai_assist.status import (
    STATE_PREVIEW,
    STATE_PREVIEW_AVAILABLE,
    STATE_READY,
    preview_state,
    read_status,
)
from src.controller.app_controller_services.ai_assist_integration import AiAssistIntegration
from src.gui_v2.ai_suggestion_view import preview_status_text
from src.services.operator_readiness_service import OperatorReadinessService

from .conftest import Install, request_for
from .test_service_runtime import SpawnSpy, make_service

PREVIEW_POLICY = ServicePolicy(allow_preview=True, strict_offline=True, watch_interval_seconds=0.05)
SECRET = "SECRETPROMPTWORDS"


@pytest.fixture
def candidate(installation: Install) -> Install:
    """The same verified installation, but with an unqualified model and runtime (a Preview candidate)."""

    return replace(
        installation,
        manifest=RuntimeManifest((replace(installation.build, qualified=False),)),
        registry=ModelRegistry((replace(installation.entry, qualified=False),)),
        build=replace(installation.build, qualified=False),
        entry=replace(installation.entry, qualified=False),
    )


def enable(inst: Install) -> None:
    enable_preview(inst.root, inst.manifest, inst.registry)


def test_status_distinguishes_qualified_available_enabled_and_not_installed(
    installation: Install, candidate: Install, tmp_path
) -> None:
    assert (
        read_status(installation.root, installation.manifest, installation.registry).state
        == STATE_READY
    )
    status = read_status(candidate.root, candidate.manifest, candidate.registry)
    assert status.state == STATE_PREVIEW_AVAILABLE and status.missing == "enablement"
    assert preview_state(status).can_enable
    enable(candidate)
    status = read_status(candidate.root, candidate.manifest, candidate.registry)
    assert status.state == STATE_PREVIEW and status.trust == "preview"
    assert status.missing == "attestation" and PREVIEW_LABEL in status.summary
    empty = read_status(tmp_path / "x", RuntimeManifest(()), ModelRegistry(()))
    assert empty.missing == "pinned_build"
    assert (
        read_status(tmp_path / "x", candidate.manifest, candidate.registry).missing
        == "imported_model"
    )


def test_enable_use_label_and_revoke(candidate: Install) -> None:
    spy = SpawnSpy()
    service = make_service(candidate, policy=PREVIEW_POLICY, runner=spy)
    record_attestation(candidate.root, "outbound block rule")
    refused = service.run(request_for())
    assert refused.code is OutcomeCode.NOT_INSTALLED and refused.reason == "preview_not_enabled"
    assert spy.calls == 0
    enable(candidate)
    outcome = service.run(request_for(request_id="r2", extra=SECRET))
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.details["trust_tier"] == "preview"
    last = EventLog(events_path(candidate.root)).tail(1)[0]
    assert last["trust_tier"] == "preview" and last["strict_offline"] is True
    assert SECRET not in events_path(candidate.root).read_text(encoding="utf-8")
    assert SECRET not in preview_enablement_path(candidate.root).read_text(encoding="utf-8")
    assert revoke_preview(candidate.root) and read_preview_enablement(candidate.root) is None
    again = service.run(request_for(request_id="r3"))
    assert again.reason == "preview_not_enabled" and spy.calls == 1


def test_enablement_record_holds_identities_and_a_timestamp_only(candidate: Install) -> None:
    enable(candidate)
    document = json.loads(preview_enablement_path(candidate.root).read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "model_sha256", "runtime_build_id", "enabled_utc"}
    assert document["model_sha256"] == candidate.entry.sha256
    assert document["runtime_build_id"] == candidate.build.build_id


def test_identity_mismatch_and_repointing_void_the_enablement(candidate: Install) -> None:
    enable(candidate)
    path = preview_enablement_path(candidate.root)
    good = json.loads(path.read_text(encoding="utf-8"))
    for key, value in (("model_sha256", "0" * 64), ("runtime_build_id", "other-build")):
        path.write_text(json.dumps({**good, key: value}), encoding="utf-8")
        assert not preview_enabled_for(candidate.root, candidate.entry, candidate.build)
        service = make_service(candidate, policy=PREVIEW_POLICY)
        assert service.run(request_for()).reason == "preview_not_enabled"
    path.write_text(json.dumps(good), encoding="utf-8")
    assert preview_enabled_for(candidate.root, candidate.entry, candidate.build)
    record_active(candidate.root, candidate.build, candidate.entry)
    assert not path.exists()


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[]", '{"schema_version": 2}', '{"schema_version": 1}', "null"],
)
def test_malformed_record_fails_closed(candidate: Install, content: str) -> None:
    preview_enablement_path(candidate.root).write_text(content, encoding="utf-8")
    assert read_preview_enablement(candidate.root) is None
    spy = SpawnSpy()
    record_attestation(candidate.root, "rule")
    outcome = make_service(candidate, policy=PREVIEW_POLICY, runner=spy).run(request_for())
    assert outcome.code is OutcomeCode.NOT_INSTALLED and spy.calls == 0


def test_missing_attestation_still_blocks_in_preview(candidate: Install) -> None:
    enable(candidate)
    spy = SpawnSpy()
    outcome = make_service(candidate, policy=PREVIEW_POLICY, runner=spy).run(request_for())
    assert outcome.code is OutcomeCode.EGRESS_NOT_ATTESTED and spy.calls == 0


def test_preview_policy_off_never_admits_a_candidate_even_with_a_record(candidate: Install) -> None:
    enable(candidate)
    record_attestation(candidate.root, "rule")
    policy = ServicePolicy(strict_offline=True, watch_interval_seconds=0.05)
    assert (
        make_service(candidate, policy=policy).run(request_for()).code is OutcomeCode.NOT_INSTALLED
    )


def test_qualified_path_is_unchanged_and_labelled_qualified(installation: Install) -> None:
    record_attestation(installation.root, "rule")
    outcome = make_service(installation, policy=PREVIEW_POLICY).run(request_for())
    assert outcome.code is OutcomeCode.SUGGESTION and outcome.details["trust_tier"] == "qualified"
    assert EventLog(events_path(installation.root)).tail(1)[0]["trust_tier"] == "qualified"
    with pytest.raises(PreviewRefused) as caught:
        enable(installation)
    assert caught.value.code == "already_qualified"


def test_harness_path_is_unchanged_and_records_no_trust_tier(candidate: Install) -> None:
    policy = ServicePolicy(allow_candidate=True, watch_interval_seconds=0.05)
    outcome = make_service(candidate, policy=policy).run(request_for())
    assert outcome.code is OutcomeCode.SUGGESTION
    assert "trust_tier" not in EventLog(events_path(candidate.root)).tail(1)[0]


def test_enable_refused_when_nothing_is_installed(tmp_path, candidate: Install) -> None:
    with pytest.raises(PreviewRefused) as caught:
        enable_preview(tmp_path / "nothing", candidate.manifest, candidate.registry)
    assert caught.value.code == "no_active_pointer"
    assert not (tmp_path / "nothing" / "preview_enablement.json").exists()


def test_integration_names_each_missing_prerequisite_then_runs_labelled(
    candidate: Install, tmp_path
) -> None:
    def owner(root, manifest, registry):
        return AiAssistIntegration(
            lambda: None, lambda cb: None, root=root, runtime_manifest=manifest, registry=registry
        )

    no_build = owner(tmp_path / "a", RuntimeManifest(()), candidate.registry)
    code, text = no_build.availability()
    assert code is OutcomeCode.NOT_INSTALLED and "pinned runtime build" in text
    not_imported = owner(tmp_path / "b", candidate.manifest, candidate.registry)
    assert "imported runtime and model" in not_imported.availability()[1]
    ai = owner(candidate.root, candidate.manifest, candidate.registry)
    code, text = ai.availability()
    assert code is OutcomeCode.NOT_INSTALLED and "not enabled" in text and ai.trust_label() == ""
    assert ai.preview_state().can_enable
    assert ai.enable_preview()[0]
    code, text = ai.availability()
    assert code is OutcomeCode.EGRESS_NOT_ATTESTED
    record_attestation(candidate.root, "rule")
    code, text = ai.availability()
    assert code is None and PREVIEW_LABEL in text and ai.trust_label() == PREVIEW_LABEL
    assert ai.revoke_preview()[0] and ai.trust_label() == ""
    assert ai.availability()[0] is OutcomeCode.NOT_INSTALLED
    ai.shutdown()
    no_build.shutdown()
    not_imported.shutdown()


def test_integration_service_uses_preview_policy_with_strict_offline(tmp_path) -> None:
    ai = AiAssistIntegration(lambda: None, lambda cb: None, root=tmp_path / "ai")
    assert ai.service is not None
    policy = ai.service._policy
    assert policy.allow_preview and policy.strict_offline and not policy.allow_candidate
    ai.shutdown()


def test_readiness_record_shows_the_preview_state_and_label(candidate: Install) -> None:
    enable(candidate)
    service = OperatorReadinessService(
        ai_assist_status_provider=lambda: read_status(
            candidate.root, candidate.manifest, candidate.registry
        ),
        python_version_provider=lambda: (3, 14, 0),
        free_threaded_provider=lambda: False,
        jit_enabled_provider=lambda: False,
        comfy_command_provider=lambda: (),
    )
    record = service.collect().record_for("ai_assist")
    assert (
        record is not None and PREVIEW_LABEL in record.summary and "not attested" in record.summary
    )


def test_preview_status_text_names_the_exact_prerequisite() -> None:
    from src.ai_assist.preview import PreviewState

    assert "pinned" in preview_status_text(PreviewState("", "pinned_build"))
    assert "imported" in preview_status_text(PreviewState("", "imported_model"))
    assert "not enabled" in preview_status_text(PreviewState("candidate", "enablement", "M", "b"))
    assert "attestation" in preview_status_text(PreviewState("preview", "attestation", "M", "b"))
