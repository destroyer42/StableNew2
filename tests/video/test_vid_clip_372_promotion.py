"""VID-CLIP-372: implementing the owner's recorded GO decision (2026-11-18) for the A14B / TI2V-5B engines.

Deterministic and GPU-free; no ComfyUI, process or network. Covers: A14B approved and the Make Video default
(graph unchanged), the 720p alternate approved under its own workflow id (1.4.0 stays experimental), per-spec history timeouts,
the owned cold-start readiness window, the A14B launch flag (applied or blocked, never silently missing),
and the warning for an approved workflow on a ComfyUI version it was not qualified on.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.controller.video_workflow_controller import VideoWorkflowController
from src.video import comfy_healthcheck
from src.video.comfy_healthcheck import ComfyHealthCheckTimeout, wait_for_comfy_ready
from src.video.comfy_process_manager import (
    OWNED_COLD_START_MIN_SECONDS,
    ComfyProcessConfig,
    ComfyProcessManager,
)
from src.video.comfy_workflow_backend import ComfyWorkflowVideoBackend
from src.video.managed_comfy_runtime import (
    build_managed_launch_command,
    load_managed_comfy_contract,
    workflow_launch_requirements,
)
from src.video.runtime_version_check import qualified_comfyui_version, runtime_version_warning
from src.video.workflow_catalog import (
    WAN22_720P_HISTORY_TIMEOUT_SECONDS,
    WAN22_720P_VERSION,
    WAN22_720P_WORKFLOW_ID,
    WAN22_720P_WORKFLOW_VERSION,
    WAN22_FRAMES_VERSION,
)
from src.video.workflow_catalog_wan_a14b import (
    WAN_A14B_ID,
    WAN_A14B_REQUIRED_LAUNCH_FLAGS,
    WAN_A14B_VERSION,
)
from src.video.workflow_picker import approved_in_preference_order, recommended_workflow_id
from src.video.workflow_preflight import (
    GATE_ADVISORY,
    GATE_BLOCKED,
    GATE_OK,
    evaluate_workflow_preflight,
)
from src.video.workflow_readiness import required_launch_flags
from src.video.workflow_registry import build_default_workflow_registry, latest_spec_per_workflow
from src.video.workflow_tasks import TASK_ANIMATE, choose_workflow
from tests.video.test_comfy_process_manager import (
    _FakeManaged,
    _manager,
    fake_comfy_command,
)
from tests.video.test_pr_vid_ux_311_preflight import _gate, _probes
from tests.video.test_vid_clip_370_candidate_specs import (
    _a14b_backend,
    _a14b_info,
    _a14b_request,
    _controller,
    _fake_export,
    _FramesFake,
)
from tests.video.test_wan22_experimental_workflow import WAN_ID

PINNED_MEMORY = "--disable-pinned-memory"


@pytest.fixture
def _no_encode(monkeypatch):
    monkeypatch.setattr("src.video.frames_out.export_image_sequence_video", _fake_export)
    monkeypatch.setattr(
        "src.video.comfy_workflow_backend.write_video_container_metadata", lambda *_a, **_k: True
    )


def _spec(workflow_id: str, version: str):
    return build_default_workflow_registry().get(workflow_id, version, allow_experimental=True)


# --- governance and the Make Video default ------------------------------------------------------


def test_a14b_is_approved_the_declared_make_video_default_and_runs_without_an_opt_in() -> None:
    spec = build_default_workflow_registry().get(
        WAN_A14B_ID, WAN_A14B_VERSION
    )  # no allow_experimental

    assert spec.governance_state == "approved" and not spec.is_experimental and spec.is_runnable
    assert "xperimental" not in spec.display_name
    assert spec.governance_notes.startswith("APPROVED")
    assert (
        "not qualified" in spec.governance_notes.lower()
    )  # approval is not a ledger qualification
    assert spec.backend_defaults["make_video_default"] is True
    # Approval changed governance only: the pinned graph is the 321F graph (digest pinned in
    # test_pr_comfy_runtime_100_workflow_versions) and the launch requirement is unchanged.
    assert tuple(spec.backend_defaults["runtime_policy"]["required_launch_flags"]) == (
        PINNED_MEMORY,
    )


def test_the_make_video_default_is_a14b_through_every_chooser() -> None:
    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=None, output_dir="output")
    )
    records = controller.list_workflow_specs()

    assert recommended_workflow_id(records) == WAN_A14B_ID
    form = controller.build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)
    choice = choose_workflow(TASK_ANIMATE, records)
    assert choice is not None and choice.workflow_id == WAN_A14B_ID and not choice.needs_opt_in
    # The operator's own pick still wins over the default.
    kept = choose_workflow(TASK_ANIMATE, records, pinned_workflow_id=WAN_ID)
    assert kept is not None and kept.workflow_id == WAN_ID


def test_the_default_is_declared_not_an_accident_of_catalog_order() -> None:
    records = [
        {"workflow_id": "a_first", "governance_state": "approved"},
        {"workflow_id": "z_default", "governance_state": "approved", "make_video_default": True},
        {"workflow_id": "m_exp", "governance_state": "experimental", "experimental": True},
        {
            "workflow_id": "b_exp_default",
            "governance_state": "experimental",
            "experimental": True,
            "make_video_default": True,
        },
    ]

    assert [r["workflow_id"] for r in approved_in_preference_order(records)] == [
        "z_default",
        "a_first",
    ]
    assert recommended_workflow_id(records) == "z_default"
    # An experimental workflow is never the default, even when it carries the flag.
    assert recommended_workflow_id(records[2:]) == ""


def test_the_ti2v_480p_version_is_still_the_one_the_picker_offers_and_old_720p_stays_experimental() -> (
    None
):
    registry = build_default_workflow_registry()
    ti2v = [s for s in registry.list_offerable_specs("comfy") if s.workflow_id == WAN_ID]

    assert [s.workflow_version for s in latest_spec_per_workflow(ti2v)] == [WAN22_FRAMES_VERSION]
    assert _spec(WAN_ID, WAN22_720P_VERSION).governance_state == "experimental"
    assert _spec(WAN_ID, WAN22_FRAMES_VERSION).governance_state == "approved"


def test_720p_is_its_own_approved_workflow_id_so_both_resolutions_are_picker_entries() -> None:
    spec = build_default_workflow_registry().get(  # no experimental opt-in needed
        WAN22_720P_WORKFLOW_ID, WAN22_720P_WORKFLOW_VERSION
    )
    assert spec.governance_state == "approved" and not spec.is_experimental and spec.is_runnable
    assert spec.pinned_revision == f"catalog:{WAN22_720P_WORKFLOW_ID}@{WAN22_720P_WORKFLOW_VERSION}"
    assert "720p" in spec.display_name and "xperimental" not in spec.display_name
    assert spec.governance_notes.startswith("APPROVED")
    assert "not QUALIFIED by the qualification ledger" in spec.governance_notes
    assert spec.backend_defaults["runtime_policy"]["release_owned_runtime_after_job"] is True
    assert "make_video_default" not in spec.backend_defaults  # an alternate, never the default

    listed = _controller().list_workflow_specs()
    records = {r["workflow_id"]: r for r in listed}
    assert (records[WAN_ID]["workflow_version"], records[WAN_ID]["governance_state"]) == (
        WAN22_FRAMES_VERSION,
        "approved",
    )
    assert (
        records[WAN22_720P_WORKFLOW_ID]["workflow_version"],
        records[WAN22_720P_WORKFLOW_ID]["governance_state"],
    ) == (WAN22_720P_WORKFLOW_VERSION, "approved")
    assert records[WAN22_720P_WORKFLOW_ID]["experimental"] is False
    assert recommended_workflow_id(listed) == WAN_A14B_ID  # 720p never displaces the default
    form = _controller().build_default_form_state()
    assert (form["workflow_id"], form["workflow_version"]) == (WAN_A14B_ID, WAN_A14B_VERSION)


def test_the_720p_workflow_is_the_1_3_0_graph_at_720p_targets_with_the_longer_timeout() -> None:
    base = _spec(WAN_ID, WAN22_FRAMES_VERSION)
    new = _spec(WAN22_720P_WORKFLOW_ID, WAN22_720P_WORKFLOW_VERSION)
    old_720p = _spec(WAN_ID, WAN22_720P_VERSION)

    # The same graph-defining content as the 1.4.0 eval candidate it supersedes for operators.
    for key in ("source_preparation", "output_policy", "frame_count_policy", "resource_readiness"):
        assert new.backend_defaults[key] == old_720p.backend_defaults[key]
    assert new.input_bindings == old_720p.input_bindings
    assert new.output_bindings == old_720p.output_bindings
    assert new.dependency_specs == old_720p.dependency_specs
    prep = new.backend_defaults["source_preparation"]
    assert prep["portrait_target"] == {"width": 704, "height": 1280}
    assert prep["landscape_target"] == {"width": 1280, "height": 704}
    assert base.backend_defaults["source_preparation"]["portrait_target"] == {
        "width": 480,
        "height": 832,
    }
    assert new.backend_defaults["history_timeout_seconds"] == WAN22_720P_HISTORY_TIMEOUT_SECONDS


def test_an_eval_arm_naming_only_another_workflow_gets_that_workflows_offered_version(
    tmp_path: Path,
) -> None:
    """The default form's version belongs to the default workflow (A14B 1.0.0), never to another id."""

    from src.video.video_eval_suite import EvalArm

    seen: dict[str, Any] = {}

    class _Builder:
        def freeze_inputs(self, _image, form):
            seen.update(form)
            raise RuntimeError("stop after the form is merged")

    controller = VideoWorkflowController(
        app_controller=SimpleNamespace(job_service=None, output_dir=str(tmp_path))
    )
    controller._njr_builder = _Builder()  # type: ignore[assignment]
    case = SimpleNamespace(image_path=tmp_path / "x.png", prompt="p", negative_prompt="")

    arm = EvalArm(
        arm_id="ti2v", label="ti2v", backend="video_workflow", overrides={"workflow_id": WAN_ID}
    )
    with pytest.raises(RuntimeError, match="stop after"):
        controller._build_workflow_eval_job(case, arm, 1)

    assert (seen["workflow_id"], seen["workflow_version"]) == (WAN_ID, WAN22_FRAMES_VERSION)


