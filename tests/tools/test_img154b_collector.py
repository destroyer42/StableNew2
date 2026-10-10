"""PR-IMG-MODELS-154B T67-T72: live-preflight assembly from injected host readers (no host is read)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tools.qualification.img154 import evidence as ev
from tools.qualification.img154 import isolation as iso
from tools.qualification.img154 import manifest as mf
from tools.qualification.img154 import preflight as pf
from tools.qualification.img154.core import GIB, Finding, Observation
from tools.qualification.img154b import collector as co
from tools.qualification.img154b import request as rq
from tools.qualification.img154b import runtime as rt
from tools.qualification.img154b import sampler as sp

BOOT = "2026-01-01T00:00:00+00:00"
DEVICE = "device-digest-1"
GOOD_CODE = {"state": "clean", "sha": "a" * 40, "source_sha256": "b" * 64}


class World:
    """A fake host. ``log`` records the order in which readers are called."""

    def __init__(self):
        self.now = 1000.0
        self.log: list[str] = []
        self.memory = {
            "commit_total_bytes": 10 * GIB,
            "commit_limit_bytes": 50 * GIB,
            "commit_headroom_bytes": 40 * GIB,
            "ram_available_bytes": 24 * GIB,
        }
        self.gpu = {
            "vram_used_bytes": int(2.3 * GIB),
            "vram_total_bytes": 12 * GIB,
            "gpu_temperature_c": 44.0,
            "gpu_utilization_percent": 3.0,
            "gpu_board_power_w": 28.0,
            "gpu_device_present": True,
        }
        self.pdh = {"shared_vram_bytes": int(0.3 * GIB), "hard_pages_input_per_s": 2.0}
        self.status: dict[str, str] = {}
        self.raises: dict[str, Exception] = {}
        self.processes: list[iso.ProcessObservation] | None = []
        self.port = iso.PortObservation("127.0.0.1", 7886, "free", "fake")
        self.served = rt.ServedProof({}, {}, ())
        self.unchanged: list[Finding] = []
        self.faults = ev.FaultSnapshot(
            "2026-01-01T12:00:00+00:00",
            BOOT,
            {
                name: ev.FaultSourceSnapshot(name, "complete", frozenset({"1"}))
                for name in ev.FAULT_SOURCES
            },
        )
        self.code = dict(GOOD_CODE)
        self.semantics_text: dict[str, str | None] | None = None
        self.device: str | None = DEVICE
        self.isolation: list[Finding] = []
        self.pin: list[Finding] = []
        self.launch: list[Finding] = []
        self.storage: list[Finding] = []
        self.process_tree_ok = True
        self.pagefile_status = "ok"
        self.workspace = "none"

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def provider(self, name, fields, source):
        world = self

        class P:
            def __init__(self):
                self.name, self.fields = name, tuple(fields)

            def read(self):
                world.log.append(f"read:{name}")
                if name in world.raises:
                    raise world.raises[name]
                values = {k: source[k] for k in fields}
                status = {k: world.status.get(k, "ok") for k in fields}
                return sp.ProviderReading(values, status, f"fake {name}")

        return P()

    def readers(self, **overrides) -> co.HostReaders:
        w = self

        def logged(name, value):
            def reader(*args):
                w.log.append(name)
                return value() if callable(value) else value

            return reader

        def source_reader(relative):
            return (
                w.semantics_text.get(relative)
                if w.semantics_text is not None
                else FULL_SOURCE.get(relative)
            )

        values = {
            "code_revision": logged("code", lambda: dict(w.code)),
            "read_source": source_reader,
            "isolation_findings": logged("isolation", lambda: list(w.isolation)),
            "pin_findings": logged("pin", lambda: list(w.pin)),
            "served_proof": logged("served", lambda: w.served),
            "served_unchanged": logged("served_recheck", lambda: list(w.unchanged)),
            "launch_findings": logged("launch", lambda: list(w.launch)),
            "storage_findings": logged("storage", lambda: list(w.storage)),
            "port": logged("port", lambda: w.port),
            "processes": logged(
                "processes", lambda: None if w.processes is None else list(w.processes)
            ),
            "providers": [
                self.provider("windows_memory", sp.NativeMemoryProvider.fields, self.memory),
                self.provider("nvml", sp.NvmlProvider.fields, self.gpu),
                self.provider("windows_pdh", sp.PdhProvider.fields, self.pdh),
            ],
            "pagefile_free": logged(
                "pagefile",
                lambda: Observation(
                    "pagefile_volume_free_bytes",
                    80 * GIB,
                    "bytes",
                    "fake",
                    w.now,
                    "2026-01-01T12:00:00+00:00",
                    w.pagefile_status,
                ),
            ),
            "evidence_free": logged(
                "evidence_free",
                lambda: Observation(
                    "evidence_volume_free_bytes",
                    50 * GIB,
                    "bytes",
                    "fake",
                    w.now,
                    "2026-01-01T12:00:00+00:00",
                    "ok",
                ),
            ),
            "fault_snapshot": logged("faults", lambda: w.faults),
            "device_id": logged("device", lambda: w.device),
            "workspace_ledger_state": logged("workspace", lambda: w.workspace),
            "process_tree_capable": lambda: w.process_tree_ok,
            "evidence_dir_valid": logged("evidence_dir", True),
            "mono": self.clock,
            "utc": lambda: "2026-01-01T12:00:00+00:00",
            "sleep": self.sleep,
            "environment": lambda: {"python": "3.x"},
            "baseline_seconds": 25.0,
            "baseline_interval_s": 1.0,
        }
        values.update(overrides)
        return co.HostReaders(**values)


FIELD_LINES = {
    "prompt": '    prompt: str = ""',
    "negative_prompt": '    negative_prompt: str = ""',
    "seed": "    seed: int = -1",
    "steps": "    steps: int = 50",
    "sampler_name": "    sampler_name: str = None",
    "scheduler": "    scheduler: str = None",
    "cfg_scale": "    cfg_scale: float = 7.0",
    "distilled_cfg_scale": "    distilled_cfg_scale: float = 3.5",
    "width": "    width: int = 512",
    "height": "    height: int = 512",
    "batch_size": "    batch_size: int = 1",
    "n_iter": "    n_iter: int = 1",
    "send_images": '{"key": "send_images", "type": bool, "default": True},',
    "save_images": '{"key": "save_images", "type": bool, "default": False},',
}


def full_source() -> dict[str, str]:
    """A text tree that states exactly the anchored fragments and defines every payload key."""

    files: dict[str, list[str]] = {}
    for anchor in rq.PINNED_ANCHORS:
        files.setdefault(anchor.file, []).extend((*anchor.present, *anchor.ordered))
    for key, (relative, _) in rq.PAYLOAD_KEY_SOURCES.items():
        files.setdefault(relative, []).append(FIELD_LINES[key])
    newline = chr(10)
    return {relative: newline.join(lines) + newline for relative, lines in files.items()}


FULL_SOURCE = full_source()


def collect(world: World | None = None, **overrides):
    world = world or World()
    plan = mf.build_manifest()
    collector = co.LiveCollector(
        world.readers(**overrides), manifest=plan, payload=rq.build_txt2img_payload(plan)
    )
    return world, collector, collector.collect()


def evaluate(collected, world, *, risk=True, ledger="none"):
    inputs = replace(collected.inputs, residual_gpu_risk_accepted=risk or None, ledger_state=ledger)
    return pf.evaluate_preflight(inputs, now_mono_s=world.now, now_utc="2026-01-01T12:00:00+00:00")


# --- T67 -----------------------------------------------------------------------------------------------------------------


def test_t67_a_clean_host_assembles_inputs_that_the_154a_evaluator_prepares():
    world, _, collected = collect()
    result = evaluate(collected, world)
    assert result.decision == pf.PREPARED, result.reason_codes
    assert collected.boot_id == BOOT and collected.device_id == DEVICE
    assert collected.inputs.quiescent_baseline.acquired_by == pf.BASELINE_PROVIDER
    assert len(collected.inputs.quiescent_baseline.samples) >= 20
    assert collected.inputs.launch_device_id == DEVICE and collected.inputs.launch_boot_id == BOOT


def test_t67_slow_evidence_comes_first_and_the_threshold_readings_come_last():
    world, _, _ = collect()
    log = world.log
    assert log.index("served") < log.index("faults") < log.index("device")
    last_provider_read = max(i for i, item in enumerate(log) if item.startswith("read:"))
    assert last_provider_read > log.index("port") and last_provider_read > log.index("processes")
    assert log.index("pagefile") > log.index("port")
    assert (
        log[-1] in ("workspace", "evidence_dir", "evidence_free", "pagefile")
        or log.count("pagefile") == 1
    )


def test_t67_the_baseline_is_acquired_by_the_sampler_over_a_window_never_asserted():
    world, collector, collected = collect()
    window = collected.inputs.quiescent_baseline
    assert window.competing_runtime_free is True
    times = [s.mono_s for s in window.samples]
    assert times == sorted(times) and times[-1] - times[0] >= 25.0
    assert all(s.vram_used_bytes == int(2.3 * GIB) for s in window.samples)
    validated, findings = pf.validate_quiescent_baseline(
        window, now_mono_s=world.now, launch_device_id=DEVICE, launch_boot_id=BOOT
    )
    assert validated is not None, findings


# --- T68: every unobtainable reading is a non-ok observation -------------------------------------------------------------


@pytest.mark.parametrize("provider", ["windows_memory", "nvml", "windows_pdh"])
def test_t68_a_provider_that_raises_becomes_visible_errors_and_unavailable_coverage(provider):
    world = World()
    world.raises[provider] = OSError("counter unavailable")
    _, _, collected = collect(world)
    errors = [o for o in collected.inputs.observations.values() if o.status == "error"]
    assert errors
    result = evaluate(collected, world)
    assert result.decision != pf.PREPARED
    if provider != "windows_pdh":
        assert any(v == "unavailable" for v in collected.inputs.telemetry_coverage.values())


def test_t68_a_field_the_provider_marks_missing_never_becomes_a_value():
    world = World()
    world.status["gpu_temperature_c"] = "missing"
    _, _, collected = collect(world)
    item = collected.inputs.observations["gpu_temperature_c"]
    assert item.status == "missing" and item.value is None
    assert collected.inputs.telemetry_coverage["gpu_temperature_c"] == "unavailable"
    assert evaluate(collected, world).decision == pf.INCONCLUSIVE


def test_t68_a_failed_baseline_window_is_inconclusive_not_a_pass():
    world = World()
    world.status["vram_used_bytes"] = "error"
    _, _, collected = collect(world)
    result = evaluate(collected, world)
    assert result.decision != pf.PREPARED
    assert "BASELINE_VRAM_INCOMPLETE" in result.reason_codes


# --- T69: sections -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr,value,reason",
    [
        ("isolation", [Finding("ISOLATION_INSIDE_RESERVED", "refuse", "x")], pf.REFUSED_ISOLATION),
        ("launch", [Finding("LAUNCH_FLAG_SET", "refuse", "x")], pf.REFUSED_ISOLATION),
        ("storage", [Finding("STORAGE_INSUFFICIENT", "refuse", "x")], pf.REFUSED_ISOLATION),
        ("pin", [Finding("PIN_MARKER_MISMATCH", "refuse", "x")], pf.REFUSED_RUNTIME_PIN),
        (
            "port",
            iso.PortObservation("127.0.0.1", 7886, "occupied", "fake"),
            pf.REFUSED_RUNTIME_CONFLICT,
        ),
        ("port", iso.PortObservation("127.0.0.1", 7886, "unverifiable", "fake"), pf.INCONCLUSIVE),
        ("port", iso.PortObservation("0.0.0.0", 7886, "free", "fake"), pf.REFUSED_RUNTIME_CONFLICT),
        (
            "processes",
            [
                iso.ProcessObservation(
                    7, "python.exe", ("python", "launch.py", "webui"), (7860,), "unknown"
                )
            ],
            pf.REFUSED_RUNTIME_CONFLICT,
        ),
        ("processes", None, pf.INCONCLUSIVE),
    ],
)
def test_t69_each_section_failure_changes_the_decision(attr, value, reason):
    world = World()
    setattr(world, attr, value)
    _, _, collected = collect(world)
    result = evaluate(collected, world)
    assert result.decision == reason


def test_t69_an_external_runtime_during_the_baseline_window_invalidates_the_baseline():
    world = World()
    world.processes = [
        iso.ProcessObservation(9, "python.exe", ("python", "webui.py"), (), "external")
    ]
    _, _, collected = collect(world)
    assert collected.inputs.quiescent_baseline.competing_runtime_free is False
    assert evaluate(collected, world).decision != pf.PREPARED


def test_t69_an_unreadable_process_list_leaves_the_baseline_runtime_absence_unknown():
    world = World()
    world.processes = None
    _, _, collected = collect(world)
    assert collected.inputs.quiescent_baseline.competing_runtime_free is None
    assert "BASELINE_COMPETING_RUNTIME_UNKNOWN" in evaluate(collected, world).reason_codes


def test_t69_served_file_findings_block_as_asset_identity():
    world = World()
    world.served = rt.ServedProof({}, {}, (Finding("ASSET_SHA256_MISMATCH", "refuse", "vae"),))
    _, _, collected = collect(world)
    assert evaluate(collected, world).decision == pf.REFUSED_ASSET_IDENTITY


# --- T70: semantics and payload ------------------------------------------------------------------------------------------


def test_t70_a_source_that_no_longer_states_the_reconciled_semantics_blocks_the_intent_section():
    world = World()
    drifted = dict(FULL_SOURCE)
    drifted["modules/processing.py"] = drifted["modules/processing.py"].replace(
        "self.sd_model.set_shift(shift=self.distilled_cfg_scale)", "# shift handling moved"
    )
    world.semantics_text = drifted
    _, _, collected = collect(world)
    result = evaluate(collected, world)
    assert result.decision == pf.REFUSED_INTENT_DRIFT
    assert "SEMANTICS_ANCHOR_MISSING" in result.reason_codes
    assert "SEMANTICS_ANCHOR_MISSING" in collected.facts["semantics_findings"]


def test_t70_an_unreadable_source_tree_is_inconclusive_not_verified():
    world = World()
    world.semantics_text = {}
    _, _, collected = collect(world)
    assert evaluate(collected, world).decision == pf.INCONCLUSIVE


# --- T71: remeasure and recheck ------------------------------------------------------------------------------------------


def test_t71_remeasure_returns_fresh_readings_a_new_window_a_new_fault_snapshot_and_the_device_identity():
    world, collector, collected = collect()
    world.now += 600.0  # the operator's unbounded wait
    world.memory["commit_headroom_bytes"] = 31 * GIB
    world.faults = ev.FaultSnapshot(
        "2026-01-01T12:10:00+00:00",
        BOOT,
        {
            name: ev.FaultSourceSnapshot(name, "complete", frozenset({"1", "2"}))
            for name in ev.FAULT_SOURCES
        },
    )
    fresh = collector.remeasure()
    assert fresh.observations["commit_headroom_bytes"].value == 31 * GIB
    assert fresh.observations["commit_headroom_bytes"].observed_mono_s == world.now
    assert fresh.observations["gpu_device_id"].value == DEVICE
    assert fresh.observations["gpu_device_id"].status == "ok"
    # a window of its own, ending at the new time (the original one is far past the 60 s limit)
    assert fresh.quiescent_baseline is not None
    assert (
        fresh.quiescent_baseline.samples[-1].mono_s
        > collected.inputs.quiescent_baseline.samples[-1].mono_s + 500
    )
    validated, findings = pf.validate_quiescent_baseline(
        fresh.quiescent_baseline, now_mono_s=world.now, launch_device_id=DEVICE, launch_boot_id=BOOT
    )
    assert validated is not None, findings
    assert fresh.fault_before is world.faults and collector.fault_before is world.faults
    world.device = None
    assert collector.remeasure().observations["gpu_device_id"].status == "missing"


def test_t71_an_unwired_served_recheck_is_a_refusal_never_a_silent_pass():
    world = World()
    readers = world.readers(
        served_unchanged=lambda: [Finding("SERVED_RECHECK_NOT_WIRED", "refuse", "x")]
    )
    collector = co.LiveCollector(readers, payload=rq.build_txt2img_payload())
    assert [f.code for f in collector.recheck_served()] == ["SERVED_RECHECK_NOT_WIRED"]


def test_t72_code_revision_comes_from_the_read_only_probe_and_dirty_trees_are_not_trusted():
    world = World()
    world.code = {"state": "dirty", "sha": "a" * 40, "source_sha256": "b" * 64}
    _, _, collected = collect(world)
    assert collected.code.state == "dirty" and not collected.code.trusted
    world.code = {"state": "unverifiable", "sha": None, "source_sha256": "b" * 64}
    _, _, collected = collect(world)
    assert not collected.code.trusted


@pytest.mark.parametrize(
    "port,processes,expected",
    [
        (iso.PortObservation("127.0.0.1", 7886, "occupied"), [], "RUNTIME_PORT_OCCUPIED"),
        (iso.PortObservation("127.0.0.1", 7886, "unverifiable"), [], "RUNTIME_PORT_UNVERIFIED"),
        (None, [], "PORT_NOT_OBSERVED"),
        (iso.PortObservation("127.0.0.1", 7886, "free"), None, "PROCESS_LIST_UNAVAILABLE"),
        (
            iso.PortObservation("127.0.0.1", 7886, "free"),
            [iso.ProcessObservation(9, "webui.py")],
            "RUNTIME_CONFLICT_FOREIGN_OWNER",
        ),
    ],
)
def test_r3_remeasure_refreshes_runtime_sections(port, processes, expected):
    world, collector, _ = collect()
    world.port, world.processes = port, processes
    fresh = collector.remeasure()
    assert expected in [f.code for findings in fresh.sections.values() for f in findings]
    assert fresh.runtime_observed_mono_s <= world.now


def test_r2_collector_reads_current_code_identity_instead_of_saved_code():
    world, collector, _ = collect()
    world.code = {"state": "unverifiable", "sha": None, "source_sha256": None}
    assert not collector.recheck_code().trusted


@pytest.mark.parametrize("reader", ["port", "processes"])
def test_r3_runtime_assessment_reader_exception_is_unknown(reader):
    world, collector, _ = collect()

    def unavailable():
        raise TimeoutError("timed out")

    setattr(collector.readers, reader, unavailable)
    when, sections = collector._runtime_assessment()
    expected = "PORT_NOT_OBSERVED" if reader == "port" else "PROCESS_LIST_UNAVAILABLE"
    assert any(f.code == expected for findings in sections.values() for f in findings)


def test_r3_runtime_timestamp_precedes_slow_inventory():
    world, collector, _ = collect()
    start = world.now

    def processes():
        world.sleep(31)
        return []

    collector.readers.processes = processes
    when, _ = collector._runtime_assessment()
    assert when == start and world.now - when == 31
