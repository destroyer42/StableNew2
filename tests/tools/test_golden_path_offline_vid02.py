"""VID-02's offline physical lane (QUAL-922): plan shape, readiness, gating and the frozen inputs it honours.

Deterministic and CPU-only: no display, no Blender, no FFmpeg, no model, no backend, no GPU, no network.  Probes are
injected; the journey body is exercised only up to the point where the GUI would start (its gates, its frozen-input readers
and its pure acceptance rules).  A real run needs the owner's frozen plan, an authorization naming its digest and a typed
launch, and is refused under pytest and CI.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.operator_journey.control import JourneyAbort, JourneyHold
from tools.operator_journey.evidence import HOLD, NO_GO, PASS, JourneyEvidence
from tools.operator_journey.golden import definitions, offline, physical
from tools.operator_journey.golden.frozen import PlanGate, PlanMismatch, input_problems
from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.golden.modes import ModeRefusal, validate_combination
from tools.operator_journey.golden.physical import confirmation_phrase, run_physical
from tools.operator_journey.golden.plan import (
    build_plan,
    environment_diffs,
    shape_problems,
)
from tools.operator_journey.golden.readiness import ReadinessContext, evaluate_readiness

KEY = "motion-assets"
LIMITS = {
    "max_jobs": 1,
    "max_artifacts": 8,
    "max_width": 1024,
    "max_height": 1024,
    "max_steps": 30,
    "max_frames": 33,
    "timeout_seconds": 900,
    "min_available_ram_gb": 8,
    "max_commit_gb": 60,
    "max_vram_used_mib": 3000,
    "min_free_disk_gb": 5,
}
GPU = {
    "name": "Test GPU",
    "driver": "1.0",
    "total_mib": 12000.0,
    "used_mib": 800.0,
    "free_mib": 11000.0,
    "uuid": "GPU-1",
}
MEM = {"available_gb": 30.0, "total_gb": 64.0, "commit_used_gb": 20.0, "commit_limit_gb": 100.0}
BLENDER_VERSION = "4.5.9"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _forbidden(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("an offline journey must not touch this")


def make_probes(**over: Any) -> HostProbes:
    values: dict[str, Any] = {
        "repo_sha": lambda: "a" * 40,
        "gpu": lambda: dict(GPU),
        "memory": lambda: dict(MEM),
        "disk_free_gb": lambda _p: 500.0,
        "endpoint": _forbidden,  # no endpoint of any kind is probed by an offline lane
        "processes": lambda: [],
        "file_sha256": _sha,
        "blender": lambda exe: {"version": BLENDER_VERSION, "sha256": _sha(Path(exe))},
        "ffmpeg": lambda: True,
        "python": lambda: "3.14.2",
        "hostname": lambda: "testhost",
        "os_name": lambda: "TestOS 1",
    }
    values.update(over)
    return HostProbes(**values)


def make_ctx(probes: HostProbes) -> ReadinessContext:
    # A runtime/workflow/launch collaborator would only be consulted for a GPU journey; none may be here.
    return ReadinessContext(
        probes=probes,
        workflow_info=_forbidden,
        comfy_launch=_forbidden,
        forge_identity=_forbidden,
        video_gates=_forbidden,
    )


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    (root / "nested").mkdir(parents=True)
    (root / "walk.bvh").write_text("HIERARCHY walk", encoding="utf-8")
    (root / "run.bvh").write_text("HIERARCHY run", encoding="utf-8")
    (root / "nested" / "dance.fbx").write_bytes(b"Kaydara FBX Binary")
    (root / "notes.txt").write_text("not a motion asset", encoding="utf-8")
    return root


@pytest.fixture
def blender_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "blender" / "blender.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ not really blender")
    return exe


def offline_target(assets: Path, blender_exe: Path, **over: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "lane": "offline",
        "blender": {
            "executable": str(blender_exe),
            "version": BLENDER_VERSION,
            "sha256": _sha(blender_exe),
        },
        "asset_directory": str(assets),
        "source_assets": [
            {"path": str(p), "sha256": _sha(p)} for p in sorted(assets.rglob("*")) if p.is_file()
        ],
        "job_count": 0,
        "expected_artifacts": 4,
        "inputs": {
            "render_profile": {
                "profile_policy": "auto",
                "camera": "side",
                "camera_mode": "tracking",
                "root_motion": "in_place",
                "orientation": "landscape",
                "start_seconds": "0.5",
                "frames": 25,
            },
            "frame_window": {"start": 0.5, "end": 2.0, "convert": True},
            "driving_workflow": {
                "id": "wan22_fun_control_5b_canny_i2v_v1",
                "version": "1.0.0",
            },
        },
    }
    target.update(over)
    return target


def freeze(tmp_path: Path, assets: Path, blender_exe: Path, probes: HostProbes | None = None):
    probes = probes or make_probes()
    plan = build_plan(
        targets={KEY: offline_target(assets, blender_exe)},
        limits=dict(LIMITS),
        evidence_dir=str(tmp_path),
        probes=probes,
    )
    return plan, probes


def authorize(plan: dict[str, Any]) -> dict[str, Any]:
    plan = deepcopy(plan)
    plan["authorization"] = {
        "state": "approved",
        "approved_by": "owner",
        "plan_digest": plan["digest"],
        "journeys": [KEY],
        "expires_at": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
    }
    return plan


def gate(report: dict[str, Any], gate_id: str) -> dict[str, str]:
    return next(g for g in report["gates"] if g["id"] == gate_id)


def refreeze(plan: dict[str, Any], mutate: Any) -> dict[str, Any]:
    """The plan with ``mutate(target)`` applied and the digest recomputed (as if the owner had frozen that spec)."""

    from tools.operator_journey.golden.plan import plan_digest

    edited = deepcopy(plan)
    mutate(edited["targets"][KEY])
    edited["digest"] = plan_digest(edited)
    return edited


# --- definitions -------------------------------------------------------------------------------------------------


def test_vid02_has_an_offline_physical_lane_with_its_acceptance_tuple() -> None:
    journey = definitions.JOURNEYS[KEY]
    assert journey.physical is True and journey.offline is True and journey.runtime_kind == "none"
    assert journey.physical_acceptance == (
        "originals byte-identical",
        "Blender executable identity and version",
        "converted MP4 hash and decode",
        "library entries survive a restart",
        "driving-clip SHA-256 recorded in the job record",
        "Prepare Motion Source output content-addressed, with the frame window recorded",
        "no generative GPU execution",
    )
    assert definitions.OFFLINE_KEYS == {KEY}
    # no GPU journey became offline, and "all" stays the three comparable GPU journeys
    assert not any(definitions.JOURNEYS[k].offline for k in ("image", "video", "learning"))
    assert [j.id for j in definitions.select("all")] == ["IMG-01", "VID-01", "LRN-01"]
    assert offline.is_offline(KEY) and not offline.is_offline("image")


# --- physical refusal under pytest and CI -------------------------------------------------------------------------


def test_physical_vid02_is_refused_under_pytest_and_ci() -> None:
    with pytest.raises(ModeRefusal, match="refused under pytest"):
        validate_combination(mode="physical", driver="windows", plan="p.json", env={})
    # CI is refused for the driver first and for the mode itself (the tk driver reaches the mode rule)
    with pytest.raises(ModeRefusal, match="never used in CI"):
        validate_combination(mode="physical", driver="windows", plan="p.json", env={"CI": "true"})
    with pytest.raises(ModeRefusal, match="physical execution is refused in CI"):
        validate_combination(mode="physical", driver="tk", plan="p.json", env={"CI": "true"})


def test_run_suite_refuses_physical_vid02_under_pytest_before_anything_is_created(
    tmp_path: Path,
) -> None:
    from tools.operator_journey.golden.suite import run_suite

    with pytest.raises(ModeRefusal, match="refused under pytest"):
        run_suite(
            journeys_choice=KEY,
            mode="physical",
            driver="windows",
            plan_path=tmp_path / "plan.json",
            evidence_root=tmp_path / "ev",
        )
    assert not (tmp_path / "ev").exists()


def test_vid02_is_no_longer_refused_as_laneless_but_still_needs_a_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the mode gates the physical lane is reached, and with no readable plan it is a HOLD that runs nothing."""

    from tools.operator_journey.golden import suite

    monkeypatch.setattr(suite, "validate_combination", lambda **_: None)
    ran: list[str] = []
    monkeypatch.setattr(physical, "real_executor", lambda *a, **k: ran.append("ran"))
    verdict, run_dir = suite.run_suite(
        journeys_choice=KEY,
        mode="physical",
        driver="windows",
        plan_path=tmp_path / "missing-plan.json",
        evidence_root=tmp_path / "ev",
    )
    assert verdict == HOLD and ran == []
    assert "plan cannot be read" in (run_dir / "summary.md").read_text(encoding="utf-8")