# --- per-spec history timeouts ------------------------------------------------------------------


def test_each_spec_declares_the_history_timeout_its_eval_evidence_supports() -> None:
    # VID-CLIP-371 wall times per clip: TI2V 480p 32-132 s, A14B 140-176 s, TI2V 720p 47-622 s.
    assert _spec(WAN_ID, WAN22_FRAMES_VERSION).backend_defaults["history_timeout_seconds"] == 600
    assert _spec(WAN_ID, WAN22_720P_VERSION).backend_defaults["history_timeout_seconds"] == (
        WAN22_720P_HISTORY_TIMEOUT_SECONDS
    )
    assert _spec(WAN22_720P_WORKFLOW_ID, WAN22_720P_WORKFLOW_VERSION).backend_defaults[
        "history_timeout_seconds"
    ] == (WAN22_720P_HISTORY_TIMEOUT_SECONDS)
    assert WAN22_720P_HISTORY_TIMEOUT_SECONDS == 1200 > 622  # the slowest observed clip
    assert (
        _spec(WAN_A14B_ID, WAN_A14B_VERSION).backend_defaults["history_timeout_seconds"]
        == 1200
        > 176
    )


def test_the_backend_waits_for_the_specs_own_limit_not_one_global_value(tmp_path: Path) -> None:
    backend = ComfyWorkflowVideoBackend(client=object(), history_timeout=120.0)

    assert backend._history_timeout_for(_spec(WAN_ID, WAN22_FRAMES_VERSION)) == 600
    assert backend._history_timeout_for(_spec(WAN_ID, WAN22_720P_VERSION)) == 1200
    assert backend._history_timeout_for(_spec(WAN_A14B_ID, WAN_A14B_VERSION)) == 1200
    # A spec that declares nothing keeps the backend default.
    assert backend._history_timeout_for(SimpleNamespace(backend_defaults={})) == 120.0


