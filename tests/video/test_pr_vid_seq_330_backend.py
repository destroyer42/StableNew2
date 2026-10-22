"""PR-VID-SEQ-330-CORE: the Comfy backend holds a StableNew-owned runtime for a sequence and releases it only through the
existing ownership interface. A single clip's lifecycle is unchanged; an unowned (external) process is never touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.video import VideoExecutionRequest
from src.video.video_backend_types import (
    CONTROL_NEGATIVE_PROMPT,
    CONTROL_PROMPT_TEXT,
    CONTROL_SOURCE_IMAGE,
)
from tests.video.test_wan22_experimental_workflow import WAN_ID, _backend, _FakeComfy

POLICY_VERSION = "1.2.0"  # declares release_owned_runtime_after_job
NO_POLICY_VERSION = "1.0.0"  # leaves a resident runtime running


def _request(tmp: Path, *, hold: bool, version: str = POLICY_VERSION) -> VideoExecutionRequest:
    source = tmp / "source.png"
    source.write_bytes(b"png")
    return VideoExecutionRequest(
        backend_id="comfy",
        stage_name="video_workflow",
        stage_config={
            "workflow_id": WAN_ID,
            "workflow_version": version,
            "seed": 7,
            "frame_count": 17,
            "source_preparation": {"target_dimensions": {"width": 480, "height": 832}},
        },
        output_dir=tmp / "run",
        input_image_path=source,
        prompt="the person waves",
        negative_prompt="blurry",
        job_id="job-1",
        workflow_id=WAN_ID,
        workflow_version=version,
        requested_controls=(CONTROL_SOURCE_IMAGE, CONTROL_PROMPT_TEXT, CONTROL_NEGATIVE_PROMPT),
        experimental_opt_in=version != POLICY_VERSION,
        hold_runtime=hold,
    )


def _released(backend) -> Mock:
    release = Mock(return_value={"released": True})
    backend._release_owned_runtime = release
    return release


def test_a_single_clip_still_releases_after_its_job(tmp_path: Path) -> None:
    backend = _backend(_FakeComfy(tmp_path))
    release = _released(backend)

    backend.execute(None, _request(tmp_path, hold=False))

    assert release.call_count == 1


def test_a_held_segment_leaves_the_owned_runtime_warm_on_success_and_on_failure(
    tmp_path: Path,
) -> None:
    backend = _backend(_FakeComfy(tmp_path))
    release = _released(backend)
    result = backend.execute(None, _request(tmp_path, hold=True))
    assert result is not None and release.call_count == 0
    assert (
        "runtime_release" not in result.backend_metadata
    )  # nothing was released, so nothing is claimed

    class Failing(_FakeComfy):
        def queue_prompt(self, payload, **_kw):
            raise RuntimeError("queue refused")

    failing = _backend(Failing(tmp_path))
    failing_release = _released(failing)
    with pytest.raises(RuntimeError, match="queue refused"):
        failing.execute(None, _request(tmp_path, hold=True))
    assert failing_release.call_count == 0  # the sequence's own end-of-job release is the only one


def test_the_sequence_release_goes_through_the_existing_ownership_interface(tmp_path: Path) -> None:
    backend = _backend(_FakeComfy(tmp_path))
    release = _released(backend)

    outcome = backend.release_for_sequence([(WAN_ID, POLICY_VERSION), (WAN_ID, POLICY_VERSION)])

    assert outcome == {"released": True} and release.call_count == 1  # deduplicated, one attempt


def test_a_sequence_of_workflows_without_the_policy_leaves_the_runtime_alone(
    tmp_path: Path,
) -> None:
    backend = _backend(_FakeComfy(tmp_path))
    release = _released(backend)

    assert backend.release_for_sequence([(WAN_ID, NO_POLICY_VERSION)]) == {
        "policy": "none_declared",
        "released": False,
    }
    assert backend.release_for_sequence([("no_such_workflow", "9.9.9")])["released"] is False
    assert release.call_count == 0


def test_an_unowned_runtime_is_never_stopped_and_an_owned_one_is_stopped_once(
    tmp_path: Path,
) -> None:
    def manager(*, owned: bool) -> SimpleNamespace:
        return SimpleNamespace(
            owns_process=owned,
            pid=4242,
            stop=Mock(),
            is_running=lambda: False,
            ensure_running=lambda: True,
            _config=SimpleNamespace(base_url="http://x"),
        )

    external = manager(owned=False)
    backend = _backend(_FakeComfy(tmp_path))
    backend._process_manager = external
    outcome = backend.release_for_sequence([(WAN_ID, POLICY_VERSION)])
    assert outcome["ownership"] == "not_owned" and outcome["released"] is False
    external.stop.assert_not_called()  # an external process is never adopted or stopped

    owned = manager(owned=True)
    backend._process_manager = owned
    outcome = backend.release_for_sequence([(WAN_ID, POLICY_VERSION)])
    assert outcome["ownership"] == "owned" and outcome["released"] is True
    owned.stop.assert_called_once_with()


# ----------------------------------------------------------------------------- readiness with a warm runtime


def _readiness(*, ram_gb: float, vram_free_mib: float = 11000.0):
    from src.video.workflow_readiness import WorkflowResourceReadiness

    return WorkflowResourceReadiness(
        ram_probe=lambda: ram_gb, gpu_probe=lambda _index: (12282.0, vram_free_mib)
    )


def _stats(*, held_mib: float = 0) -> dict:
    return {
        "devices": [
            {"type": "cuda", "index": 0, "torch_vram_total": held_mib * 1024 * 1024, "vram_free": 0}
        ]
    }


def _approved_spec():
    from src.video.workflow_registry import build_default_workflow_registry

    return build_default_workflow_registry().get(WAN_ID, "1.3.0")


def test_a_cold_load_and_a_single_clip_still_need_the_ram_floor() -> None:
    spec = _approved_spec()

    refused = _readiness(ram_gb=7.3).evaluate(spec, system_stats=_stats())

    assert refused.ready is False and "system RAM" in refused.message
    assert _readiness(ram_gb=24.0).evaluate(spec, system_stats=_stats()).ready is True


def test_a_warm_sequence_segment_is_not_refused_for_the_ram_its_resident_model_holds() -> None:
    spec = _approved_spec()
    readiness = _readiness(ram_gb=7.3)  # exactly what the first physical run saw after segment 0

    warm = readiness.evaluate(spec, system_stats=_stats(), warm_sequence=True)

    assert warm.ready is True and "already resident" in warm.observations["ram_floor_skipped"]


def test_the_gpu_memory_floor_still_applies_to_a_warm_sequence_segment() -> None:
    crowded = _readiness(ram_gb=7.3, vram_free_mib=500.0).evaluate(
        _approved_spec(), system_stats=_stats(held_mib=1000), warm_sequence=True
    )  # another process took the GPU

    assert crowded.ready is False and "GPU memory" in crowded.message


def _manager(*, pid: int, owned: bool = True, running: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        owns_process=owned,
        pid=pid,
        is_running=lambda: running,
        stop=Mock(),
        ensure_running=lambda: True,
    )


def test_only_the_same_owned_process_that_served_the_previous_segment_counts_as_warm() -> None:
    backend = _backend(_FakeComfy(Path(".")))
    assert backend._owned_running_pid() is None  # no manager provably owned: not warm

    backend._process_manager = _manager(pid=4242)
    assert backend._owned_running_pid() == 4242
    backend._process_manager = _manager(
        pid=4242, owned=False
    )  # an external runtime is never "ours"
    assert backend._owned_running_pid() is None
    backend._process_manager = _manager(pid=4242, running=False)
    assert backend._owned_running_pid() is None


def test_the_backend_asks_for_the_warm_floor_only_for_the_process_that_ran_the_last_segment(
    tmp_path: Path,
) -> None:
    class Spy:
        calls: list[bool] = []

        def policy_for(self, spec):
            return {"policy": "spy"}

        def evaluate(self, spec, *, system_stats, warm_sequence=False):
            Spy.calls.append(warm_sequence)
            return SimpleNamespace(ready=True, message="", to_dict=lambda: {})

    backend = _backend(_FakeComfy(tmp_path))
    backend._readiness = Spy()
    backend._process_manager = _manager(pid=111)
    _released(backend)

    backend.execute(None, _request(tmp_path, hold=True))  # first segment: nothing warm yet
    backend.execute(None, _request(tmp_path, hold=True))  # same process: warm
    backend._process_manager = _manager(pid=222)  # Comfy was restarted between segments: cold again
    backend.execute(None, _request(tmp_path, hold=True))
    backend.release_for_sequence([(WAN_ID, POLICY_VERSION)])
    backend._process_manager = _manager(pid=222)
    backend.execute(None, _request(tmp_path, hold=True))  # a new sequence starts cold

    assert Spy.calls == [False, True, False, False]
