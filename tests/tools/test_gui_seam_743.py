"""GUI-SEAM-743 ordinary-CI tests: pump-parameter injection, the real ``TkInvoker._pump`` under every candidate, and the
evidence validators. No window, no PySide6, no GPU and no operator data; the native proof stays opt-in."""

from __future__ import annotations

import copy
import math
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from src.gui import gui_invoker
from src.gui.gui_invoker import TkInvoker
from src.gui.ui_dispatcher import release_tk_dispatcher, tk_dispatcher_for
from tools.qualification.gui_port_742.evidence import EvidenceError, summarize
from tools.qualification.gui_seam_743 import evidence as ev
from tools.qualification.gui_seam_743 import run as run743
from tools.qualification.gui_seam_743.config import (
    CONTROL,
    MATRIX,
    WORKLOAD,
    ConfigError,
    PumpConfig,
    balanced_order,
    plan_runs,
    validate_confirmations,
    validate_matrix,
    varied_dimensions,
)
from tools.qualification.gui_seam_743.inject import (
    configure,
    deferred_first_pump,
    dispatcher_with_config,
    effective_parameters,
    observe,
    production_defaults,
)

ALL = [*MATRIX, PumpConfig("H", 10, 64, 8.0)]


class FakeRoot:
    def __init__(self) -> None:
        self.calls: list[tuple[int, Any]] = []

    def after(self, delay_ms: int, fn: Any) -> None:
        self.calls.append((delay_ms, fn))


def armed(config: PumpConfig) -> tuple[FakeRoot, TkInvoker]:
    """A production invoker with ``config`` in force before its first timer, built exactly as the child builds it."""

    root = FakeRoot()
    with deferred_first_pump():
        invoker = TkInvoker(root)  # type: ignore[arg-type]
    assert root.calls == []
    configure(invoker, config)
    return root, invoker


def pump(root: FakeRoot) -> None:
    root.calls[-1][1]()


# ----- 1-5: parameters ------------------------------------------------------------------------------------------------
def test_production_defaults_are_exactly_15_32_8_and_are_the_control() -> None:
    assert production_defaults() == {"interval_ms": 15, "max_callbacks": 32, "max_pump_ms": 8.0}
    assert production_defaults() == CONTROL.parameters()
    assert (TkInvoker._schedule_pump.__name__, TkInvoker._pump.__name__) == (
        "_schedule_pump",
        "_pump",
    )


def test_experimental_parameters_apply_only_to_the_proof_instance() -> None:
    original = TkInvoker._schedule_pump
    _root, tuned = armed(PumpConfig("Z", 5, 128, 12.0))
    assert effective_parameters(tuned) == {
        "interval_ms": 5,
        "max_callbacks": 128,
        "max_pump_ms": 12.0,
    }
    assert TkInvoker._schedule_pump is original
    fresh_root = FakeRoot()
    fresh = TkInvoker(fresh_root)  # type: ignore[arg-type]
    assert effective_parameters(fresh) == CONTROL.parameters()
    assert fresh_root.calls[0][0] == 15
    assert production_defaults() == CONTROL.parameters()
    fresh.dispose()
    tuned.dispose()


def test_deferred_first_pump_restores_the_method_even_on_error() -> None:
    original = TkInvoker._schedule_pump
    with pytest.raises(RuntimeError), deferred_first_pump():
        raise RuntimeError("boom")
    assert TkInvoker._schedule_pump is original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval_ms": 0},
        {"interval_ms": 101},
        {"interval_ms": True},
        {"interval_ms": 7.5},
        {"max_callbacks": 0},
        {"max_callbacks": 1025},
        {"max_callbacks": 2.5},
        {"max_pump_ms": float("nan")},
        {"max_pump_ms": float("inf")},
        {"max_pump_ms": 0.1},
        {"max_pump_ms": 51},
        {"max_pump_ms": True},
        {"name": ""},
        {"name": "not valid"},
    ],
)
def test_invalid_parameters_are_rejected_before_any_gui(kwargs: dict[str, Any]) -> None:
    base = {"name": "Z", "interval_ms": 15, "max_callbacks": 32, "max_pump_ms": 8.0} | kwargs
    with pytest.raises(ConfigError):
        PumpConfig(**base).validate()


