"""Deterministic contracts of the advanced golden-path journeys (PR-TEST-JOURNEYS-832).

No journey is run here (they need a display and take minutes: see ``test_golden_path_journeys``).  These tests pin the
parts every advanced journey relies on: the definitions and their routing, the refusal of physical modes, the loopback
backend's fault, img2img and Forge-identity seams, the isolation of the operator's per-user stores, the registries and
the comparator's longitudinal metrics.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tools.operator_journey.evidence import HOLD, JourneyEvidence
from tools.operator_journey.golden import definitions as defs
from tools.operator_journey.golden.modes import ModeRefusal

ADVANCED_IDS = {"IMG-02", "IMG-03", "VID-02", "VID-03", "LRN-02", "OPS-01"}


# --- definitions and routing -------------------------------------------------------------------------------------------


def test_advanced_journeys_are_defined_as_simulated_only_with_acceptance_criteria() -> None:
    chosen = defs.select("advanced")
    assert {j.id for j in chosen} == ADVANCED_IDS
    assert [j.key for j in chosen] == list(defs.ADVANCED_ORDER)
    for journey in chosen:
        assert journey.physical is False and not journey.physical_acceptance, journey.id
        assert journey.steps and journey.simulated_acceptance, journey.id
    assert len({j.key for j in chosen}) == len(chosen)
    assert len({j.id for j in defs.JOURNEYS.values()}) == len(defs.JOURNEYS)


def test_every_advanced_journey_routes_to_its_own_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.operator_journey.golden import advanced, session

    seen: dict[str, str] = {}

    def fake_run_journey_body(
        journey_id: str, body: Any, config: Any, **kwargs: Any
    ) -> JourneyEvidence:
        seen[journey_id] = body.__name__
        return JourneyEvidence(journey_id=journey_id, backend_mode="simulated")

    monkeypatch.setattr(session, "run_journey_body", fake_run_journey_body)
    for journey in defs.select("advanced"):
        advanced.run_advanced(journey, config=None)  # type: ignore[arg-type]
    assert seen == {
        "OPS-01": "run_ops01",
        "IMG-02": "run_img02",
        "LRN-02": "run_lrn02",
        "VID-03": "run_vid03",
        "IMG-03": "run_img03",
        "VID-02": "run_vid02",
    }


def test_an_unknown_advanced_journey_has_no_runner() -> None:
    from tools.operator_journey.golden import advanced

    bogus = defs.JourneyDef(
        key="not-a-journey",
        id="XXX-01",
        title="t",
        runtime_kind="forge",
        steps=("s",),
        simulated_acceptance=("a",),
        physical_acceptance=(),
        physical=False,
    )
    with pytest.raises(KeyError):
        advanced.run_advanced(bogus, config=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["physical", "readiness"])
@pytest.mark.parametrize(
    "choice", ["advanced", "recovery", "image-edit", "storyboard", "motion-assets"]
)
def test_physical_and_readiness_modes_refuse_every_advanced_journey(
    mode: str, choice: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.operator_journey.golden import suite
    from tools.operator_journey.golden.suite import run_suite

    # pytest itself is refused for physical mode before anything else (covered elsewhere); reach the lane check.
    monkeypatch.setattr(suite, "validate_combination", lambda **_: None)

    with pytest.raises(ModeRefusal, match="no physical lane"):
        run_suite(
            journeys_choice=choice,
            mode=mode,
            driver="windows",
            plan_path=tmp_path / "plan.json",
            evidence_root=tmp_path,
        )
    assert not list(tmp_path.iterdir()), "a refused run must create nothing"


# --- the loopback backend: faults, img2img and the Forge identity ------------------------------------------------------


def _post(url: str, body: dict[str, Any]) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - loopback fake
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _get(url: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - loopback fake
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _png(width: int, height: int) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_fake_backend_answers_img2img_at_the_init_image_size_and_records_the_payload() -> None:
    from PIL import Image

    from tools.operator_journey.fake_a1111 import FakeA1111

    with FakeA1111() as fake:
        status, body = _post(
            fake.base_url + "/sdapi/v1/img2img",
            {"init_images": [_png(96, 64)], "mask": _png(96, 64), "prompt": "a buoy", "seed": 5},
        )
        assert status == 200
        with Image.open(io.BytesIO(base64.b64decode(body["images"][0]))) as image:
            assert image.size == (96, 64)
        assert json.loads(body["info"])["seed"] == 5
        assert [p["prompt"] for p in fake.img2img_payloads] == [
            "a buoy"
        ] and not fake.txt2img_payloads
        assert not fake.unhandled


def test_fake_backend_presents_as_a1111_or_as_forge_to_the_runtime_identity_probe() -> None:
    from src.api.webui_runtime_identity import (
        A1111_WEBUI_IDENTITY,
        FORGE_WEBUI_IDENTITY,
        probe_runtime_identity,
    )
    from tools.operator_journey.fake_a1111 import FakeA1111

    def identity(forge: bool) -> str:
        with FakeA1111(forge=forge) as fake:
            return probe_runtime_identity(
                lambda path: _get(fake.base_url + path)[1]
                if _get(fake.base_url + path)[0] == 200
                else None
            ).identity

    assert identity(False) == A1111_WEBUI_IDENTITY
    assert identity(True) == FORGE_WEBUI_IDENTITY


def test_fake_backend_fault_rules_are_consumed_once_and_logged() -> None:
    from tools.operator_journey.fake_a1111 import FakeA1111

    with FakeA1111() as fake:
        fake.inject("POST", "/sdapi/v1/txt2img", "status:503")
        first, _ = _post(fake.base_url + "/sdapi/v1/txt2img", {"prompt": "x"})
        second, _ = _post(fake.base_url + "/sdapi/v1/txt2img", {"prompt": "x"})
        assert (first, second) == (503, 200)
        assert fake.requests.count(("POST", "/sdapi/v1/txt2img")) == 2
        fake.clear_faults()
        assert not fake.faults


# --- the scripted dialog seam and the driver ---------------------------------------------------------------------------


def test_dialog_seam_answers_folder_choices_from_the_scripted_files() -> None:
    from tkinter import filedialog

    from tools.operator_journey.dialogs import DialogSeam, scripted_dialogs

    original = filedialog.askdirectory
    seam = DialogSeam()
    seam.files.append("C:/test-owned/motion_assets")
    with scripted_dialogs(seam):
        assert filedialog.askdirectory(title="Choose a folder") == "C:/test-owned/motion_assets"
        assert seam.history[-1].kind == "askdirectory"
    assert filedialog.askdirectory is original, "the real dialog must be restored"


def test_a_ttk_flag_is_authoritative_for_whether_a_control_is_disabled() -> None:
    import tkinter as tk
    from tkinter import ttk

    from tools.operator_journey.tk_driver import is_disabled

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display")
    try:
        button = ttk.Button(root, text="Preview", state="disabled")
        assert is_disabled(button)
        button.state(
            ["!disabled"]
        )  # how the product enables it: the configured option stays "disabled"
        assert str(button.cget("state")) == "disabled"
        assert not is_disabled(button)
        button.state(["disabled"])
        assert is_disabled(button)
        classic = tk.Button(root, text="x", state="disabled")
        assert is_disabled(classic)
    finally:
        root.destroy()


# --- isolation of per-user stores --------------------------------------------------------------------------------------


def test_the_workspace_redirects_storyboard_and_motion_stores_and_restores_them(
    tmp_path: Path,
) -> None:
    import src.video.motion_library.config as motion_config
    import src.video.storyboard_store as storyboard_store
    from tools.operator_journey.workspace import OperatorWorkspace

    real = (storyboard_store.default_root, motion_config._user_data_dir)
    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:1")
    with workspace.activate():
        assert (
            Path(storyboard_store.default_root())
            .resolve()
            .is_relative_to((tmp_path / "ws").resolve())
        )
        assert (
            Path(motion_config.config_path()).resolve().is_relative_to((tmp_path / "ws").resolve())
        )
    assert (storyboard_store.default_root, motion_config._user_data_dir) == real


def test_the_guard_reports_a_change_to_the_operators_real_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.operator_journey.workspace as workspace_module

    store = tmp_path / "storyboards"
    store.mkdir()
    settings = tmp_path / "motion_library.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.video.storyboard_store.default_root", lambda: store)
    monkeypatch.setattr("src.video.motion_library.config.config_path", lambda: settings)
    before = workspace_module._user_store_signature()
    (store / "draft.json").write_text("{}", encoding="utf-8")
    settings.write_text('{"root": "x"}', encoding="utf-8")
    after = workspace_module._user_store_signature()
    assert before != after
    assert any(key.startswith("storyboards/") for key in set(after) - set(before))
    assert "motion_library.json" in after


# --- registries --------------------------------------------------------------------------------------------------------


def test_the_coverage_register_names_every_required_workflow_with_physical_status_and_risk() -> (
    None
):
    from tools.operator_journey.golden.registry import (
        coverage_problems,
        coverage_summary,
        load_coverage,
    )

    doc = load_coverage()
    assert coverage_problems(doc) == []
    rows = {row["id"]: row for row in doc["workflows"]}
    required = {
        "model-comparison-and-prompt-model-matrix",
        "lora-and-embedding-experiments",
        "controlnet-reference-maps",
        "smart-review",
        "video-experiment-ratings-and-review",
        "movie-clips-assembly",
        "multi-shot-strict-resume-and-replay",
        "batch-operations",
        "offline-ai-assist",
        "experimental-fun-control",
        "other-qualified-model-families",
    }
    assert required <= set(rows)
    covered = {journey for row in rows.values() for journey in row["journeys"]}
    assert ADVANCED_IDS <= covered
    assert all(row["physical_qualification"] and row["remaining_risk"] for row in rows.values())
    assert not any("PASS" in row["physical_qualification"] for row in rows.values())
    assert sum(coverage_summary(doc).values()) == len(rows)


def test_a_coverage_row_without_physical_status_or_risk_is_a_problem() -> None:
    from tools.operator_journey.golden.registry import coverage_problems, load_coverage

    doc = load_coverage()
    row = dict(doc["workflows"][0])
    row.pop("remaining_risk")
    row.pop("physical_qualification")
    problems = coverage_problems({**doc, "workflows": [row]})
    assert any("remaining_risk" in p for p in problems) and any(
        "physical_qualification" in p for p in problems
    )


def test_the_product_findings_of_the_advanced_journeys_are_registered_and_unrepaired() -> None:
    from tools.operator_journey.golden.registry import finding_problems, load_findings

    doc = load_findings()
    assert finding_problems(doc) == []
    by_id = {f["id"]: f for f in doc["findings"]}
    for fid in ("GP832-F1", "GP832-F2", "GP832-F3", "GP832-F4"):
        assert by_id[fid]["repair"]["status"] == "UNREPAIRED", fid
    assert "parent_job_id" in by_id["GP832-F3"]["observed"]


# --- comparator metrics ------------------------------------------------------------------------------------------------


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": "PASS",
        "checks": [{"phase": "p", "name": "ok", "passed": True, "detail": ""}],
        "action_trace": [
            {"t": 1.0, "action": "invoke"},
            {"t": 4.0, "action": "wait_satisfied"},
            {"t": 4.5, "action": "reclick_after_no_effect", "label": "Save"},
            {"t": 5.0, "action": "maximize_window"},
            {"t": 7.0, "action": "wait_timeout"},
            {"t": 7.2, "action": "scrolled_into_view"},
        ],
        "observations": [
            {"name": "shutdown_latency_s_1", "value": 0.4},
            {"name": "shutdown_latency_s_2", "value": 1.3},
            {"name": "edited_media", "value": {"valid": False}},
        ],
        "captured_errors": {"gui": ["x"], "threads": [], "logs": []},
    }
    base.update(overrides)
    return base


def test_journey_metrics_cover_friction_waiting_errors_and_submissions() -> None:
    from tools.operator_journey.golden.compare import journey_metrics

    checks = [
        {"phase": "p", "name": "ok", "passed": True, "detail": ""},
        {"phase": "p", "name": "preview_queued_nothing", "passed": False, "detail": ""},
        {"phase": "p", "name": "parent_job_recorded", "passed": False, "detail": ""},
        {"phase": "p", "name": "edited_image_decodes", "passed": False, "detail": ""},
    ]
    metrics = journey_metrics(_result(checks=checks), "windows")
    assert metrics["action_count"] == 6
    assert metrics["waiting_time_s"] == 5.0  # 3.0 s before the first wait, 2.0 s before the second
    assert metrics["click_retries"] == 1 and metrics["lost_clicks"] == 1
    assert metrics["forced_scroll_or_resize"] == 2  # maximize + one wheel scroll
    assert metrics["extra_interaction_count"] == 3
    assert metrics["gui_error_count"] == 1
    assert metrics["shutdown_latency_s"] == 1.3
    assert metrics["unexpected_queue_submissions"] == 1
    assert metrics["wrong_job_associations"] == 1
    assert (
        metrics["invalid_artifacts"] == 2
    )  # one invalid media observation + one failed decode check


def test_metrics_missing_from_a_run_are_unknown_not_zero() -> None:
    from tools.operator_journey.golden.compare import journey_metrics

    metrics = journey_metrics(_result(action_trace=[], observations=[]), "tk")
    assert metrics["action_count"] is None and metrics["waiting_time_s"] is None
    assert metrics["lost_clicks"] is None and metrics["shutdown_latency_s"] is None


def test_new_metrics_are_judged_and_truncated_runs_are_inconclusive() -> None:
    from tools.operator_journey.golden.compare import DEGRADED, IMPROVED, INCONCLUSIVE, _judge

    steady = {"timing_factors": [], "verdicts": {"PASS"}}
    assert _judge("lost_clicks", 0, 2, steady)[0] == DEGRADED
    assert _judge("unexpected_queue_submissions", 1, 0, steady)[0] == IMPROVED
    assert _judge("shutdown_latency_s", 1.0, None, steady)[0] == INCONCLUSIVE
    assert (
        _judge("waiting_time_s", 5.0, 9.0, {"timing_factors": ["layout"], "verdicts": {"PASS"}})[0]
        == INCONCLUSIVE
    )
    truncated = {"timing_factors": [], "verdicts": {"PASS", "FAIL"}}
    assert _judge("extra_interaction_count", 1, 9, truncated)[0] == INCONCLUSIVE
    assert _judge("click_retries", 0, 3, truncated)[0] == INCONCLUSIVE


def test_the_comparison_states_its_limitations() -> None:
    from tools.operator_journey.golden.compare import LIMITATIONS, markdown

    assert len(LIMITATIONS) >= 4 and any(
        "not comparable" in item or "like with like" in item for item in LIMITATIONS
    )
    text = markdown(
        {
            "a": {"path": "a", "integrity": "sealed"},
            "b": {"path": "b", "integrity": "sealed"},
            "counts": {"improved": 0, "unchanged": 0, "degraded": 0, "inconclusive": 0},
            "environment": {"differences": []},
            "journeys": {},
            "limitations": list(LIMITATIONS),
        }
    )
    assert "## Limitations" in text and LIMITATIONS[0] in text


def test_a_partial_hold_never_hides_a_failed_check() -> None:
    ev = JourneyEvidence(journey_id="VID-02", backend_mode="simulated")
    ev.check("batch", "ok", True)
    ev.hold_reason = "Blender is not installed"
    assert ev.verdict == HOLD
    # VID-02 only applies its lane-A HOLD when nothing failed, so a failure keeps the journey FAIL.
    failing = JourneyEvidence(journey_id="VID-02", backend_mode="simulated")
    failing.check("batch", "bad", False)
    assert failing.verdict == "FAIL"