# --- cold-start readiness of an owned runtime ---------------------------------------------------


def test_an_owned_cold_start_waits_at_least_the_floor_and_stops_waiting_when_the_child_exits(
    monkeypatch,
) -> None:
    observed: dict[str, Any] = {}

    def wait(_url: str, *, timeout: float, poll_interval: float, abort_if=None) -> bool:
        observed.update(timeout=timeout, abort_if=abort_if)
        return True

    monkeypatch.setattr("src.video.comfy_process_manager.wait_for_comfy_ready", wait)
    manager = _manager(
        ComfyProcessConfig(
            command=["python", "main.py"],
            base_url="http://127.0.0.1:9000",
            startup_timeout_seconds=30.0,
        )
    )
    manager.start()

    assert manager.check_health() is True
    assert observed["timeout"] == OWNED_COLD_START_MIN_SECONDS == 180.0
    assert observed["abort_if"]() is None  # the fake child is alive

    _FakeManaged.instances[-1].process._returncode = 3  # the child died while we were waiting
    assert "exited (return code 3)" in observed["abort_if"]()


def test_a_longer_configured_wait_is_kept_and_an_unowned_endpoint_uses_the_configured_value(
    monkeypatch,
) -> None:
    waits: list[float] = []

    def wait(_url: str, *, timeout: float, poll_interval: float, **_kw: Any) -> bool:
        waits.append(timeout)
        return True

    monkeypatch.setattr("src.video.comfy_process_manager.wait_for_comfy_ready", wait)
    config = ComfyProcessConfig(
        command=["python", "main.py"],
        base_url="http://127.0.0.1:9000",
        startup_timeout_seconds=300.0,
    )
    owned = _manager(config)
    owned.start()
    owned.check_health()
    unowned = ComfyProcessManager(dataclasses.replace(config, startup_timeout_seconds=30.0))
    unowned.check_health()

    assert waits == [300.0, 30.0]
    assert unowned.readiness_timeout_seconds == 30.0


