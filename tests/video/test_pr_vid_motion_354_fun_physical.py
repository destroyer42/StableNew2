"""Offline tests for the Fun Control physical executor, coverage plan and input manifest (no GPU, no Comfy, no network)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from tools.qualification.fun354 import physical
from tools.qualification.fun354.harness import (
    FEASIBLE,
    INCONCLUSIVE,
    NO_GO,
    Authorization,
    run_qualification,
)
from tools.qualification.fun354.inputs import InputsError, load_input_set, rebuild_plan
from tools.qualification.fun354.physical import (
    Monitor,
    PhysicalExecutor,
    Sample,
    Seams,
    StopGuard,
    fault_events,
    render_graph,
    scan_log,
    template_digest,
    validate_frames,
    validate_schema,
)
from tools.qualification.fun354.plan import (
    CASE_Q2_A,
    PHASE_Q0,
    PHASE_Q1,
    PHASE_Q1C,
    PHASE_Q2,
    RESOURCE_STOPS,
    ROLE_Q2_DRIVING,
    STOP_ALLOCATION,
    STOP_COMMIT,
    STOP_DEVICE_LOSS,
    STOP_IDENTITY,
    STOP_LOW_RAM,
    STOP_TEARDOWN,
    STOP_TELEMETRY,
    CoverageEntry,
    build_plan,
)
from tools.qualification.fun354.q0 import Q0Report

REFERENCE_SIZE = (480, 832)


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _manifest(tmp_path: Path, extra_roles: tuple[tuple[str, str], ...] = ()) -> tuple[Path, Path]:
    clips = tmp_path / "clips"
    clips.mkdir()
    entries = []
    for role, kind in (
        ("driving_clip", "fbx_character"),
        ("q2_driving_clip", "fbx_character"),
        *extra_roles,
    ):
        path = _write(clips / f"{role}.mp4", role.encode() * 8)
        entries.append(
            {"role": role, "source_type": kind, "label": role, "path": str(path), "frames": 17}
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    reference = tmp_path / "reference.png"
    Image.new("RGB", REFERENCE_SIZE, (30, 60, 90)).save(reference)
    return manifest, reference


COVERAGE_ROLES = (
    ("cov_char_run", "fbx_character"),
    ("cov_skel_walk", "fbx_skeleton"),
    ("cov_bvh_walk", "bvh"),
    ("cov_mp4_yoga", "mp4"),
)


# ---- plan, manifest ---------------------------------------------------------------------------------------------------


def test_a_manifest_pins_every_clip_and_builds_a_coverage_phase_between_q1_and_q2(
    tmp_path: Path,
) -> None:
    manifest, reference = _manifest(tmp_path, COVERAGE_ROLES)
    input_set = load_input_set(manifest, reference)
    plan = input_set.build_plan()

    assert [p.phase_id for p in plan.phases] == [PHASE_Q0, PHASE_Q1, PHASE_Q1C, PHASE_Q2]
    coverage = plan.phase(PHASE_Q1C)
    assert [c.driving_role for c in coverage.cases] == [role for role, _ in COVERAGE_ROLES]
    assert all(c.frames == 17 for c in coverage.cases)
    assert {c.driving_role for c in plan.phase(PHASE_Q2).cases} == {ROLE_Q2_DRIVING}
    assert {p.role for p in plan.inputs} >= {
        "driving_clip",
        "reference_image",
        ROLE_Q2_DRIVING,
        *(role for role, _ in COVERAGE_ROLES),
    }
    assert all(p.sha256 and p.size for p in plan.inputs)
    assert plan.prompt and plan.negative_prompt
    assert plan.coverage[0] == CoverageEntry("cov_char_run", "fbx_character", "cov_char_run")


def test_the_prompt_the_coverage_and_every_pinned_clip_change_the_digest(tmp_path: Path) -> None:
    manifest, reference = _manifest(tmp_path, COVERAGE_ROLES)
    plan = load_input_set(manifest, reference).build_plan()
    assert replace(plan, prompt="different").digest != plan.digest
    assert replace(plan, coverage=plan.coverage[:-1]).digest != plan.digest
    clip = tmp_path / "clips" / "cov_char_run.mp4"
    clip.write_bytes(b"other bytes")
    assert load_input_set(manifest, reference).build_plan().digest != plan.digest


def test_a_stored_plan_rebuilds_to_the_same_digest(tmp_path: Path) -> None:
    manifest, reference = _manifest(tmp_path, COVERAGE_ROLES)
    plan = load_input_set(manifest, reference).build_plan()
    record = json.loads(json.dumps({**plan.to_record(), "digest": plan.digest}))
    assert rebuild_plan(record).digest == plan.digest


def test_a_manifest_without_a_driving_clip_or_with_a_missing_file_is_refused(
    tmp_path: Path,
) -> None:
    manifest, reference = _manifest(tmp_path)
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(entries[1:]), encoding="utf-8")
    with pytest.raises(InputsError, match="no driving_clip"):
        load_input_set(manifest, reference)
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    Path(entries[0]["path"]).unlink()
    with pytest.raises(InputsError, match="does not exist"):
        load_input_set(manifest, reference)
    with pytest.raises(InputsError, match="required"):
        load_input_set(None, reference)


def test_without_coverage_the_plan_keeps_its_original_three_phases() -> None:
    assert [p.phase_id for p in build_plan().phases] == [PHASE_Q0, PHASE_Q1, PHASE_Q2]


# ---- pure pieces ------------------------------------------------------------------------------------------------------


def _sample(t: float, commit: float = 0.5, ram: float = 8000.0, vram: float = 4000.0) -> Sample:
    return Sample(t, commit, ram, vram, 12282.0)


def test_the_guard_stops_on_sustained_commit_pressure_low_ram_or_a_telemetry_gap() -> None:
    guard = StopGuard()
    assert guard.observe(_sample(0, commit=0.96)) == ""  # one sample is not sustained
    assert guard.observe(_sample(1, commit=0.5)) == ""
    assert guard.observe(_sample(2, commit=0.96)) == ""
    assert guard.observe(_sample(3, commit=0.97)) == STOP_COMMIT

    guard = StopGuard()
    assert all(guard.observe(_sample(t, ram=900)) == "" for t in range(0, 8))
    assert guard.observe(_sample(8, ram=2000)) == ""  # recovered: the 10 s clock restarts
    assert all(guard.observe(_sample(t, ram=900)) == "" for t in range(9, 19))
    assert guard.observe(_sample(19, ram=900)) == STOP_LOW_RAM

    guard = StopGuard()
    guard.observe(_sample(0))
    assert guard.observe(_sample(6)) == STOP_TELEMETRY
    assert guard.peak_commit == 0.5 and guard.min_available_mib == 8000.0
    assert guard.silent_for(20) and not guard.silent_for(7)


def test_log_lines_map_to_device_loss_and_allocation_stops() -> None:
    assert scan_log("CUDA error: device-side assert triggered") == STOP_DEVICE_LOSS
    assert scan_log("torch.OutOfMemoryError: CUDA out of memory") == STOP_ALLOCATION
    assert scan_log("Allocation on device") == STOP_ALLOCATION
    assert scan_log("got prompt\nPrompt executed in 12.00 seconds") == ""
    assert {STOP_DEVICE_LOSS, STOP_ALLOCATION} <= RESOURCE_STOPS


def test_the_rendered_graph_is_the_catalog_template_for_this_case(tmp_path: Path) -> None:
    plan = build_plan()
    case = plan.phase(PHASE_Q2).cases[1]
    graph = render_graph(plan, case, reference_name="ref.png", driving_name="drive.mp4")
    text = json.dumps(graph)
    assert "{{" not in text
    assert graph["7"]["inputs"]["image"] == "ref.png"
    assert graph["12"]["inputs"]["file"] == "drive.mp4"
    assert graph["9"]["inputs"]["seed"] == case.seed == 424243
    assert graph["8"]["inputs"]["length"] == 49
    assert (graph["8"]["inputs"]["width"], graph["8"]["inputs"]["height"]) == (480, 832)
    assert graph["5"]["inputs"]["text"] == plan.prompt
    assert graph["11"]["inputs"]["filename_prefix"].endswith(case.case_id)
    assert template_digest() == plan.graph_sha256  # the recorded digest is the template's real hash


COMBO_INPUTS = frozenset(
    {
        "image",
        "file",
        "unet_name",
        "clip_name",
        "vae_name",
        "weight_dtype",
        "type",
        "sampler_name",
        "scheduler",
    }
)


def _info_for(graph: dict[str, Any]) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for node in graph.values():
        required = info.setdefault(node["class_type"], {"input": {"required": {}}})["input"][
            "required"
        ]
        for key, value in node["inputs"].items():
            combo = key in COMBO_INPUTS and isinstance(value, str)
            required[key] = [[value]] if combo else ["ANY"]
    return info


def test_schema_validation_names_a_missing_node_option_or_input() -> None:
    plan = build_plan()
    graph = render_graph(
        plan, plan.phase(PHASE_Q1).cases[0], reference_name="r.png", driving_name="d.mp4"
    )
    info = _info_for(graph)
    validate_schema(info, graph)

    with pytest.raises(RuntimeError, match="Missing stock node: LoadVideo"):
        validate_schema({k: v for k, v in info.items() if k != "LoadVideo"}, graph)
    stale = json.loads(json.dumps(info))
    stale["LoadVideo"]["input"]["required"]["file"] = [["something_else.mp4"]]
    with pytest.raises(RuntimeError, match="Unavailable node option: d.mp4"):
        validate_schema(stale, graph)
    stale = json.loads(json.dumps(info))
    del stale["Canny"]["input"]["required"]["low_threshold"]
    with pytest.raises(RuntimeError, match="Unsupported node input: Canny.low_threshold"):
        validate_schema(stale, graph)


def _frames(out: Path, count: int, size: tuple[int, int] = REFERENCE_SIZE) -> dict[str, Any]:
    (out / "stablenew").mkdir(parents=True, exist_ok=True)
    images = []
    for i in range(count):
        name = f"fun_{i:05d}.png"
        Image.new("RGB", size, (i * 3 % 255, 40, 80)).save(out / "stablenew" / name)
        images.append({"filename": name, "subfolder": "stablenew", "type": "output"})
    return {
        "status": {"completed": True, "status_str": "success"},
        "outputs": {"11": {"images": images}},
    }


def test_frame_validation_demands_exact_count_geometry_and_containment(tmp_path: Path) -> None:
    out = tmp_path / "output"
    history = _frames(out, 17)
    assert len(validate_frames(history, out, 17, REFERENCE_SIZE)) == 17
    with pytest.raises(RuntimeError, match="Expected 49 PNG frames, found 17"):
        validate_frames(history, out, 49, REFERENCE_SIZE)
    with pytest.raises(RuntimeError, match="Invalid frame geometry"):
        validate_frames(
            _frames(tmp_path / "wrong", 3, (64, 64)), tmp_path / "wrong", 3, REFERENCE_SIZE
        )
    for name, subfolder in (("..\\..\\x.png", ""), ("x.png", "../.."), ("../x.png", "")):
        escaped = {
            "outputs": {
                "11": {"images": [{"filename": name, "subfolder": subfolder, "type": "output"}]}
            }
        }
        with pytest.raises(RuntimeError, match="Escaped"):
            validate_frames(escaped, out, 1, REFERENCE_SIZE)


def test_only_driver_and_hardware_faults_in_the_event_log_count() -> None:
    rows = {
        "events": [
            {"Id": 1, "ProviderName": "Microsoft-Windows-Kernel-General"},
            {"Id": 153, "ProviderName": "disk"},
        ]
    }
    assert fault_events(rows) == []
    rows["events"].append({"Id": 4101, "ProviderName": "Display"})
    rows["events"].append({"Id": 14, "ProviderName": "Microsoft-Windows-WHEA-Logger"})
    assert len(fault_events(rows)) == 2
    assert fault_events({"events": {"Id": 41, "ProviderName": "Kernel-Power"}}) != []


def test_the_monitor_stops_the_owned_runtime_when_telemetry_goes_quiet(tmp_path: Path) -> None:
    stops: list[int] = []
    calls = [0]

    def sample() -> Sample:
        calls[0] += 1
        if calls[0] > 2:
            raise OSError("counter unavailable")
        return _sample(calls[0])

    monitor = Monitor(
        sample_fn=sample,
        log_fn=lambda: "",
        stop_fn=lambda: stops.append(1),
        journal=tmp_path / "t.jsonl",
        interval=0.01,
    )
    monitor.start()
    deadline = time.monotonic() + 3
    while not monitor.stop_code and time.monotonic() < deadline:
        time.sleep(0.01)
    monitor.close()
    assert monitor.stop_code == STOP_TELEMETRY and stops == [1] and not monitor.complete
    assert (tmp_path / "t.jsonl").read_text(encoding="utf-8").count("\n") >= 2


# ---- the executor against fakes ---------------------------------------------------------------------------------------


class World:
    """A stand-in machine: fake manager, client, counters and processes."""

    def __init__(self, plan, case, mode: str = "ok") -> None:  # noqa: ANN001
        self.plan, self.case, self.mode = plan, case, mode
        self.config: Any = None
        self.stdout: list[str] = []
        self.stdout_on_start: list[str] = []
        self.started = False
        self.stops: list[float] = []
        self.interrupted = threading.Event()
        self.alive_after_stop: set[int] = set()
        self.vram_after = 1350.0
        self.stopped = False
        self.dispatched: list[dict[str, Any]] = []
        self.stats = {
            "system": {
                "comfyui_version": "0.38.0",
                "pytorch_version": "2.14.0+cu130",
                "python_version": "3.13.1 (main)",
            }
        }
        graph = render_graph(
            plan, case, reference_name="fun354_reference.png", driving_name="fun354_driving.mp4"
        )
        self.info = _info_for(graph)

    @property
    def out_dir(self) -> Path:
        command = self.config.command
        return Path(command[command.index("--output-directory") + 1])

    def seams(self) -> Seams:
        world = self

        class Manager:
            owns_process = False
            contained = True
            pid = 4242

            def __init__(self, config: Any) -> None:
                world.config = config

            def start(self) -> None:
                world.started = True
                world.stdout = world.stdout_on_start
                self.owns_process = True

            def stop(self, *, grace_seconds: float = 5.0) -> None:
                world.stops.append(grace_seconds)
                world.stopped = True
                self.owns_process = False

            def check_health(self) -> bool:
                return True

            def get_stdout_tail(self) -> list[str]:
                return world.stdout

            def get_stderr_tail(self) -> list[str]:
                return []

        class Client:
            def close(self) -> None: ...

            def get_system_stats(self, **_: Any) -> dict[str, Any]:
                return world.stats

            def get_object_info(self, **_: Any) -> dict[str, Any]:
                return world.info

            def queue_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
                world.dispatched.append(payload)
                return {"prompt_id": "p1"}

            def interrupt(self, prompt_id: str | None = None) -> None:
                world.interrupted.set()

            def get_queue(self, **_: Any) -> dict[str, Any]:
                return {"queue_running": [], "queue_pending": []}

            def get_history(self, prompt_id: str, **_: Any) -> dict[str, Any]:
                if world.mode == "cancel":
                    if not world.interrupted.is_set():
                        return {}
                    status = {
                        "completed": False,
                        "status_str": "error",
                        "messages": [["execution_interrupted", {}]],
                    }
                    return {prompt_id: {"status": status, "outputs": {}}}
                if world.mode == "oom":
                    status = {
                        "status_str": "error",
                        "messages": [
                            ["execution_error", {"exception_message": "CUDA out of memory"}]
                        ],
                    }
                    return {prompt_id: {"status": status, "outputs": {}}}
                if world.mode == "short":
                    return {prompt_id: _frames(world.out_dir, world.case.frames - 1)}
                return {prompt_id: _frames(world.out_dir, world.case.frames)}

        return Seams(
            manager_factory=Manager,
            client_factory=lambda url: Client(),
            gpu_memory=lambda: (world.vram_after if world.stopped else 1350.0, 12282.0),
            system_memory=lambda: (0.5, 9000.0),
            git_head=lambda source: world.plan.runtime_commit,
            event_log=lambda since: {"events": []},
            pid_exists=lambda pid: pid in world.alive_after_stop and world.stopped,
            child_pids=lambda pid: [4243],
            sleep=lambda s: time.sleep(0.005),
            monitor_interval=0.01,
        )


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(physical, "TEARDOWN_GRACE_SECONDS", 0.05)
    manifest, reference = _manifest(tmp_path, COVERAGE_ROLES)
    input_set = load_input_set(manifest, reference)
    return input_set.build_plan(), input_set, tmp_path / "evidence"


def _run(staged, phase_id: str, index: int, mode: str = "ok", **case_changes: Any):  # noqa: ANN001
    plan, input_set, evidence = staged
    phase = plan.phase(phase_id)
    case = replace(phase.cases[index], **case_changes)
    world = World(plan, case, mode)
    evidence.mkdir(exist_ok=True)
    executor = PhysicalExecutor(inputs=input_set.paths, evidence_root=evidence, seams=world.seams())
    return world, executor.run_case(plan, phase, case), evidence / case.case_id


def test_a_clean_q1_case_delivers_exact_frames_and_leaves_complete_evidence(staged) -> None:  # noqa: ANN001
    world, obs, root = _run(staged, PHASE_Q1, 0)
    assert obs.completed and obs.frames_delivered == obs.frames_expected == 17
    assert (
        not obs.stop_code
        and obs.identity_verified
        and obs.telemetry_complete
        and obs.teardown_clean
    )
    assert obs.peak_host_commit_fraction == 0.5 and obs.min_available_ram_mib == 9000
    command = world.config.command
    for flag in ("--disable-pinned-memory", "--disable-auto-launch", "--disable-all-custom-nodes"):
        assert flag in command
    assert command[command.index("--port") + 1] == "8197"
    assert str(root) in command[command.index("--output-directory") + 1]
    assert len(world.dispatched) == 1  # exactly one dispatch, never a retry
    for name in (
        "graph.json",
        "history.json",
        "frames.json",
        "telemetry.jsonl",
        "teardown.json",
        "events-before.json",
        "events-after.json",
        "runtime-stats.json",
    ):
        assert (root / name).is_file(), name
    assert json.loads((root / "teardown.json").read_text(encoding="utf-8"))["verified"] is True
    staged_names = sorted(p.name for p in (root / "runtime" / "input").iterdir())
    assert staged_names == ["fun354_driving.mp4", "fun354_reference.png"]


def test_a_coverage_case_stages_its_own_driving_clip(staged) -> None:  # noqa: ANN001
    plan, input_set, _ = staged
    index = [c.driving_role for c in plan.phase(PHASE_Q1C).cases].index("cov_bvh_walk")
    world, obs, root = _run(staged, PHASE_Q1C, index)
    assert obs.completed and obs.frames_delivered == 17
    staged_clip = root / "runtime" / "input" / "fun354_driving.mp4"
    assert staged_clip.read_bytes() == input_set.paths["cov_bvh_walk"].read_bytes()
    assert world.dispatched[0]["prompt"]["12"]["inputs"]["file"] == "fun354_driving.mp4"


def test_a_changed_input_or_a_wrong_runtime_is_an_identity_stop_before_anything_launches(
    staged,
) -> None:  # noqa: ANN001
    plan, input_set, _ = staged
    input_set.paths["driving_clip"].write_bytes(b"tampered")
    world, obs, root = _run(staged, PHASE_Q1, 0)
    assert obs.stop_code == STOP_IDENTITY and not obs.identity_verified and not world.started
    assert (root / "identity-refusal.json").is_file()


def test_a_runtime_that_reports_another_version_is_an_identity_stop(staged) -> None:  # noqa: ANN001
    plan, _, evidence = staged
    phase = plan.phase(PHASE_Q1)
    world = World(plan, phase.cases[0])
    world.stats["system"]["pytorch_version"] = "2.9.0"
    evidence.mkdir(exist_ok=True)
    obs = PhysicalExecutor(
        inputs=staged[1].paths, evidence_root=evidence, seams=world.seams()
    ).run_case(plan, phase, phase.cases[0])
    assert obs.stop_code == STOP_IDENTITY and not obs.identity_verified
    assert (
        world.started and world.stopped and not world.dispatched
    )  # launched, refused, torn down, never dispatched


def test_a_comfy_allocation_failure_is_a_resource_stop_with_complete_telemetry(staged) -> None:  # noqa: ANN001
    world, obs, _ = _run(staged, PHASE_Q1, 0, mode="oom")
    assert obs.stop_code == STOP_ALLOCATION and not obs.completed and obs.telemetry_complete
    assert world.stopped


def test_the_monitor_log_scan_stops_a_running_case_on_device_loss(staged) -> None:  # noqa: ANN001
    plan, input_set, evidence = staged
    phase = plan.phase(PHASE_Q1)
    world = World(plan, phase.cases[0], mode="cancel")  # never completes on its own
    world.stdout_on_start = ["RuntimeError: CUDA error: device-side assert triggered"]
    evidence.mkdir(exist_ok=True)
    obs = PhysicalExecutor(
        inputs=input_set.paths, evidence_root=evidence, seams=world.seams()
    ).run_case(plan, phase, phase.cases[0])
    assert obs.stop_code == STOP_DEVICE_LOSS and obs.telemetry_complete
    assert world.stops[0] == 0  # the hard stop uses no grace


def test_a_short_delivery_is_an_error_not_a_pass(staged) -> None:  # noqa: ANN001
    _, obs, _ = _run(staged, PHASE_Q1, 0, mode="short")
    assert not obs.completed and obs.stop_code == "executor_error"
    assert "Expected 17 PNG frames, found 16" in obs.note


def test_the_cancel_case_interrupts_once_and_delivers_zero_frames_cleanly(staged) -> None:  # noqa: ANN001
    world, obs, root = _run(staged, PHASE_Q2, 2, mode="cancel", cancel_after_seconds=1)
    assert world.interrupted.is_set()
    assert obs.completed and obs.frames_expected == obs.frames_delivered == 0
    assert not obs.stop_code and obs.teardown_clean
    assert (root / "queue-after-cancel.json").is_file()


def test_a_survivor_process_or_unreleased_vram_is_an_unsafe_teardown(staged) -> None:  # noqa: ANN001
    plan, input_set, evidence = staged
    phase = plan.phase(PHASE_Q1)
    world = World(plan, phase.cases[0])
    world.alive_after_stop = {4243}
    evidence.mkdir(exist_ok=True)
    obs = PhysicalExecutor(
        inputs=input_set.paths, evidence_root=evidence, seams=world.seams()
    ).run_case(plan, phase, phase.cases[0])
    assert obs.stop_code == STOP_TEARDOWN and not obs.teardown_clean

    world = World(plan, phase.cases[0])
    world.vram_after = 9000.0
    shutil_target = evidence / phase.cases[0].case_id
    import shutil

    shutil.rmtree(shutil_target)
    obs = PhysicalExecutor(
        inputs=input_set.paths, evidence_root=evidence, seams=world.seams()
    ).run_case(plan, phase, phase.cases[0])
    assert obs.stop_code == STOP_TEARDOWN and not obs.teardown_clean


def test_a_driver_fault_in_the_system_log_stops_the_case(staged) -> None:  # noqa: ANN001
    plan, input_set, evidence = staged
    phase = plan.phase(PHASE_Q1)
    world = World(plan, phase.cases[0])
    seams = world.seams()
    seams.event_log = lambda since: {"events": [{"Id": 4101, "ProviderName": "Display"}]}
    evidence.mkdir(exist_ok=True)
    obs = PhysicalExecutor(inputs=input_set.paths, evidence_root=evidence, seams=seams).run_case(
        plan, phase, phase.cases[0]
    )
    assert obs.stop_code == STOP_DEVICE_LOSS


def test_a_case_directory_is_never_reused(staged) -> None:  # noqa: ANN001
    _run(staged, PHASE_Q1, 0)
    with pytest.raises(FileExistsError):
        _run(staged, PHASE_Q1, 0)


def test_the_guarded_harness_drives_the_real_executor_through_every_phase_in_order(
    staged,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    plan, input_set, evidence = staged
    evidence.mkdir(exist_ok=True)
    worlds: dict[str, World] = {}

    class Routed(PhysicalExecutor):
        def run_case(self, plan, phase, case):  # noqa: ANN001
            fast = replace(case, cancel_after_seconds=1) if case.cancel_after_seconds else case
            world = worlds[case.case_id] = World(
                plan, fast, "cancel" if fast.cancel_after_seconds else "ok"
            )
            self.seams = world.seams()
            return super().run_case(plan, phase, fast)

    q0 = Q0Report(plan.digest, (), None)
    outcome = run_qualification(
        plan,
        q0,
        Routed(inputs=input_set.paths, evidence_root=evidence),
        Authorization(plan.digest, "owner"),
    )
    assert outcome.verdict == FEASIBLE, outcome.reason
    ran = [o.case_id for o in outcome.observations]
    assert ran == [c.case_id for p in plan.phases if p.physical for c in p.cases]
    assert CASE_Q2_A in ran and len(ran) == 1 + len(COVERAGE_ROLES) + 3


def test_the_first_resource_stop_ends_the_run_with_no_go_and_nothing_after_it(staged) -> None:  # noqa: ANN001
    plan, input_set, evidence = staged
    evidence.mkdir(exist_ok=True)
    seen: list[str] = []

    class Routed(PhysicalExecutor):
        def run_case(self, plan, phase, case):  # noqa: ANN001
            seen.append(case.case_id)
            world = World(plan, case, "oom" if phase.phase_id == PHASE_Q1C else "ok")
            self.seams = world.seams()
            return super().run_case(plan, phase, case)

    outcome = run_qualification(
        plan,
        Q0Report(plan.digest, (), None),
        Routed(inputs=input_set.paths, evidence_root=evidence),
        Authorization(plan.digest, "owner"),
    )
    assert outcome.verdict == NO_GO
    assert seen[-1].startswith("q1c_") and not any(c.startswith("q2_") for c in seen)
    assert outcome.verdict != INCONCLUSIVE


def test_the_physical_cli_refuses_a_digest_that_is_not_the_plans(tmp_path: Path) -> None:
    manifest, reference = _manifest(tmp_path)
    plan = load_input_set(manifest, reference).build_plan()
    stored = tmp_path / "plan.json"
    stored.write_text(json.dumps({**plan.to_record(), "digest": plan.digest}), encoding="utf-8")
    with pytest.raises(SystemExit, match="digest"):
        physical.main(
            [
                "--plan",
                str(stored),
                "--inputs-manifest",
                str(manifest),
                "--reference",
                str(reference),
                "--authorize-plan",
                "0" * 64,
                "--authorized-by",
                "owner",
                "--evidence-root",
                str(tmp_path / "evidence"),
            ]
        )
    assert not (tmp_path / "evidence").exists()  # refused before touching anything


def test_importing_the_executor_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    called: list[str] = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: called.append("run"))
    importlib.reload(physical)
    assert called == [] and isinstance(datetime.now(), datetime)
