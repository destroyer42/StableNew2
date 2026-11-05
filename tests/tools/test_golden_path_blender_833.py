"""VID-02's Blender situation is classified precisely and staged only inside the disposable workspace (PR-QUAL-JOURNEYS-833).

Deterministic and CPU-only: no Blender is started here.  A real-Blender run of the journey is opt-in below.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.utils.managed_process import ProcessOutcome
from src.video.motion_conversion import batch as bt
from src.video.motion_conversion import blender as bl
from src.video.motion_conversion import conversion_plan as cp
from src.video.motion_conversion import workbench
from src.video.motion_conversion.workbench import ConversionWorkbench
from tools.operator_journey.golden import blender_gate as gate
from tools.operator_journey.golden.vid02 import BVH_FRAME_TIME, BVH_FRAMES, make_bvh


def _runner(stdout: bytes = b"", **fields: object):
    def run(argv, **_options):  # noqa: ANN001, ANN202
        return ProcessOutcome(returncode=fields.pop("returncode", 0), stdout=stdout, **fields)  # type: ignore[arg-type]

    return run


def _verify_with(runner):  # noqa: ANN001, ANN202
    return lambda candidate: bl.verify_blender(
        candidate, runner=runner, argv_prefix=[str(candidate)]
    )


def test_no_supplied_executable_is_not_a_missing_installation() -> None:
    result = gate.qualify_blender("")
    assert result.state == gate.NOT_SUPPLIED and not result.verified
    reason = result.hold_reason()
    assert "isolated workspace deliberately has no Blender registration" in reason
    assert "does not say whether the host has Blender" in reason
    assert (
        "not installed" not in reason
    )  # the workspace has none by design; that is not a finding about the host


def test_a_missing_executable_is_named_as_missing(tmp_path: Path) -> None:
    result = gate.qualify_blender(tmp_path / "no" / "blender.exe")
    assert result.state == gate.MISSING
    assert "was not found" in result.detail and "executable missing" in result.hold_reason()


@pytest.mark.parametrize(
    ("outcome", "state"),
    [
        (_runner(b"Blender 3.6.5\n"), gate.UNSUPPORTED),
        (_runner(b"hello from some other program\n"), gate.NOT_BLENDER),
        (_runner(b"", launch_error="access denied"), gate.VERIFICATION_FAILED),
        (_runner(b"", timed_out=True), gate.VERIFICATION_FAILED),
        (_runner(b"Blender 4.5.9\n", returncode=3), gate.VERIFICATION_FAILED),
    ],
)
def test_each_refusal_has_its_own_state(outcome, state: str) -> None:  # noqa: ANN001
    result = gate.qualify_blender("candidate.exe", verify=_verify_with(outcome))
    assert result.state == state and not result.verified
    assert state.replace("_", " ") in result.hold_reason()
    assert "no render was faked" in result.hold_reason()


def test_a_supported_blender_is_verified_and_reports_its_version() -> None:
    result = gate.qualify_blender(
        "candidate.exe", verify=_verify_with(_runner(b"Blender 4.5.9 LTS (hash x)\n"))
    )
    assert result.verified and result.hold_reason() == ""
    assert result.install is not None and result.install.version == (4, 5, 9)


def test_the_run_setting_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gate.ENV_VARIABLE, "from-env.exe")
    assert gate.supplied_executable({gate.EXTRAS_KEY: "from-run.exe"}) == "from-run.exe"
    assert gate.supplied_executable({}) == "from-env.exe"
    monkeypatch.delenv(gate.ENV_VARIABLE)
    assert gate.supplied_executable(None) == ""


def test_registration_is_staged_only_inside_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, elsewhere = tmp_path / "workspace", tmp_path / "operator"
    workspace.mkdir()
    elsewhere.mkdir()
    install = bl.BlenderInstall(Path("C:/blender/blender.exe"), (4, 5, 9), "Blender 4.5.9")

    monkeypatch.setattr(workbench, "settings_path", lambda: workspace / "user-data" / "s.json")
    staged = gate.stage_registration(install, workspace)
    assert staged.is_file() and workbench.load_blender_setting().endswith("blender.exe")

    monkeypatch.setattr(workbench, "settings_path", lambda: elsewhere / "motion_conversion.json")
    with pytest.raises(gate.RegistrationEscape):
        gate.stage_registration(install, workspace)
    assert not (
        elsewhere / "motion_conversion.json"
    ).exists()  # nothing was written to the operator's side


def test_the_fixture_animation_is_a_valid_bvh_the_renderer_can_use(tmp_path: Path) -> None:
    text = make_bvh()
    header, _, motion = text.partition("MOTION")
    channels = sum(int(line.split()[1]) for line in header.splitlines() if "CHANNELS" in line)
    rows = [line for line in motion.splitlines() if line and line[0] in "-0123456789"]
    assert f"Frames: {BVH_FRAMES}" in motion and len(rows) == BVH_FRAMES
    assert all(len(row.split()) == channels for row in rows)
    path = tmp_path / "walk.bvh"
    path.write_text(text, encoding="utf-8")
    facts = ConversionWorkbench(library_root=tmp_path / "lib").describe_source(path)
    assert facts.ready and facts.route == cp.SOURCE_BVH
    # The animation supplies enough frames for every length the generic frame rule accepts, from the start.
    probe = SimpleNamespace(duration_seconds=(BVH_FRAMES - 1) * BVH_FRAME_TIME)
    assert bt.fit_frames(bt.BatchSettings(frames=17), probe) == 17  # type: ignore[arg-type]
    assert bt.fit_frames(bt.BatchSettings(frames=BVH_FRAMES), probe) == BVH_FRAMES  # type: ignore[arg-type]


def test_the_old_four_frame_fixture_would_have_been_ineligible() -> None:
    """The earlier fixture could never convert: 4 frames supply 3 at 24 fps, below the shortest legal length."""

    probe = SimpleNamespace(duration_seconds=3 * 0.0333333)
    with pytest.raises(cp.ConversionPlanError):
        bt.fit_frames(bt.BatchSettings(frames=17), probe)  # type: ignore[arg-type]


@pytest.mark.skipif(
    not os.environ.get(gate.ENV_VARIABLE),
    reason=f"opt-in real CPU Blender conversion: set {gate.ENV_VARIABLE} to an explicit blender.exe",
)
def test_vid02_converts_a_sample_with_a_real_blender(tmp_path: Path) -> None:
    """The journey, with a real offline Blender: it must prove a conversion happened, not merely not fail."""

    if sys.platform != "win32":
        pytest.skip("the golden-path GUI journeys run on Windows only")
    import json

    from tests.tools.test_golden_path_journeys import _run_suite

    code, _evidence, bundle = _run_suite(
        tmp_path,
        "--journey",
        "motion-assets",
        "--hide-window",
        "--blender",
        os.environ[gate.ENV_VARIABLE],
        timeout=1500,
    )
    journey = json.loads(next(bundle.glob("journeys/*VID-02*/evidence.json")).read_text("utf-8"))
    checks = {c["name"]: c["passed"] for c in journey["checks"]}
    assert checks.get("a_real_conversion_completed") is True, journey.get("failed_assertion")
    assert journey["verdict"] == "PASS" and code == 0