def test_wait_for_comfy_ready_aborts_at_once_with_the_reason_instead_of_running_out_the_clock(
    monkeypatch,
) -> None:
    def no_network(*_a: Any, **_k: Any):
        raise AssertionError("must not probe once the owner says the wait is pointless")

    monkeypatch.setattr(comfy_healthcheck.requests, "get", no_network)

    with pytest.raises(ComfyHealthCheckTimeout, match="exited"):
        wait_for_comfy_ready(
            "http://127.0.0.1:1", timeout=600.0, abort_if=lambda: "the process exited"
        )


def test_wait_for_comfy_ready_without_an_abort_callback_is_unchanged(monkeypatch) -> None:
    class _Ok:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {}

    monkeypatch.setattr(comfy_healthcheck.requests, "get", lambda *_a, **_k: _Ok())

    assert wait_for_comfy_ready("http://127.0.0.1:1", timeout=5.0) is True


# --- the A14B launch flag is applied or blocked, never silently missing -------------------------


def test_a14b_declares_the_flag_and_a_command_without_it_gets_it_appended_at_launch(
    tmp_path: Path,
) -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    assert required_launch_flags(spec) == WAN_A14B_REQUIRED_LAUNCH_FLAGS == (PINNED_MEMORY,)
    base = fake_comfy_command(tmp_path / "src", PINNED_MEMORY)  # an owner command lacking the flag
    assert PINNED_MEMORY not in base
    manager = _manager(ComfyProcessConfig(command=list(base), working_dir=str(tmp_path / "src")))

    manager.start(required_flags=required_launch_flags(spec))

    assert PINNED_MEMORY in _FakeManaged.instances[-1].command
    assert PINNED_MEMORY in manager.verified_launch_flags


def test_a_managed_command_carries_the_flag_from_the_contract_for_any_workflow(
    tmp_path: Path,
) -> None:
    contract = load_managed_comfy_contract()
    command = build_managed_launch_command(
        contract,
        install_dir=tmp_path / contract.install_dir_name,
        runtime_dir=tmp_path / "rt",
        port=8188,
    )

    assert PINNED_MEMORY in command
    assert PINNED_MEMORY in workflow_launch_requirements(command, (), contract)


def test_preflight_blocks_a14b_when_the_runtime_cannot_take_the_flag_and_passes_when_it_can(
    tmp_path: Path,
) -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)

    blocked = evaluate_workflow_preflight(
        spec, _probes(spec, command=fake_comfy_command(tmp_path / "old"))
    )
    gate = _gate(blocked, "launch_flags")
    assert gate.state == GATE_BLOCKED and PINNED_MEMORY in gate.detail and not blocked.queueable

    ok = evaluate_workflow_preflight(
        spec, _probes(spec, command=fake_comfy_command(tmp_path / "new", PINNED_MEMORY))
    )
    assert _gate(ok, "launch_flags").state == GATE_OK
    assert "StableNew will apply" in _gate(ok, "launch_flags").detail

    external = evaluate_workflow_preflight(spec, _probes(spec, command=(), state="healthy"))
    assert (
        _gate(external, "launch_flags").state == GATE_BLOCKED
    )  # an external runtime proves nothing