def test_bad_confirmation_never_launches_a_child_or_creates_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tools.qualification.gui_port_742.launch as launch

    monkeypatch.setattr(launch, "run_child", lambda *a, **k: pytest.fail("a child was launched"))
    out = tmp_path / "evidence"
    primary = tmp_path / "primary.json"
    primary.write_text("{}", encoding="utf8")
    for bad in ("H=0,64,8", "H=10,64", "H=5,256,8", "A=10,64,8", "H=15,32,8"):
        with pytest.raises(SystemExit):
            run743.main(
                [
                    "--allow-gui",
                    "--phase",
                    "confirmation",
                    "--confirm",
                    bad,
                    "--primary",
                    str(primary),
                    "--output",
                    str(out),
                ]
            )
    with pytest.raises(SystemExit):  # three confirmations exceed the cap
        run743.main(
            [
                "--allow-gui",
                "--phase",
                "confirmation",
                "--primary",
                str(primary),
                "--output",
                str(out),
            ]
            + [x for c in ("H=10,64,8", "I=5,64,8", "J=10,128,4") for x in ("--confirm", c)]
        )
    assert not out.exists()


def test_without_allow_gui_nothing_runs(capsys: pytest.CaptureFixture[str]) -> None:
    assert run743.main(["--output", "C:/never"]) == 2
    assert "NOT RUN" in capsys.readouterr().out


def test_configure_reports_effective_values_and_refuses_an_armed_invoker() -> None:
    config = PumpConfig("Z", 10, 64, 4.0)
    root, invoker = armed(config)
    assert root.calls == [(10, root.calls[0][1])]
    with pytest.raises(ConfigError):
        configure(invoker, config)
    invoker.dispose()
    plain = TkInvoker(FakeRoot())  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        configure(plain, config)  # already armed at the production interval


def test_matrix_matches_the_contract_and_changes_one_dimension_each() -> None:
    validate_matrix()
    table = {c.name: (c.interval_ms, c.max_callbacks, c.max_pump_ms) for c in MATRIX}
    assert table == {
        "A": (15, 32, 8.0),
        "B": (10, 32, 8.0),
        "C": (5, 32, 8.0),
        "D": (15, 64, 8.0),
        "E": (15, 128, 8.0),
        "F": (15, 32, 4.0),
        "G": (15, 32, 12.0),
    }
    only = {c.name: varied_dimensions(c) for c in MATRIX[1:]}
    assert only == {
        "B": ("interval_ms",),
        "C": ("interval_ms",),
        "D": ("max_callbacks",),
        "E": ("max_callbacks",),
        "F": ("max_pump_ms",),
        "G": ("max_pump_ms",),
    }
    assert varied_dimensions(CONTROL) == ()


# ----- 7-12: the real production pump under every candidate ----------------------------------------------------------
@pytest.mark.parametrize("config", ALL, ids=lambda c: c.name)
def test_first_timer_uses_the_requested_interval_and_there_is_one_chain(config: PumpConfig) -> None:
    root, invoker = armed(config)
    assert [d for d, _ in root.calls] == [
        config.interval_ms
    ]  # no startup tick at the production 15 ms
    for _ in range(5):
        pump(root)
    assert [d for d, _ in root.calls] == [
        config.interval_ms
    ] * 6  # one re-arm per pump, never two chains
    invoker.dispose()


@pytest.mark.parametrize("config", ALL, ids=lambda c: c.name)
def test_no_loss_no_duplication_fifo_on_the_ui_thread(config: PumpConfig) -> None:
    root, invoker = armed(config)
    ui = threading.get_ident()
    delivered: list[tuple[int, int]] = []
    count = 700

    def worker() -> None:
        for index in range(count):
            invoker.schedule(lambda index=index: delivered.append((index, threading.get_ident())))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    batches = []
    for _ in range(count):
        before = len(delivered)
        pump(root)
        batches.append(len(delivered) - before)
        if len(delivered) == count:
            break
    assert [i for i, _ in delivered] == list(range(count))
    assert {t for _, t in delivered} == {ui}
    assert max(batches) <= config.max_callbacks
    assert len(root.calls) == len(batches) + 1
    invoker.dispose()