# --- plan shape --------------------------------------------------------------------------------------------------


def test_a_valid_offline_target_needs_no_model_or_runtime(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, _ = freeze(tmp_path, assets, blender_exe)
    target = plan["targets"][KEY]
    assert "runtime" not in target and "model" not in target
    assert shape_problems(plan) == []
    assert plan["expected_endpoints"] == [] and plan["job_count"] == 0
    # the converter and the folder listing are frozen into the environment the run is compared against
    env = plan["environment"]["targets"][KEY]
    assert env["blender"] == {"version": BLENDER_VERSION, "sha256": _sha(blender_exe)}
    assert sorted(Path(p).name for p in env["asset_listing"]) == [
        "dance.fbx",
        "notes.txt",
        "run.bvh",
        "walk.bvh",
    ]
    assert set(env["sources"].values()) == {_sha(p) for p in assets.rglob("*") if p.is_file()}


def test_build_plan_freezes_the_default_inputs_when_the_spec_omits_them(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    spec = offline_target(assets, blender_exe)
    del spec["inputs"]
    plan = build_plan(
        targets={KEY: spec}, limits=dict(LIMITS), evidence_dir=str(tmp_path), probes=make_probes()
    )
    assert plan["targets"][KEY]["inputs"] == offline.default_inputs()
    assert shape_problems(plan) == []


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda t: t.pop("lane"), 'must declare "lane": "offline"'),
        (lambda t: t.pop("blender"), "Blender identity"),
        (lambda t: t["blender"].pop("sha256"), "Blender identity"),
        (lambda t: t["blender"].update(sha256="nothex"), "Blender identity"),
        (lambda t: t["blender"].update(version=""), "Blender identity"),
        (lambda t: t.pop("asset_directory"), "asset directory is required"),
        (lambda t: t.update(source_assets=[]), "SHA-256 of every source asset"),
        (lambda t: t.pop("source_assets"), "SHA-256 of every source asset"),
        (lambda t: t["source_assets"][0].pop("sha256"), "needs a path and a SHA-256"),
        (lambda t: t["source_assets"][0].update(sha256="ab" * 3), "needs a path and a SHA-256"),
        (lambda t: t["source_assets"].append(dict(t["source_assets"][0])), "listed twice"),
        (
            lambda t: t["source_assets"][0].update(
                path=str(Path(t["asset_directory"]).parent / "x")
            ),
            "outside the asset directory",
        ),
        (
            lambda t: t.update(runtime={"kind": "comfy", "ownership": "managed"}),
            "declares no runtime or model",
        ),
        (lambda t: t.update(model={"name": "m"}), "declares no runtime or model"),
        (lambda t: t.update(job_count=1), "submits no job"),
        (lambda t: t.pop("inputs"), "does not bind"),
        (lambda t: t["inputs"].pop("render_profile"), "render_profile"),
        (lambda t: t["inputs"]["render_profile"].pop("camera"), "render_profile missing: camera"),
        (lambda t: t["inputs"]["render_profile"].update(frames=0), "frames must be a positive"),
        (lambda t: t["inputs"]["render_profile"].update(frames=True), "frames must be a positive"),
        (lambda t: t["inputs"]["render_profile"].update(frames=99), "exceeds max_frames"),
        (lambda t: t["inputs"]["render_profile"].update(start_seconds="-1"), "start_seconds"),
        (lambda t: t["inputs"].pop("frame_window"), "frame_window"),
        (lambda t: t["inputs"]["frame_window"].update(end=0.5), "end must be null or greater"),
        (lambda t: t["inputs"]["frame_window"].update(start=-1), "start must be a number"),
        (lambda t: t["inputs"]["frame_window"].update(convert="yes"), "convert must be true"),
        (lambda t: t["inputs"].pop("driving_workflow"), "driving_workflow"),
    ],
)
def test_malformed_offline_targets_are_invalid(
    tmp_path: Path, assets: Path, blender_exe: Path, mutate: Any, message: str
) -> None:
    plan, _ = freeze(tmp_path, assets, blender_exe)
    problems = shape_problems(refreeze(plan, mutate))
    assert any(message in p for p in problems), problems