# --- a warning for an approved workflow on a runtime it was not qualified on --------------------


def test_the_warning_names_both_versions_and_only_fires_for_approved_workflows_on_a_mismatch() -> (
    None
):
    a14b = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    assert qualified_comfyui_version(a14b) == "0.38.0"

    assert runtime_version_warning(a14b, "0.38.0") is None
    assert runtime_version_warning(a14b, "") is None  # unobserved is not a mismatch
    assert runtime_version_warning(a14b, None) is None
    text = runtime_version_warning(a14b, "0.37.0")
    assert text is not None and "0.38.0" in text and "0.37.0" in text and WAN_A14B_ID in text
    # TI2V-5B 1.3.0 was requalified on 0.38.0 too; its 0.3.65-era experimental versions never warn.
    assert runtime_version_warning(_spec(WAN_ID, WAN22_FRAMES_VERSION), "0.40.0") is not None
    assert runtime_version_warning(_spec(WAN_ID, "1.1.0"), "0.38.0") is None
    assert (
        runtime_version_warning(_spec(WAN_ID, WAN22_720P_VERSION), "0.37.0") is None
    )  # experimental
    new_720p = _spec(WAN22_720P_WORKFLOW_ID, WAN22_720P_WORKFLOW_VERSION)
    assert runtime_version_warning(new_720p, "0.37.0") is not None  # approved, qualified on 0.38.0
    assert runtime_version_warning(new_720p, "0.38.0") is None


def test_execution_records_the_warning_beside_the_actual_runtime_and_still_runs(
    tmp_path: Path, _no_encode
) -> None:
    stats = {**_stats_for_a14b(), "system": {"comfyui_version": "0.37.0"}}
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info(), stats=stats)

    result = _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path, opt_in=False))

    assert result is not None and len(client.queued) == 1  # a warning, never a block
    warning = result.backend_metadata["runtime_version_warning"]
    assert "0.38.0" in warning and "0.37.0" in warning
    assert result.backend_metadata["actual_runtime"]["comfyui_version"] == "0.37.0"


def test_execution_on_the_qualified_version_records_no_warning(tmp_path: Path, _no_encode) -> None:
    stats = {**_stats_for_a14b(), "system": {"comfyui_version": "0.38.0"}}
    client = _FramesFake(tmp_path, save_node="16", info=_a14b_info(), stats=stats)

    result = _a14b_backend(client, tmp_path).execute(None, _a14b_request(tmp_path, opt_in=False))

    assert result is not None and "runtime_version_warning" not in result.backend_metadata


def _stats_for_a14b() -> dict[str, Any]:
    from tests.video.test_wan22_experimental_workflow import _stats

    return _stats(free_mib=11800.0)


def test_preflight_shows_an_advisory_gate_for_a_serving_runtime_of_another_version() -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    other = {"devices": [], "system": {"comfyui_version": "0.37.0"}}
    same = {"devices": [], "system": {"comfyui_version": "0.38.0"}}

    flagged = evaluate_workflow_preflight(
        spec,
        _probes(spec, command=("python", "main.py", PINNED_MEMORY), state="healthy", stats=other),
    )
    gate = _gate(flagged, "runtime_version")
    assert gate.state == GATE_ADVISORY and "0.37.0" in gate.detail and gate not in flagged.blocking

    clean = evaluate_workflow_preflight(
        spec,
        _probes(spec, command=("python", "main.py", PINNED_MEMORY), state="healthy", stats=same),
    )
    assert "runtime_version" not in {g.id for g in clean.gates}


def test_preflight_warns_before_launch_when_the_managed_install_is_another_version(
    tmp_path: Path,
) -> None:
    spec = _spec(WAN_A14B_ID, WAN_A14B_VERSION)
    contract = load_managed_comfy_contract()
    install = tmp_path / contract.install_dir_name
    command = tuple(
        build_managed_launch_command(
            contract, install_dir=install, runtime_dir=tmp_path / "rt", port=8188
        )
    )
    older = dataclasses.replace(contract, version="0.37.0")

    same_version = evaluate_workflow_preflight(
        spec, _probes(spec, command=command, managed=contract)
    )
    drifted = evaluate_workflow_preflight(spec, _probes(spec, command=command, managed=older))

    assert "runtime_version" not in {g.id for g in same_version.gates}
    assert _gate(drifted, "runtime_version").state == GATE_ADVISORY
