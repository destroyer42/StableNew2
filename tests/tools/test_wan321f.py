"""Offline contracts for the WAN-321F proposal. No GPU, endpoint or model file reads."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from tools.qualification.wan321f.controls import (
    AttemptLedger,
    SafetyGuard,
    Sample,
    owned_session,
    physical_refusals,
    write_new_json,
)
from tools.qualification.wan321f.plan import (
    ASSETS,
    INPUT_SHA,
    asset_refusals,
    build_graph,
    digest,
    frozen_plan,
    inspect_file,
    source_refusals,
)


def sample(**changes):
    return replace(Sample(0, 50, 20, 12, 2, 3, 8000, 12282), **changes)


def guard():
    return SafetyGuard(frozen_plan()["safety_proposal"])


def test_two_experts_two_loras_and_correct_vae_are_not_ti2v():
    graph = build_graph(1)
    assert len(ASSETS) == 6
    assert sum(a.bytes for a in ASSETS) == 36953325927
    assert graph["8"]["inputs"]["vae_name"] == "wan_2.1_vae.safetensors"
    assert {n["class_type"] for n in graph.values()} == {
        "UNETLoader",
        "LoraLoaderModelOnly",
        "ModelSamplingSD3",
        "CLIPLoader",
        "VAELoader",
        "LoadImage",
        "WanImageToVideo",
        "CLIPTextEncode",
        "KSamplerAdvanced",
        "VAEDecode",
        "SaveImage",
    }
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
    assert graph["10"]["inputs"] == {
        "positive": ["11", 0],
        "negative": ["12", 0],
        "vae": ["8", 0],
        "width": 480,
        "height": 832,
        "length": 81,
        "batch_size": 1,
        "start_image": ["9", 0],
    }


def test_sampler_split_preserves_noise_and_conditioning():
    graph = build_graph(1)
    high, low = graph["13"]["inputs"], graph["14"]["inputs"]
    assert (
        high["start_at_step"],
        high["end_at_step"],
        high["add_noise"],
        high["return_with_leftover_noise"],
    ) == (0, 2, "enable", "enable")
    assert (
        low["start_at_step"],
        low["end_at_step"],
        low["add_noise"],
        low["return_with_leftover_noise"],
    ) == (2, 4, "disable", "disable")
    assert low["latent_image"] == ["13", 0]
    for key in ("steps", "cfg", "sampler_name", "scheduler", "noise_seed", "positive", "negative"):
        assert high[key] == low[key]
    assert high["steps"] == 4 and high["cfg"] == 1.0
    assert graph["5"]["inputs"]["shift"] == graph["6"]["inputs"]["shift"] == 5.0
    assert graph["15"]["inputs"]["samples"] == ["14", 0]
    assert graph["16"]["inputs"]["images"] == ["15", 0]


def test_stock_schedule_matches_accepted_publisher_sigmas():
    # Pinned ModelSamplingDiscreteFlow uses 1000 points (1..1000)/1000.
    # simple_scheduler selects indices 999,749,499,249 then appends zero.
    # Independent numeric comparison to the accepted explicit sigma list.
    shifted = [5 * t / (1 + 4 * t) for t in (1, 0.75, 0.5, 0.25)] + [0]
    assert shifted == pytest.approx([1, 0.9375001, 0.8333333, 0.625, 0], abs=1.1e-7)


def test_frozen_attempts_are_independent_and_cannot_be_cache_hits():
    graphs = [build_graph(i) for i in (1, 2, 3)]
    assert len({g["13"]["inputs"]["noise_seed"] for g in graphs}) == 3
    assert len({digest(g) for g in graphs}) == 3
    graphs[0]["10"]["inputs"]["length"] = 1
    assert build_graph(1)["10"]["inputs"]["length"] == 81
    assert digest(frozen_plan()) == digest(frozen_plan())


@pytest.mark.parametrize("attempt", [0, 4, -1, 1.0, True, "1"])
def test_no_extra_attempts_or_dynamic_graph(attempt):
    with pytest.raises(ValueError):
        build_graph(attempt)


def test_plan_keeps_physical_operations_disabled():
    plan = frozen_plan()
    assert not any(plan["authorization"].values())
    assert not plan["safety_proposal"]["owner_accepted"]
    assert plan["budget"]["automatic_retries"] is None
    assert len(physical_refusals()) == 3
    assert plan["input"]["sha256"] == INPUT_SHA


def test_frozen_proposal_digest_and_exact_stock_launch_policy():
    plan = frozen_plan()
    assert digest(plan) == "c795fa82ffc1309a3df57df6662b34ad9b3164af526e76cf4a35ae7f7f85eb97"
    command = plan["launch_command"]
    assert command[0].endswith("v0.38.0-py313/venv/Scripts/python.exe")
    assert command[command.index("--port") + 1] == "8197"
    assert command[-3:] == [
        "--disable-pinned-memory",
        "--disable-auto-launch",
        "--disable-all-custom-nodes",
    ]
    assert not any(x in command for x in ("--cache-none", "--lowvram", "--highvram"))
    check = Mock(
        side_effect=lambda path, size, expected: "source drift"
        if path.endswith("samplers.py")
        else ""
    )
    assert source_refusals(check) == ["source drift"]
    assert check.call_count == 5


def test_preflight_reports_every_missing_asset_and_input_without_substitution():
    inspector = Mock(side_effect=lambda path, size, expected: f"missing: {path}")
    assert len(asset_refusals(inspector)) == 7
    assert inspector.call_count == 7
    assert [c.args[0] for c in inspector.call_args_list[:6]] == [a.local_path for a in ASSETS]


def test_real_hash_preflight_refuses_missing_changed_and_wrong_size(tmp_path):
    path = tmp_path / "asset"
    assert inspect_file(str(path), 3, "x").startswith("missing")
    path.write_bytes(b"abc")
    assert inspect_file(str(path), 2, "x").startswith("size mismatch")
    assert inspect_file(str(path), 3, "x").startswith("hash mismatch")
    assert (
        inspect_file(
            str(path), 3, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        == ""
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("commit_percent", 97, "system commit"),
        ("commit_headroom_gib", 0.99, "commit headroom"),
        ("physical_available_gib", 0.24, "physical RAM"),
    ],
)
def test_sustained_safety_stops_latch(field, value, reason):
    safety = guard()
    assert not safety.observe(sample(**{field: value}))
    assert reason in safety.observe(sample(elapsed=0.5, **{field: value}))
    assert reason in safety.observe(sample(elapsed=1))


def test_recovery_resets_counters_and_boundary_is_not_below_floor():
    safety = guard()
    assert not safety.observe(sample(commit_headroom_gib=0.9))
    assert not safety.observe(
        sample(elapsed=0.5, commit_headroom_gib=1, physical_available_gib=0.25)
    )
    assert not safety.observe(sample(elapsed=1, commit_headroom_gib=0.9))


@pytest.mark.parametrize(
    "bad,reason",
    [
        (None, "missing telemetry"),
        (sample(device_loss=True), "GPU unavailable"),
        (sample(gpu_ok=False), "GPU unavailable"),
        (sample(commit_headroom_gib=float("nan")), "invalid telemetry"),
        (sample(owned_private_gib=-1), "invalid telemetry"),
        (sample(vram_total_mib=0), "inconsistent telemetry"),
        (sample(commit_percent=101), "inconsistent telemetry"),
        (sample(elapsed=1200), "attempt time limit"),
    ],
)
def test_telemetry_failure_and_time_limit_stop_immediately(bad, reason):
    assert reason in guard().observe(bad)


@pytest.mark.parametrize(
    "field,value", [("gpu_ok", "unknown"), ("device_loss", None), ("gpu_ok", 1)]
)
def test_gpu_status_requires_known_boolean_telemetry(field, value):
    assert "invalid GPU status" in guard().observe(sample(**{field: value}))


@pytest.mark.parametrize("elapsed", [0, -0.5, 2.1])
def test_no_stale_or_reversed_sample(elapsed):
    safety = guard()
    assert not safety.observe(sample())
    assert safety.observe(sample(elapsed=elapsed))


def test_invalid_policy_is_not_a_disabled_guard():
    policy = frozen_plan()["safety_proposal"]
    for value in (0, -1, float("nan"), True, None):
        with pytest.raises(ValueError):
            SafetyGuard({**policy, "attempt_seconds": value})


def test_one_dispatch_and_evidence_exists_before_callback(tmp_path):
    ledger = AttemptLedger(tmp_path)

    def submit(payload):
        assert json.loads((tmp_path / "attempt-1/graph.json").read_text()) == payload["prompt"]
        assert (tmp_path / "attempt-1/dispatch-intent.json").is_file()
        return {"prompt_id": "frozen-attempt-1"}

    dispatch = Mock(side_effect=submit)
    assert ledger.dispatch_once(1, dispatch)["prompt_id"] == "frozen-attempt-1"
    with pytest.raises(FileExistsError):
        AttemptLedger(tmp_path).dispatch_once(1, dispatch)
    assert dispatch.call_count == 1


@pytest.mark.parametrize(
    "error", [TimeoutError("ambiguous"), KeyboardInterrupt(), RuntimeError("OOM")]
)
def test_unresolved_dispatch_is_never_replayed_and_evidence_survives(tmp_path, error):
    dispatch = Mock(side_effect=error)
    with pytest.raises(type(error)):
        AttemptLedger(tmp_path).dispatch_once(1, dispatch)
    assert (tmp_path / "attempt-1/dispatch-unresolved.json").is_file()
    with pytest.raises(FileExistsError):
        AttemptLedger(tmp_path).dispatch_once(1, dispatch)
    assert dispatch.call_count == 1


@pytest.mark.parametrize("reply", [{}, None, {"prompt_id": ""}, {"prompt_id": 1}])
def test_invalid_dispatch_ack_is_ambiguous(tmp_path, reply):
    with pytest.raises(ValueError, match="unresolved"):
        AttemptLedger(tmp_path).dispatch_once(1, lambda _: reply)
    assert (tmp_path / "attempt-1/dispatch-unresolved.json").is_file()


def test_evidence_is_never_overwritten(tmp_path):
    path = tmp_path / "record.json"
    write_new_json(path, {"first": True})
    with pytest.raises(FileExistsError):
        write_new_json(path, {"first": False})
    assert json.loads(path.read_text()) == {"first": True}


def test_evidence_write_failure_prevents_dispatch(tmp_path, monkeypatch):
    def no_write(*args):
        raise OSError("disk full")

    monkeypatch.setattr("tools.qualification.wan321f.controls.write_new_json", no_write)
    dispatch = Mock()
    with pytest.raises(OSError, match="disk full"):
        AttemptLedger(tmp_path).dispatch_once(1, dispatch)
    dispatch.assert_not_called()
    with pytest.raises(FileExistsError):
        AttemptLedger(tmp_path).dispatch_once(1, dispatch)


class FakeManager:
    def __init__(self, *, contained=True, external=False):
        self.owns_process = False
        self.contained = contained
        self.external = external
        self.stops = 0

    def start(self):
        if self.external:
            raise RuntimeError("external endpoint occupied")
        self.owns_process = True

    def stop(self):
        self.stops += 1
        self.owns_process = False

    def is_running(self):
        return self.owns_process


@pytest.mark.parametrize("error", [None, RuntimeError("safety stop"), KeyboardInterrupt()])
def test_owned_manager_cleanup_for_success_failure_and_interrupt(error):
    manager = FakeManager()
    if error is None:
        with owned_session(manager):
            assert manager.owns_process
    else:
        with pytest.raises(type(error)), owned_session(manager):
            raise error
    assert manager.stops == 1 and not manager.owns_process


def test_external_runtime_is_never_stopped():
    manager = FakeManager(external=True)
    with pytest.raises(RuntimeError, match="external"), owned_session(manager):
        pytest.fail("external runtime reached execution")
    assert manager.stops == 0


def test_uncontained_owned_child_is_stopped_before_dispatch():
    manager = FakeManager(contained=False)
    with pytest.raises(RuntimeError, match="containment"), owned_session(manager):
        pytest.fail("uncontained child reached execution")
    assert manager.stops == 1


def test_preexisting_manager_child_is_not_reused_or_stopped():
    manager = FakeManager()
    manager.owns_process = True
    with pytest.raises(RuntimeError, match="prior child"), owned_session(manager):
        pytest.fail("prior child reused")
    assert manager.stops == 0


def test_unverified_teardown_precludes_a_pass():
    manager = FakeManager()
    manager.stop = lambda: None
    with pytest.raises(RuntimeError, match="teardown unverified"), owned_session(manager):
        pass