@pytest.mark.parametrize("config", ALL, ids=lambda c: c.name)
def test_time_budget_yield_preserves_order_and_scales_with_the_budget(
    config: PumpConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(gui_invoker, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    root, invoker = armed(config)
    delivered: list[int] = []

    def make(index: int):
        def callback() -> None:
            clock[0] += 0.0025  # each callback costs 2.5 ms (no budget lands on an exact boundary)
            delivered.append(index)

        return callback

    for index in range(400):
        invoker.schedule(make(index))
    batches = []
    for _ in range(400):
        before = len(delivered)
        pump(root)
        batches.append(len(delivered) - before)
        if len(delivered) == 400:
            break
    assert delivered == list(range(400))  # leftovers return to the FRONT in order
    expected = min(config.max_callbacks, math.ceil(config.max_pump_ms / 2.5))
    assert batches[0] == expected
    assert max(batches) == expected
    invoker.dispose()


def test_one_slow_callback_consumes_the_budget_and_the_rest_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(gui_invoker, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    root, invoker = armed(PumpConfig("Z", 15, 128, 4.0))
    ran: list[str] = []
    invoker.schedule(lambda: (clock.__setitem__(0, 0.1), ran.append("slow")))
    invoker.schedule(lambda: ran.append("next"))
    pump(root)
    assert ran == ["slow"]
    pump(root)
    assert ran == ["slow", "next"]
    invoker.dispose()


@pytest.mark.parametrize("config", [CONTROL, MATRIX[2], MATRIX[4], MATRIX[6]], ids=lambda c: c.name)
def test_a_backlog_that_never_empties_still_yields_each_pump(config: PumpConfig) -> None:
    root, invoker = armed(config)
    ran = [0]

    def regenerate() -> None:
        ran[0] += 1
        invoker.schedule(regenerate_again())  # a worker-style enqueue while the pump is executing

    def regenerate_again():
        def again() -> None:
            ran[0] += 1
            invoker.schedule(regenerate_again())

        return again

    for _ in range(config.max_callbacks * 2):
        invoker.schedule(
            lambda: ran.__setitem__(0, ran[0] + 1) or invoker.schedule(regenerate_again())
        )
    for step in range(1, 21):
        pump(root)
        assert len(root.calls) == step + 1  # every pump returns and re-arms; the loop is never held
    assert invoker._pending  # the backlog persists, bounded per pump rather than drained inline
    # enqueue during a pump runs in a later pump, never inside the one that was snapshotted
    assert ran[0] <= 20 * config.max_callbacks
    invoker.dispose()


def test_exception_isolation_and_pending_id_release() -> None:
    root, invoker = armed(PumpConfig("Z", 5, 64, 8.0))
    ran: list[str] = []

    def bad() -> None:
        raise RuntimeError("callback failure")

    invoker.schedule(lambda: ran.append("first"))
    invoker.schedule(bad)
    invoker.schedule(lambda: ran.append("after-error"))
    pump(root)
    assert ran == ["first", "after-error"]
    assert not invoker._pending and not invoker._pending_ids
    invoker.schedule(bad)  # the same callable may be accepted again once it has run
    assert len(invoker._pending) == 1
    invoker.dispose()


def test_duplicate_callable_is_coalesced() -> None:
    root, invoker = armed(PumpConfig("Z", 10, 64, 8.0))
    ran = []
    fn = lambda: ran.append(1)  # noqa: E731
    for _ in range(5):
        invoker.schedule(fn)
    pump(root)
    assert ran == [1]
    invoker.dispose()


def test_delayed_callbacks_marshal_through_the_pump_and_are_cancelled_by_disposal() -> None:
    root, invoker = armed(PumpConfig("Z", 10, 64, 8.0))
    ran: list[str] = []
    invoker.invoke_later(20, lambda: ran.append("delayed"))
    pump(root)
    assert ran == []  # not yet queued
    deadline = time.perf_counter() + 2
    while not invoker._pending and time.perf_counter() < deadline:
        time.sleep(0.005)
    pump(root)
    assert ran == ["delayed"]
    invoker.invoke_later(150, lambda: ran.append("never"))
    invoker.dispose()
    time.sleep(0.3)
    assert ran == ["delayed"]
    assert not invoker._timers


@pytest.mark.parametrize("config", [CONTROL, MATRIX[2], MATRIX[4]], ids=lambda c: c.name)
def test_disposal_is_idempotent_and_rejects_late_and_worker_work(config: PumpConfig) -> None:
    root, invoker = armed(config)
    ran: list[str] = []
    invoker.schedule(lambda: ran.append("queued"))
    invoker.dispose()
    invoker.dispose()
    invoker.schedule(lambda: ran.append("late"))
    invoker.run_on_ui_thread(lambda: ran.append("late-inline"))
    worker = threading.Thread(target=lambda: invoker.schedule(lambda: ran.append("worker")))
    worker.start()
    worker.join()
    calls = len(root.calls)
    pump(root)  # the already-armed timer fires after disposal: it must run nothing and not re-arm
    assert ran == []
    assert len(root.calls) == calls
    assert not invoker._pending and not invoker._pending_ids and not invoker._timers


def test_one_pump_per_root_and_no_second_dispatcher_authority() -> None:
    root = FakeRoot()
    dispatcher, log, effective = dispatcher_with_config(root, PumpConfig("Z", 10, 64, 4.0))
    try:
        assert effective == {"interval_ms": 10, "max_callbacks": 64, "max_pump_ms": 4.0}
        assert tk_dispatcher_for(root) is dispatcher
        assert [d for d, _ in root.calls] == [10]  # one armed timer, at the requested interval
        with pytest.raises(ConfigError):
            dispatcher_with_config(root, CONTROL)  # a root never gains a second configured pump
        assert len(root.calls) == 1
        ran: list[int] = []
        dispatcher.schedule(lambda: ran.append(1))
        pump(root)
        assert ran == [1] and len(log.starts) == 1 and len(log.durations_ms) == 1
    finally:
        release_tk_dispatcher(root)
    assert dispatcher.disposed
    dispatcher.schedule(lambda: pytest.fail("ran after release"))
    pump(root)


def test_observation_calls_the_production_pump_and_changes_nothing_else() -> None:
    root = FakeRoot()
    with deferred_first_pump():
        invoker = TkInvoker(root)  # type: ignore[arg-type]
    log = observe(invoker)  # the recorder must be in place before the first timer is armed
    configure(invoker, CONTROL)
    seen: list[int] = []
    invoker.schedule(lambda: seen.append(log.current))
    invoker.schedule(lambda: seen.append(log.current))
    calls_before = len(root.calls)
    root.calls[-1][1]()
    assert seen == [0, 0]  # inside a callback the current pump index is the executing pump
    assert len(log.starts) == 1 and log.durations_ms[0] >= 0
    assert len(root.calls) == calls_before + 1 and root.calls[-1][0] == 15
    invoker.dispose()


# ----- 13-17: evidence -----------------------------------------------------------------------------------------------
def _hb(median: float, p95: float, maximum: float) -> dict[str, Any]:
    return {"n": 300, "min": 2.0, "median": median, "p95": p95, "max": maximum}


def good_result(
    config: PumpConfig, *, burst_median: float = 600.0, refresh: float = 110.0
) -> dict[str, Any]:
    latency = {
        "n": 2000,
        "min": 20.0,
        "median": burst_median,
        "p95": burst_median * 1.9,
        "max": burst_median * 2,
    }
    return {
        "event": "result",
        "clock_ns": 20,
        "status": "PASS",
        "toolkit": "tk",
        "fixture": {"history": "x"},
        "workload": dict(WORKLOAD),
        "config": {
            "name": config.name,
            "requested": config.parameters(),
            "effective": config.parameters(),
            "production_defaults": CONTROL.parameters(),
        },
        "burst": {
            "arrived": True,
            "problem": None,
            "expected": 2000,
            "delivered": 2000,
            "missing": 0,
            "duplicates": 0,
            "out_of_order": 0,
            "wrong_thread": 0,
            "peak_backlog": 2000,
            "total_ms": 1200.0,
            "pumps_used": 63,
            "latency_ms": latency,
            "callback_ms": {"n": 2000, "min": 0.008, "median": 0.009, "p95": 0.05, "max": 1.0},
            "batch_sizes": {"n": 63, "min": 16, "median": 32, "p95": 32, "max": 32},
            "pump_ms": {"n": 63, "min": 0.4, "median": 0.5, "p95": 1.1, "max": 1.4},
        },
        "sustained": {
            "heartbeat": _hb(5.0, 10.0, 17.0),
            "pump_ms": {"n": 100, "min": 0.01, "median": 0.02, "p95": 11.0, "max": 13.0},
            "publishes": 56,
            "renders": 15,
        },
        "refresh": {
            "arrived": True,
            "selection_kept": True,
            "to_visible_ms": refresh,
            "heartbeat": {
                "n": 16,
                "min": 2.6,
                "median": 5.1,
                "p95": None,
                "max": 36.0,
            },  # n < 20: no p95
        },
        "interaction": {"filter_visible_ms": 8.5, "select_visible_ms": 4.9},
        "idle": {
            "window_s": 3.0,
            "pump_count": 156,
            "pump_hz": 52.0,
            "process_cpu_percent": 0.5,
            "host_cpu_percent": 8.0,
            "period_ms": {"n": 155, "min": 15.0, "median": 18.0, "p95": 28.0, "max": 36.0},
        },
        "lifecycle": dict.fromkeys(ev.LIFECYCLE_CHECKS, True),
    }


def good_record(config: PumpConfig, **kwargs: Any) -> dict[str, Any]:
    return {
        "timeout": False,
        "exit_code": 0,
        "contained": True,
        "surviving_descendants": [],
        "first_visible": {"visible": True, "clock_ns": 10},
        "result": good_result(config, **kwargs),
    }


def test_a_complete_record_validates_and_flattens() -> None:
    record = good_record(CONTROL)
    ev.validate_run(record, CONTROL, CONTROL.parameters())
    scalars = ev.run_scalars(record)
    assert set(scalars) == set(ev.SCALAR_KEYS) and scalars["burst_median_ms"] == 600.0


def _mutations() -> list[tuple[str, Any]]:
    def set_(path: tuple[str, ...], value: Any):
        def apply(record: dict[str, Any]) -> None:
            node = record
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value

        return apply

    def drop(path: tuple[str, ...]):
        def apply(record: dict[str, Any]) -> None:
            node = record
            for key in path[:-1]:
                node = node[key]
            del node[path[-1]]

        return apply

    r = ("result",)
    return [
        (
            "effective-differs",
            set_(
                (*r, "config", "effective"),
                {"interval_ms": 16, "max_callbacks": 32, "max_pump_ms": 8.0},
            ),
        ),
        (
            "requested-differs",
            set_(
                (*r, "config", "requested"),
                {"interval_ms": 5, "max_callbacks": 32, "max_pump_ms": 8.0},
            ),
        ),
        ("wrong-condition", set_((*r, "config", "name"), "B")),
        (
            "defaults-differ",
            set_(
                (*r, "config", "production_defaults"),
                {"interval_ms": 10, "max_callbacks": 32, "max_pump_ms": 8.0},
            ),
        ),
        ("workload-altered", set_((*r, "workload", "burst_callbacks"), 1000)),
        ("fixture-missing", set_((*r, "fixture"), {})),
        ("burst-missing", drop((*r, "burst"))),
        ("burst-unarrived", set_((*r, "burst", "arrived"), False)),
        ("burst-dropped", set_((*r, "burst", "delivered"), 1999)),
        ("burst-duplicate", set_((*r, "burst", "duplicates"), 1)),
        ("burst-out-of-order", set_((*r, "burst", "out_of_order"), 3)),
        ("burst-wrong-thread", set_((*r, "burst", "wrong_thread"), 1)),
        ("burst-nonfinite", set_((*r, "burst", "latency_ms", "median"), float("nan"))),
        ("burst-infinite-total", set_((*r, "burst", "total_ms"), float("inf"))),
        ("burst-negative", set_((*r, "burst", "peak_backlog"), -1)),
        ("burst-short-samples", set_((*r, "burst", "latency_ms", "n"), 1999)),
        ("heartbeat-inconsistent", set_((*r, "sustained", "heartbeat"), _hb(20.0, 10.0, 17.0))),
        ("refresh-heartbeat-nonfinite", set_((*r, "refresh", "heartbeat", "max"), float("nan"))),
        ("sustained-nothing-rendered", set_((*r, "sustained", "renders"), 0)),
        ("refresh-selection-lost", set_((*r, "refresh", "selection_kept"), False)),
        ("refresh-missing-latency", drop((*r, "refresh", "to_visible_ms"))),
        ("idle-no-pumps", set_((*r, "idle", "pump_count"), 1)),
        ("lifecycle-late-mutation", set_((*r, "lifecycle", "no_late_mutations"), False)),
        ("lifecycle-missing", drop((*r, "lifecycle", "dispatcher_disposed"))),
        ("not-visible", set_(("first_visible", "visible"), False)),
        ("timeout", set_(("timeout",), True)),
        ("exit-code", set_(("exit_code",), 1)),
        ("survivors", set_(("surviving_descendants",), [123])),
        ("not-contained", set_(("contained",), False)),
        ("status-fail", set_((*r, "status"), "FAIL")),
    ]


@pytest.mark.parametrize(("label", "mutate"), _mutations(), ids=[m[0] for m in _mutations()])
def test_invalid_or_incomplete_records_are_rejected(label: str, mutate: Any) -> None:
    record = copy.deepcopy(good_record(CONTROL))
    mutate(record)
    with pytest.raises(EvidenceError):
        ev.validate_run(record, CONTROL, CONTROL.parameters())


def test_a_record_for_another_condition_is_not_accepted_as_this_one() -> None:
    with pytest.raises(EvidenceError):
        ev.validate_run(good_record(MATRIX[1]), CONTROL, CONTROL.parameters())


def _runs(
    config: PumpConfig, medians: list[float], refresh: list[float], **overrides: float
) -> list[dict[str, float]]:
    out = []
    for burst, ref in zip(medians, refresh, strict=True):
        scalars = ev.run_scalars(good_record(config, burst_median=burst, refresh=ref))
        scalars.update(overrides)
        out.append(scalars)
    return out


BASE = _runs(CONTROL, [600, 610, 590, 605, 595], [120, 118, 122, 119, 121])


def test_screening_requires_both_burst_and_operator_benefit_without_regression() -> None:
    good = _runs(MATRIX[2], [200, 210, 190, 205, 195], [90, 88, 92, 89, 91])
    result = ev.screen(BASE, good)
    assert result["promising"] and all(result["gates"].values())
    burst_only = ev.screen(
        BASE, _runs(MATRIX[2], [200, 210, 190, 205, 195], [120, 118, 122, 119, 121])
    )
    assert burst_only["gates"]["burst"] and not burst_only["gates"]["representative_refresh"]
    assert not burst_only["promising"] and burst_only["burst_only"]
    starving = ev.screen(
        BASE,
        _runs(MATRIX[4], [200, 210, 190, 205, 195], [90, 88, 92, 89, 91], sustained_hb_max_ms=40.0),
    )
    assert (
        starving["gates"]["burst"]
        and not starving["gates"]["responsiveness"]
        and not starving["promising"]
    )
    p95_up = ev.screen(
        BASE,
        _runs(MATRIX[4], [200, 210, 190, 205, 195], [90, 88, 92, 89, 91], sustained_hb_p95_ms=13.0),
    )
    assert not p95_up["gates"]["responsiveness"]
    busy = ev.screen(
        BASE,
        _runs(
            MATRIX[2],
            [200, 210, 190, 205, 195],
            [90, 88, 92, 89, 91],
            idle_cpu_percent=1.6,
            idle_pump_hz=150.0,
        ),
    )
    assert not busy["gates"]["resource"] and busy["idle_pump_rate_note"]
    refresh_stall = ev.screen(
        BASE,
        _runs(MATRIX[4], [200, 210, 190, 205, 195], [90, 88, 92, 89, 91], refresh_hb_max_ms=60.0),
    )
    assert not refresh_stall["gates"][
        "responsiveness"
    ]  # a refresh-window stall is a regression too
    weak = ev.screen(BASE, _runs(MATRIX[3], [400, 410, 390, 405, 395], [90, 88, 92, 89, 91]))
    assert not weak["gates"]["burst"]  # a 33% cut is below the screening floor
    noisy = ev.screen(BASE, _runs(MATRIX[3], [200, 210, 190, 205, 700], [90, 88, 92, 89, 91]))
    assert not noisy["gates"]["burst"]  # one run overlaps the baseline range: not consistent


def test_screening_refuses_short_samples() -> None:
    with pytest.raises(EvidenceError):
        ev.screen(BASE[:4], BASE)
    with pytest.raises(EvidenceError):
        ev.screen(BASE, [])


def test_verdict_never_forces_a_winner_or_accepts_nothing() -> None:
    losing = {"promising": False, "burst_only": False}
    winning = {"promising": True, "burst_only": False}
    with pytest.raises(EvidenceError):
        ev.verdict({})
    assert (
        ev.verdict({"B": losing, "C": {"promising": False, "burst_only": True}})["outcome"]
        == "NO-GO"
    )
    assert ev.verdict({"B": winning, "C": losing})["outcome"] == "CONDITIONAL GO"
    assert ev.verdict({"B": winning, "H": winning}, ["H"])["outcome"] == "GO"
    assert ev.verdict({"B": losing, "H": winning}, ["H"])["outcome"] == "CONDITIONAL GO"
    assert ev.verdict({"B": winning, "H": losing}, ["H"])["outcome"] == "CONDITIONAL GO"


def _report(samples: int = 5) -> dict[str, Any]:
    conditions = {
        c.name: {
            "warmup": {"run_id": f"primary-warmup-{c.name}"},
            "runs": [{"run_id": f"primary-r{i}-{c.name}"} for i in range(1, samples + 1)],
        }
        for c in MATRIX
    }
    return {
        "identity": {
            "source_sha": "a" * 40,
            "fingerprint": {"f": "1"},
            "windows": "Windows",
            "parent": {"pid": 1},
            "seed": 743,
            "samples": samples,
            "worktree_clean": True,
            "production_defaults": CONTROL.parameters(),
        },
        "phases": {"primary": {"conditions": conditions}},
        "validity": {"failures": []},
    }


def test_experiment_validation_fails_closed() -> None:
    assert ev.validate_experiment(_report()) == []
    assert ev.validate_experiment({})  # an empty experiment is never a pass
    empty = _report()
    empty["phases"] = {}
    assert any("no phase" in p for p in ev.validate_experiment(empty))
    zero = _report()
    zero["phases"]["primary"]["conditions"] = {}
    assert any("zero candidates" in p for p in ev.validate_experiment(zero))
    short = _report()
    short["phases"]["primary"]["conditions"]["B"]["runs"].pop()
    assert any("primary/B" in p for p in ev.validate_experiment(short))
    assert any("fewer than" in p for p in ev.validate_experiment(_report(samples=4)))
    nowarm = _report()
    nowarm["phases"]["primary"]["conditions"]["C"]["warmup"] = None
    assert any("warm-up" in p for p in ev.validate_experiment(nowarm))
    partial = _report()
    del partial["phases"]["primary"]["conditions"]["G"]
    assert any("declared matrix" in p for p in ev.validate_experiment(partial))
    dirty = _report()
    dirty["identity"]["worktree_clean"] = False
    assert any("clean" in p for p in ev.validate_experiment(dirty))
    unbound = _report()
    unbound["identity"]["source_sha"] = ""
    assert any("source_sha" in p for p in ev.validate_experiment(unbound))
    drifted = _report()
    drifted["identity"]["production_defaults"] = {
        "interval_ms": 10,
        "max_callbacks": 32,
        "max_pump_ms": 8.0,
    }
    assert any("declared control" in p for p in ev.validate_experiment(drifted))
    invalid = _report()
    invalid["validity"]["failures"] = ["primary-r2-D: bad"]
    assert any("invalid run" in p for p in ev.validate_experiment(invalid))
    dup = _report()
    dup["phases"]["primary"]["conditions"]["B"]["runs"][0]["run_id"] = "primary-r1-C"
    assert any("duplicate" in p for p in ev.validate_experiment(dup))


def test_confirmation_phase_has_a_hard_cap() -> None:
    report = _report()
    report["phases"] = {
        "confirmation": {
            "conditions": {
                n: {
                    "warmup": {"run_id": f"w{n}"},
                    "runs": [{"run_id": f"{n}{i}"} for i in range(5)],
                }
                for n in ("H", "I", "J")
            }
        }
    }
    assert any("more than 2" in p for p in ev.validate_experiment(report))


# ----- plan, order, identity ------------------------------------------------------------------------------------------
def test_plan_has_one_warmup_per_candidate_and_counterbalanced_measured_rounds() -> None:
    plan = plan_runs(list(MATRIX), phase="primary", samples=5, seed=743)
    warmups = [s for s in plan if s.kind == "warmup"]
    measured = [s for s in plan if s.kind == "measured"]
    assert [s.config.name for s in warmups] == [c.name for c in MATRIX]
    assert len(measured) == 35 and len({s.run_id for s in plan}) == len(plan)
    for config in MATRIX:
        assert sum(1 for s in measured if s.config.name == config.name) == 5
        positions = [s.position for s in measured if s.config.name == config.name]
        assert len(set(positions)) == 5  # a different position in each round
    assert plan_runs(list(MATRIX), phase="primary", samples=5, seed=743) == plan  # reproducible
    assert plan_runs(list(MATRIX), phase="primary", samples=5, seed=1) != plan
    assert warmups[0].run_id.startswith("primary-warmup")


def test_plan_rejects_empty_short_and_duplicate_inputs() -> None:
    with pytest.raises(ConfigError):
        plan_runs([], phase="primary", samples=5, seed=1)
    with pytest.raises(ConfigError):
        plan_runs(list(MATRIX), phase="primary", samples=4, seed=1)
    with pytest.raises(ConfigError):
        plan_runs([CONTROL, CONTROL], phase="primary", samples=5, seed=1)
    with pytest.raises(ConfigError):
        balanced_order([], 3, 1)


def test_confirmation_rules_and_distinct_identities() -> None:
    h = PumpConfig("H", 10, 64, 8.0)
    i = PumpConfig("I", 5, 128, 8.0)
    assert validate_confirmations([h, i]) == [h, i]
    for bad in (
        [],
        [h, i, PumpConfig("J", 10, 128, 4.0)],
        [PumpConfig("K", 7, 64, 8.0)],  # an untested interval
        [PumpConfig("K", 10, 64, 20.0)],  # an untested time budget
        [PumpConfig("K", 10, 32, 8.0)],  # one dimension is a primary candidate, not a confirmation
        [PumpConfig("B", 10, 64, 8.0)],  # name collision with the matrix
        [h, PumpConfig("L", 10, 64, 8.0)],  # duplicate settings
    ):
        with pytest.raises(ConfigError):
            validate_confirmations(bad)
    primary = plan_runs(list(MATRIX), phase="primary", samples=5, seed=743)
    confirm = plan_runs([h, i], phase="confirmation", samples=5, seed=743)
    assert not {s.run_id for s in primary} & {s.run_id for s in confirm}
    assert len([s for s in confirm if s.kind == "measured"]) == 10


def test_fingerprint_binds_the_dispatcher_sources_and_the_experiment_code() -> None:
    fp = run743.fingerprint()
    for name in run743.EXTRA_SOURCE_FILES:
        assert len(fp[name]) == 64
    for module in ("config.py", "inject.py", "evidence.py", "child.py", "run.py"):
        assert f"tools/qualification/gui_seam_743/{module}" in fp
    assert "tools/qualification/gui_port_742/tk_view.py" in fp  # the reused workspace is bound too


def test_summarize_is_the_reused_742_validator() -> None:
    assert summarize([1.0, 2.0, 3.0], label="x")["median"] == 2.0
    with pytest.raises(EvidenceError):
        summarize([], label="x")