def test_an_edited_offline_plan_fails_its_digest(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, _ = freeze(tmp_path, assets, blender_exe)
    plan["targets"][KEY]["inputs"]["render_profile"]["frames"] = 17
    assert any("digest" in p for p in shape_problems(plan))


def test_the_offline_form_never_relaxes_a_gpu_journey(tmp_path: Path) -> None:
    """Offline-ness belongs to the journey definition: a GPU journey that claims it is still missing its runtime and model."""

    base = {"lane": "offline", "job_count": 0, "expected_artifacts": 0}
    for key in ("image", "video", "learning"):
        plan = build_plan(
            targets={key: dict(base)},
            limits=dict(LIMITS),
            evidence_dir=str(tmp_path),
            probes=make_probes(),
        )
        problems = shape_problems(plan)
        assert any("runtime" in p for p in problems), (key, problems)
        if key != "video":
            assert any("installed model with a SHA-256" in p for p in problems), (key, problems)
        else:
            assert any("workflow id and version" in p for p in problems), (key, problems)
    # and an offline-looking VID-02 target cannot smuggle a runtime in
    assert not offline.is_offline("video") and not offline.is_offline("learning")


def test_the_gpu_journeys_still_require_every_limit(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    """The offline lane relaxes no limit: a plan without the GPU ceiling is as invalid as it ever was."""

    plan, _ = freeze(tmp_path, assets, blender_exe)
    from tools.operator_journey.golden.plan import plan_digest

    broken = deepcopy(plan)
    del broken["limits"]["max_vram_used_mib"]
    broken["digest"] = plan_digest(broken)
    assert any("max_vram_used_mib" in p for p in shape_problems(broken))


# --- frozen inputs are honoured ----------------------------------------------------------------------------------


def test_every_operator_value_is_read_from_the_frozen_target(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, _ = freeze(tmp_path, assets, blender_exe)
    frozen = offline.read_offline_inputs(plan["targets"][KEY])
    assert frozen.asset_directory == assets
    assert (
        frozen.blender_executable == str(blender_exe) and frozen.blender_version == BLENDER_VERSION
    )
    assert frozen.blender_sha256 == _sha(blender_exe)
    assert frozen.assets == {str(p): _sha(p) for p in sorted(assets.rglob("*")) if p.is_file()}
    assert frozen.render_profile == {
        "profile_policy": "auto",
        "camera": "side",
        "camera_mode": "tracking",
        "root_motion": "in_place",
        "orientation": "landscape",
        "start_seconds": "0.5",
        "frames": 25,
    }
    assert (frozen.window_start, frozen.window_end, frozen.window_convert) == ("0.5", "2", True)
    assert (frozen.workflow_id, frozen.workflow_version) == (
        "wan22_fun_control_5b_canny_i2v_v1",
        "1.0.0",
    )
    # an open-ended window is the empty "End" the panel expects
    open_ended = deepcopy(plan["targets"][KEY])
    open_ended["inputs"]["frame_window"] = {"start": 0, "end": None, "convert": False}
    assert offline.read_offline_inputs(open_ended).window_end == ""
    assert offline.read_offline_inputs(open_ended).window_start == "0"


def test_an_invalid_target_cannot_be_read_as_inputs(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    with pytest.raises(ValueError, match="Blender identity"):
        offline.read_offline_inputs(offline_target(assets, blender_exe, blender={}))


def test_the_plan_binds_the_inputs_it_needs(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    target = offline_target(assets, blender_exe)
    assert input_problems(KEY, target) == []
    target["inputs"] = {}
    assert input_problems(KEY, target)


def _fake_dialog(offered_frames: list[int]):
    """A stand-in for the Batch Convert dialog's own variables and session (no Tk)."""

    class Var:
        def __init__(self, value: Any = "") -> None:
            self.value = value

        def get(self) -> Any:
            return self.value

        def set(self, value: Any) -> None:
            self.value = value

    options = SimpleNamespace(
        profile_policy="auto",
        camera="front",
        camera_mode="static",
        root_motion="preserve",
        orientation="portrait",
        start_seconds="0",
        frames="",
    )
    dialog = SimpleNamespace(
        policy_var=Var(),
        camera_var=Var(),
        mode_var=Var(),
        root_var=Var(),
        orient_var=Var(),
        start_var=Var("0"),
        frames_combo=SimpleNamespace(),
        session=SimpleNamespace(
            options=options, view=lambda: SimpleNamespace(legal_frames=tuple(offered_frames))
        ),
    )
    return dialog, options


class _Driver:
    """Records what the harness typed; applies it to the fake session the way the dialog's traces would."""

    def __init__(self, dialog: Any, options: Any) -> None:
        self.dialog, self.options, self.log = dialog, options, []

    def set_variable(self, variable: Any, value: Any, *, label: str) -> None:
        variable.set(value)
        self.log.append((label, value))
        from src.gui.views import motion_batch_dialog as mbd

        pairs = (
            (self.dialog.policy_var, mbd._POLICY_ITEMS, "profile_policy"),
            (self.dialog.camera_var, mbd._CAMERA_ITEMS, "camera"),
            (self.dialog.mode_var, mbd._MODE_ITEMS, "camera_mode"),
            (self.dialog.root_var, mbd._ROOT_ITEMS, "root_motion"),
            (self.dialog.orient_var, mbd._ORIENT_ITEMS, "orientation"),
        )
        for var, items, attribute in pairs:
            if var is variable:
                setattr(self.options, attribute, dict(items)[value])
        if variable is self.dialog.start_var:
            self.options.start_seconds = str(value)

    def select_combobox(self, _combo: Any, value: str, *, label: str) -> None:
        self.options.frames = value
        self.log.append((label, value))

    def pump(self, _seconds: float) -> None:
        return None


def _run_stub(driver: Any) -> Any:
    checks: list[tuple[str, str, bool]] = []
    observations: dict[str, Any] = {}

    def check(phase: str, name: str, passed: bool, detail: str = "") -> bool:
        checks.append((phase, name, passed))
        return passed

    run = SimpleNamespace(
        driver=driver,
        check=check,
        ev=SimpleNamespace(observe=lambda name, value, **_k: observations.__setitem__(name, value)),
        checks=checks,
        observations=observations,
    )
    return run


def test_the_frozen_render_profile_is_typed_into_the_dialog_and_read_back(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    from tools.operator_journey.golden.vid02_offline import _apply_render_profile

    frozen = offline.read_offline_inputs(offline_target(assets, blender_exe))
    dialog, options = _fake_dialog([17, 25, 33])
    driver = _Driver(dialog, options)
    run = _run_stub(driver)
    _apply_render_profile(run, dialog, frozen)
    assert ("Batch: Longest clip", "25") in driver.log
    assert (options.camera, options.camera_mode, options.root_motion, options.orientation) == (
        "side",
        "tracking",
        "in_place",
        "landscape",
    )
    assert options.start_seconds == "0.5" and options.frames == "25"
    assert run.checks == [("batch", "dialog_holds_the_frozen_render_profile", True)]
    assert run.observations["render_profile"]["frozen"]["frames"] == 25


def test_a_render_profile_the_dialog_does_not_offer_is_a_hold(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    from tools.operator_journey.golden.vid02_offline import _apply_render_profile

    base = offline_target(assets, blender_exe)
    unoffered_frames = deepcopy(base)
    unoffered_frames["inputs"]["render_profile"]["frames"] = 33
    dialog, options = _fake_dialog([17, 25])
    with pytest.raises(JourneyHold, match="33 frames"):
        _apply_render_profile(
            _run_stub(_Driver(dialog, options)),
            dialog,
            offline.read_offline_inputs(unoffered_frames),
        )
    unoffered_camera = deepcopy(base)
    unoffered_camera["inputs"]["render_profile"]["camera"] = "overhead"
    dialog, options = _fake_dialog([17, 25])
    with pytest.raises(JourneyHold, match="camera 'overhead'"):
        _apply_render_profile(
            _run_stub(_Driver(dialog, options)),
            dialog,
            offline.read_offline_inputs(unoffered_camera),
        )


def _fake_tab(*, label: str | None, version: str, listed: bool = True):
    picked: list[str] = []
    tab = SimpleNamespace(
        advanced_section=SimpleNamespace(is_expanded=lambda: True),
        _workflow_map={"wan22_fun_control_5b_canny_i2v_v1": {"workflow_version": version}},
        _workflow_id_to_label={"wan22_fun_control_5b_canny_i2v_v1": label} if label else {},
        workflow_combo=SimpleNamespace(cget=lambda _k: ["Other engine", label] if listed else []),
    )
    driver = SimpleNamespace(
        select_combobox=lambda _c, value, label: picked.append(value),
        pump=lambda _s: None,
        invoke=lambda *_a, **_k: None,
    )
    return tab, SimpleNamespace(driver=driver), picked


def test_the_frozen_driving_workflow_is_selected_by_id_and_version(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    from tools.operator_journey.golden.vid02_offline import _pick_driving_workflow

    frozen = offline.read_offline_inputs(offline_target(assets, blender_exe))
    tab, run, picked = _fake_tab(label="Fun Control 5B (experimental)", version="1.0.0")
    _pick_driving_workflow(run, tab, frozen)
    assert picked == ["Fun Control 5B (experimental)"]
    for stale in (
        _fake_tab(label="Fun Control 5B (experimental)", version="2.0.0"),  # another version
        _fake_tab(label=None, version="1.0.0"),  # the picker has no such workflow
        _fake_tab(label="Fun Control 5B (experimental)", version="1.0.0", listed=False),
    ):
        tab, run, picked = stale
        with pytest.raises(JourneyHold, match="offers no wan22_fun_control_5b_canny_i2v_v1 1.0.0"):
            _pick_driving_workflow(run, tab, frozen)
        assert picked == []


def _prepared_record(workspace: Path, clip_sha: str, *, start: Any = 0.5, end: Any = 2.0):
    derived = workspace / "output" / "prepared_driving_videos" / ("c" * 64 + ".mp4")
    derived.parent.mkdir(parents=True)
    derived.write_bytes(b"prepared")
    sha = _sha(derived)
    final = derived.with_name(f"{sha}.mp4")
    derived.rename(final)
    record = {
        "original": {"sha256": clip_sha},
        "derived": {"path": str(final), "sha256": sha, "frames": 3},
        "settings": {"requested": {"start": start, "end": end, "unit": "seconds"}},
        "plan": {"window_frames": 3, "source_indices": [12, 13, 14]},
    }
    return record, sha


def _findings(record: dict[str, Any], frozen: Any, **over: Any) -> dict[str, bool]:
    from tools.operator_journey.golden.vid02_offline import prepared_findings

    args: dict[str, Any] = {
        "clip_sha": "d" * 64,
        "clip_sha_after": "d" * 64,
        "workspace": over.pop("workspace"),
        "independent_sha": over.pop("independent_sha"),
        "media": {"valid": True, "decoded_frames": 3},
    }
    args.update(over)
    return {name: passed for name, passed, _detail in prepared_findings(record, frozen, **args)}


def test_prepare_motion_source_is_judged_on_content_addressing_and_the_recorded_window(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    frozen = offline.read_offline_inputs(offline_target(assets, blender_exe))
    record, sha = _prepared_record(tmp_path, "d" * 64)
    good = _findings(record, frozen, workspace=tmp_path, independent_sha=sha)
    assert set(good) == {
        "preparation_names_the_driving_clip",
        "output_is_content_addressed",
        "frame_window_is_recorded",
        "prepared_clip_decodes",
        "preparation_left_the_driving_clip_unchanged",
    }
    assert all(good.values()), good

    # not content-addressed: the file name is not its hash
    renamed = deepcopy(record)
    wrong = Path(record["derived"]["path"]).with_name("not-the-hash.mp4")
    Path(record["derived"]["path"]).rename(wrong)
    renamed["derived"]["path"] = str(wrong)
    assert not _findings(renamed, frozen, workspace=tmp_path, independent_sha=sha)[
        "output_is_content_addressed"
    ]
    # a record that disagrees with the file on disk
    assert not _findings(record, frozen, workspace=tmp_path, independent_sha="e" * 64)[
        "output_is_content_addressed"
    ]
    # the window the plan froze is not the window recorded
    other_window, sha2 = _prepared_record(tmp_path / "two", "d" * 64, start=0.0, end=2.0)
    assert not _findings(other_window, frozen, workspace=tmp_path / "two", independent_sha=sha2)[
        "frame_window_is_recorded"
    ]
    # a different driving clip, a clip that changed under preparation, an undecodable result
    assert not _findings(
        record, frozen, workspace=tmp_path, independent_sha=sha, clip_sha="f" * 64
    )["preparation_names_the_driving_clip"]
    assert not _findings(
        record, frozen, workspace=tmp_path, independent_sha=sha, clip_sha_after="f" * 64
    )["preparation_left_the_driving_clip_unchanged"]
    assert not _findings(
        record, frozen, workspace=tmp_path, independent_sha=sha, media={"valid": False}
    )["prepared_clip_decodes"]


def test_an_open_ended_window_must_be_recorded_as_open_ended(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    target = offline_target(assets, blender_exe)
    target["inputs"]["frame_window"] = {"start": 0, "end": None, "convert": False}
    frozen = offline.read_offline_inputs(target)
    record, sha = _prepared_record(tmp_path, "d" * 64, start=0, end=None)
    assert _findings(record, frozen, workspace=tmp_path, independent_sha=sha)[
        "frame_window_is_recorded"
    ]
    record["settings"]["requested"]["end"] = 3.0
    assert not _findings(record, frozen, workspace=tmp_path, independent_sha=sha)[
        "frame_window_is_recorded"
    ]


# --- the journey body's own gates (before anything starts) -----------------------------------------------------------


def _body_run(**over: Any) -> Any:
    observations: dict[str, Any] = {}
    checks: list[tuple[str, bool]] = []
    ev = SimpleNamespace(
        observe=lambda name, value, **_k: observations.__setitem__(name, value),
        checks=checks,
        failed_checks=[],
    )
    run = SimpleNamespace(
        ev=ev,
        fake_comfy=None,
        fake_a1111=None,
        config=SimpleNamespace(extras={}),
        check=lambda phase, name, passed, detail="": checks.append((name, passed)) or passed,
        observations=observations,
    )
    for key, value in over.items():
        setattr(run, key, value)
    return run


@pytest.fixture
def ffmpeg_present(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.pipeline.video as video

    monkeypatch.setattr(video, "VideoCreator", lambda: SimpleNamespace(ffmpeg_available=True))


def test_the_body_refuses_to_run_with_a_fake_backend_or_an_invalid_target(
    tmp_path: Path, assets: Path, blender_exe: Path, ffmpeg_present: None
) -> None:
    from tools.operator_journey.golden.vid02_offline import run_vid02_offline

    target = offline_target(assets, blender_exe)
    with pytest.raises(JourneyAbort, match="no fake backend"):
        run_vid02_offline(_body_run(fake_comfy=object()), target)
    with pytest.raises(JourneyHold, match="not a valid offline VID-02 target"):
        run_vid02_offline(_body_run(), {**target, "blender": {}})


def test_a_changed_added_or_removed_original_is_a_hold_before_anything_runs(
    tmp_path: Path, assets: Path, blender_exe: Path, ffmpeg_present: None, monkeypatch
) -> None:
    from tools.operator_journey.golden import blender_gate
    from tools.operator_journey.golden.vid02_offline import run_vid02_offline

    monkeypatch.setattr(
        blender_gate, "qualify_blender", _forbidden
    )  # the originals gate comes first
    target = offline_target(assets, blender_exe)
    (assets / "walk.bvh").write_text("edited after freezing", encoding="utf-8")
    with pytest.raises(JourneyHold, match=r"walk\.bvh: SHA-256 changed"):
        run_vid02_offline(_body_run(), target)
    (assets / "walk.bvh").write_text("HIERARCHY walk", encoding="utf-8")
    (assets / "extra.bvh").write_text("surprise", encoding="utf-8")
    with pytest.raises(JourneyHold, match=r"extra\.bvh: present in the asset directory"):
        run_vid02_offline(_body_run(), target)
    (assets / "extra.bvh").unlink()
    (assets / "run.bvh").unlink()
    with pytest.raises(JourneyHold, match=r"run\.bvh: frozen but no longer"):
        run_vid02_offline(_body_run(), target)


def test_a_blender_that_is_not_the_frozen_one_is_a_hold(
    tmp_path: Path, assets: Path, blender_exe: Path, ffmpeg_present: None, monkeypatch
) -> None:
    from src.video.motion_conversion import blender as bl
    from tools.operator_journey.golden import blender_gate
    from tools.operator_journey.golden.vid02_offline import run_vid02_offline

    target = offline_target(assets, blender_exe)
    install = bl.BlenderInstall(blender_exe, (4, 5, 9), "Blender 4.5.9")
    monkeypatch.setattr(
        blender_gate,
        "qualify_blender",
        lambda _c: blender_gate.BlenderQualification(
            blender_gate.VERIFIED, "ok", candidate=str(blender_exe), install=install
        ),
    )
    blender_exe.write_bytes(b"a different executable")  # same path, different SHA-256
    with pytest.raises(JourneyHold, match="no longer matches the frozen plan"):
        run_vid02_offline(_body_run(), target)
    unusable = blender_gate.BlenderQualification(blender_gate.MISSING, "not found")
    monkeypatch.setattr(blender_gate, "qualify_blender", lambda _c: unusable)
    with pytest.raises(JourneyHold, match="executable missing"):
        run_vid02_offline(_body_run(), target)


def test_without_ffmpeg_the_lane_is_a_hold(
    tmp_path: Path, assets: Path, blender_exe: Path, monkeypatch
) -> None:
    import src.pipeline.video as video
    from tools.operator_journey.golden.vid02_offline import run_vid02_offline

    monkeypatch.setattr(video, "VideoCreator", lambda: SimpleNamespace(ffmpeg_available=False))
    with pytest.raises(JourneyHold, match="FFmpeg is not available"):
        run_vid02_offline(_body_run(), offline_target(assets, blender_exe))


def test_run_vid02_dispatches_a_physical_target_to_the_offline_lane_and_nothing_else(
    tmp_path: Path, assets: Path, blender_exe: Path, monkeypatch
) -> None:
    from tools.operator_journey.golden import vid02, vid02_offline

    seen: list[Any] = []
    monkeypatch.setattr(vid02_offline, "run_vid02_offline", lambda run, target: seen.append(target))
    target = offline_target(assets, blender_exe)
    vid02.run_vid02(object(), simulated=False, physical=target)  # type: ignore[arg-type]
    assert seen == [target]


# --- the physical executor ----------------------------------------------------------------------------------------


def test_real_executor_runs_vid02_offline_with_no_backend_configured(
    tmp_path: Path, assets: Path, blender_exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.operator_journey.golden import session, vid02

    target = offline_target(assets, blender_exe)
    captured: dict[str, Any] = {}

    ran: list[Any] = []
    monkeypatch.setattr(
        vid02, "run_vid02", lambda run, simulated, physical: ran.append((simulated, physical))
    )

    def fake_run_journey_body(journey_id, body, config, **kwargs):
        captured.update(journey_id=journey_id, config=config, kwargs=kwargs)
        body(object())
        captured["ran"] = ran
        return JourneyEvidence(journey_id=journey_id, backend_mode="physical")

    monkeypatch.setattr(session, "run_journey_body", fake_run_journey_body)
    # the operator's saved engine settings are not read: a Comfy or Forge address saved there cannot be reached from here
    monkeypatch.setattr(physical, "_engine_settings", _forbidden)

    class Monitor:
        tripped = None
        peaks = {"vram_used_mib": 812.0}

    physical.real_executor(definitions.JOURNEYS[KEY], target, Monitor(), tmp_path)  # type: ignore[arg-type]
    assert captured["journey_id"] == "VID-02"
    assert captured["ran"] == [(False, target)]
    kwargs = captured["kwargs"]
    assert (kwargs["mode_label"], kwargs["execution_mode"]) == ("physical", "physical")
    assert kwargs["base_url"] == physical.OFFLINE_BASE_URL == "http://127.0.0.1:9"
    settings = kwargs["settings_extra"]
    assert settings["comfy_base_url"] == settings["webui_base_url"] == physical.OFFLINE_BASE_URL
    assert (
        settings["comfy_autostart_enabled"] is False
        and settings["webui_autostart_enabled"] is False
    )
    config = captured["config"]
    assert config.driver == "windows"
    assert config.extras["journey_key"] == KEY and config.extras["target"] is target
    assert config.extras["resource_peaks"]() == {"vram_used_mib": 812.0}
    assert config.extras["abort_check"]() is None


def test_the_plan_gate_declines_every_submission_of_an_offline_journey() -> None:
    queued: list[Any] = []
    service = SimpleNamespace(submit_njrs=lambda records, *a, **k: queued.append(list(records)))
    gatekeeper = PlanGate(KEY, {"job_count": 0})
    gatekeeper.install(service)
    with pytest.raises(PlanMismatch, match="offline journey and submits no job"):
        service.submit_njrs([SimpleNamespace(to_dict=lambda: {})])
    assert queued == [] and gatekeeper.mismatches
    # the same gate, for a GPU journey, still lets a matching record through (unchanged behaviour)
    queued.clear()
    image = PlanGate("image", {"job_count": 1, "settings": {}, "inputs": {}, "model": {}})
    service2 = SimpleNamespace(submit_njrs=lambda records, *a, **k: queued.append(list(records)))
    image.install(service2)
    service2.submit_njrs([SimpleNamespace(to_dict=lambda: {"workload": {"config": {}}})])
    assert len(queued) == 1


# --- readiness ---------------------------------------------------------------------------------------------------


def test_readiness_passes_for_an_intact_offline_plan_without_touching_any_runtime(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    report = evaluate_readiness(authorize(plan), make_ctx(probes))
    assert report["verdict"] == PASS, report["gates"]
    assert report["started_runtime"] is False and report["physical_run_authorized"] is True
    ids = {g["id"] for g in report["gates"]}
    assert {
        f"{KEY}:offline_lane",
        f"{KEY}:blender_identity",
        f"{KEY}:source_assets",
        f"{KEY}:ffmpeg",
    } <= ids
    # no endpoint, ownership, runtime-identity or workflow gate exists for a lane with no backend
    assert not any(
        g.endswith(suffix)
        for g in ids
        for suffix in (":endpoint", ":ownership", ":runtime_identity", ":workflow_governance")
    )
    assert "matches the plan" in gate(report, f"{KEY}:blender_identity")["detail"]


def test_an_offline_plan_still_observes_the_gpu_and_host_so_idle_is_evidence(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    """Readiness must not need a GPU *runtime*, but the shared resource gates are unchanged: a GPU already busy is NO-GO."""

    plan, probes = freeze(tmp_path, assets, blender_exe)
    busy = make_probes(gpu=lambda: {**GPU, "used_mib": 9000.0})
    # the environment changed (the GPU is not the one frozen) only in VRAM use, which is not part of the identity
    report = evaluate_readiness(authorize(plan), make_ctx(busy))
    assert gate(report, "gpu_idle_vram")["state"] == NO_GO and report["verdict"] == NO_GO
    blind = make_probes(gpu=lambda: None)
    report = evaluate_readiness(authorize(plan), make_ctx(blind))
    assert gate(report, "gpu_telemetry")["state"] == NO_GO


def test_a_different_blender_or_a_drifted_asset_folder_or_no_ffmpeg_is_a_hold(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    approved = authorize(plan)

    other_version = make_probes(blender=lambda exe: {"version": "4.6.0", "sha256": _sha(Path(exe))})
    report = evaluate_readiness(approved, make_ctx(other_version))
    assert gate(report, f"{KEY}:blender_identity")["state"] == HOLD
    assert report["verdict"] == HOLD

    report = evaluate_readiness(approved, make_ctx(make_probes(blender=lambda _e: None)))
    assert gate(report, f"{KEY}:blender_identity")["state"] == HOLD
    assert "missing or not a supported Blender" in gate(report, f"{KEY}:blender_identity")["detail"]

    assert (
        gate(
            evaluate_readiness(approved, make_ctx(make_probes(ffmpeg=lambda: False))),
            f"{KEY}:ffmpeg",
        )["state"]
        == HOLD
    )

    (assets / "walk.bvh").write_text("changed", encoding="utf-8")
    report = evaluate_readiness(approved, make_ctx(probes))
    assert gate(report, f"{KEY}:source_assets")["state"] == HOLD
    assert gate(report, "environment_matches_plan")["state"] == HOLD
    assert report["verdict"] == HOLD


def test_environment_diffs_see_an_added_file_a_changed_original_and_a_changed_blender(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    assert environment_diffs(plan, probes) == []
    (assets / "added.bvh").write_text("new", encoding="utf-8")
    assert any("asset_listing" in d for d in environment_diffs(plan, probes))
    (assets / "added.bvh").unlink()
    (assets / "run.bvh").write_text("changed", encoding="utf-8")
    assert any("sources" in d for d in environment_diffs(plan, probes))
    (assets / "run.bvh").write_text("HIERARCHY run", encoding="utf-8")
    blender_exe.write_bytes(b"patched")
    assert any(".blender" in d for d in environment_diffs(plan, probes))


# --- the gates in front of the lane -------------------------------------------------------------------------------


def run_gate(tmp_path: Path, plan: dict[str, Any], probes: HostProbes, **over: Any):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, default=str), "utf-8")
    return run_physical(
        path,
        journeys=[definitions.JOURNEYS[KEY]],
        evidence_root=tmp_path / "ev",
        ctx=make_ctx(probes),
        probes=probes,
        **over,
    )


def test_an_unauthorized_offline_plan_runs_nothing(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    verdict, run_dir = run_gate(tmp_path, plan, probes, executor=_forbidden)
    assert verdict == HOLD
    evidence = json.loads((run_dir / "evidence.json").read_text("utf-8"))
    assert evidence["outcomes"]["physical_execution"] == "NOT RUN"
    assert "not authorized" in evidence["outcomes"]["reason"]


def test_the_typed_launch_is_still_required_for_an_authorized_offline_plan(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    approved = authorize(plan)
    verdict, _ = run_gate(
        tmp_path, approved, probes, executor=_forbidden, confirm=lambda _prompt: "yes"
    )
    assert verdict == HOLD
    verdict, run_dir = run_gate(
        tmp_path, approved, probes, executor=_forbidden, confirm=lambda _prompt: "RUN 000000000000"
    )
    assert verdict == HOLD


def test_authorized_ready_and_typed_an_offline_plan_runs_exactly_the_frozen_target(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    approved = authorize(plan)
    seen: list[dict[str, Any]] = []

    def executor(journey, target, monitor, run_dir):
        seen.append(target)
        ev = JourneyEvidence(journey_id=journey.id, backend_mode="physical")
        ev.observe("video_media", {"path": "x.mp4", "valid": True, "sha256": "ab"})
        return ev

    verdict, run_dir = run_gate(
        tmp_path, approved, probes, executor=executor, confirm=lambda _p: confirmation_phrase(plan)
    )
    assert verdict == PASS and seen == [approved["targets"][KEY]]
    evidence = json.loads((run_dir / "evidence.json").read_text("utf-8"))
    assert evidence["outcomes"]["physical_execution"] == "RAN"
    assert evidence["outcomes"]["visual_quality"] == "PENDING_OPERATOR_REVIEW"
    assert (run_dir / "resource_telemetry.jsonl").read_text("utf-8").strip()


def test_drift_between_freezing_and_launch_is_a_hold_for_an_offline_plan(
    tmp_path: Path, assets: Path, blender_exe: Path
) -> None:
    plan, probes = freeze(tmp_path, assets, blender_exe)
    approved = authorize(plan)
    (assets / "walk.bvh").write_text("edited", encoding="utf-8")
    verdict, run_dir = run_gate(
        tmp_path,
        approved,
        probes,
        executor=_forbidden,
        confirm=lambda _p: confirmation_phrase(plan),
    )
    assert verdict == HOLD
    evidence = json.loads((run_dir / "evidence.json").read_text("utf-8"))
    assert "environment changed" in evidence["outcomes"]["reason"]
    assert evidence["outcomes"]["physical_execution"] == "NOT RUN"


# --- the simulated lane is unchanged ------------------------------------------------------------------------------


def test_the_simulated_lane_still_routes_through_its_own_runner_with_loopback_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.operator_journey.golden import advanced, session

    seen: dict[str, Any] = {}

    def fake_run_journey_body(journey_id, body, config, **kwargs):
        seen.update(journey_id=journey_id, body=body.__name__, kwargs=kwargs)
        return JourneyEvidence(journey_id=journey_id, backend_mode="simulated")

    monkeypatch.setattr(session, "run_journey_body", fake_run_journey_body)
    advanced.run_advanced(definitions.JOURNEYS[KEY], config=None)  # type: ignore[arg-type]
    assert seen["journey_id"] == "VID-02" and seen["body"] == "run_vid02"
    assert seen["kwargs"]["mode_label"] == "simulated"
    assert callable(seen["kwargs"]["fake_comfy_factory"]) and callable(
        seen["kwargs"]["fake_a1111_factory"]
    )
    assert "execution_mode" not in seen["kwargs"]  # still the default, "simulated"
