"""The read-only readiness projection: optional when absent, ready when intact, action required when tampered."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.ai_assist.attestation import record_attestation
from src.ai_assist.events import EventLog
from src.ai_assist.manifests import ModelRegistry, RuntimeManifest
from src.ai_assist.paths import events_path, runtime_dir
from src.ai_assist.status import (
    STATE_INTEGRITY_FAILED,
    STATE_NOT_INSTALLED,
    STATE_READY,
    AiAssistStatus,
    read_status,
)
from src.services.operator_readiness_service import OperatorReadinessService, OperatorReadinessState

from .conftest import Install


def _service(provider) -> OperatorReadinessService:
    return OperatorReadinessService(
        ai_assist_status_provider=provider,
        python_version_provider=lambda: (3, 14, 0),
        free_threaded_provider=lambda: False,
        jit_enabled_provider=lambda: False,
        comfy_command_provider=lambda: (),
    )


def test_nothing_registered_is_optional_not_installed(tmp_path: Path) -> None:
    status = read_status(tmp_path / "ai", RuntimeManifest(()), ModelRegistry(()))
    assert status.state == STATE_NOT_INSTALLED and status.egress == "not_attested"


def test_an_intact_qualified_installation_is_ready(installation: Install) -> None:
    status = read_status(installation.root, installation.manifest, installation.registry)
    assert status.state == STATE_READY and status.blockers == ()


def test_registered_but_not_imported_is_not_installed_with_an_action(
    installation: Install, tmp_path: Path
) -> None:
    status = read_status(tmp_path / "elsewhere", installation.manifest, installation.registry)
    assert status.state == STATE_NOT_INSTALLED and status.actions


def test_tampering_is_an_integrity_failure_with_the_reason(installation: Install) -> None:
    (runtime_dir(installation.root, installation.build.build_id) / "ggml.dll").write_bytes(
        b"changed"
    )
    status = read_status(installation.root, installation.manifest, installation.registry)
    assert status.state == STATE_INTEGRITY_FAILED
    assert status.blockers[0].startswith("runtime_file_changed")


def test_unqualified_candidates_do_not_make_the_feature_ready(installation: Install) -> None:
    manifest = RuntimeManifest((replace(installation.build, qualified=False),))
    assert (
        read_status(installation.root, manifest, installation.registry).state == STATE_NOT_INSTALLED
    )


def test_status_reports_attestation_and_last_outcome_without_content(installation: Install) -> None:
    record_attestation(installation.root, "outbound block rule")
    EventLog(events_path(installation.root)).append(
        {"request_id": "r1", "outcome": "refused_by_model"}
    )
    status = read_status(installation.root, installation.manifest, installation.registry)
    assert status.egress == "attested" and status.last_outcome == "refused_by_model"


def test_readiness_record_states_map_from_the_status() -> None:
    cases = {
        STATE_NOT_INSTALLED: OperatorReadinessState.OPTIONAL,
        STATE_READY: OperatorReadinessState.READY,
        STATE_INTEGRITY_FAILED: OperatorReadinessState.ACTION_REQUIRED,
    }
    for state, expected in cases.items():
        snapshot = _service(
            lambda state=state: AiAssistStatus(state, "summary", ("why",), ("do",))
        ).collect()
        record = snapshot.record_for("ai_assist")
        assert record is not None and record.state is expected
        assert (
            ("why",) == record.blocking_reasons
            if expected is OperatorReadinessState.ACTION_REQUIRED
            else not record.blocking_reasons
        )


def test_readiness_states_the_firewall_limit_honestly() -> None:
    attested = (
        _service(lambda: AiAssistStatus(STATE_READY, "ok", egress="attested"))
        .collect()
        .record_for("ai_assist")
    )
    assert attested is not None and "not verified by StableNew" in attested.summary
    missing = _service(lambda: AiAssistStatus(STATE_READY, "ok")).collect().record_for("ai_assist")
    assert missing is not None and "not attested" in missing.summary


def test_a_broken_optional_feature_cannot_break_the_readiness_window() -> None:
    def broken() -> AiAssistStatus:
        raise RuntimeError("boom")

    record = _service(broken).collect().record_for("ai_assist")
    assert record is not None and record.state is OperatorReadinessState.UNKNOWN


def test_default_readiness_projection_is_optional_on_a_clean_machine(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STABLENEW_AI_DIR", str(tmp_path / "ai"))
    record = _service(None).collect().record_for("ai_assist")
    assert record is not None and record.state is OperatorReadinessState.OPTIONAL
    assert not (tmp_path / "ai").exists(), "reading status must not create anything"
