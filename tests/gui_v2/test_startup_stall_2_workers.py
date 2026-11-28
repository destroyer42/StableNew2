"""STARTUP-STALL-2: the profile strip and the AI Assist poll read their files off the Tk thread."""

from __future__ import annotations

import threading
import time

import pytest

from src.ai_assist.contracts import OutcomeCode
from src.assets import AssetRegistry
from src.gui.generation_profile_strip import GenerationProfileStrip
from src.gui_v2.generation_profile_projection import build_strip_view
from tests.gui_v2.test_ai_suggestions_112 import journey  # noqa: F401 - fixture


def pump_until(root, ready, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not ready():
        assert time.monotonic() < end, "condition not reached while pumping Tk"
        root.update()
        time.sleep(0.01)


class SlowProfiles:
    """A strip controller whose file-reading half records its thread and can be held."""

    def __init__(self) -> None:
        self.read_threads: list[str] = []
        self.compute_threads: list[str] = []
        self.statuses: list[str] = []
        self.gate = threading.Event()
        self.gate.set()

    def add_listener(self, _listener) -> None:
        return None

    def strip_view_job(self):
        self.read_threads.append(threading.current_thread().name)
        number = len(self.read_threads)

        def compute():
            self.compute_threads.append(threading.current_thread().name)
            assert self.gate.wait(5)
            view = build_strip_view(None)
            return type(view)(**{**view.__dict__, "status": f"read {number}"})

        return compute


@pytest.mark.gui
def test_strip_reads_working_values_on_tk_and_files_on_a_worker(tk_root) -> None:
    profiles = SlowProfiles()
    strip = GenerationProfileStrip(tk_root, controller_getter=lambda: profiles)

    pump_until(tk_root, lambda: strip.status_label.cget("text") == "read 1")

    assert profiles.read_threads == [threading.main_thread().name]
    assert profiles.compute_threads and threading.main_thread().name not in profiles.compute_threads


@pytest.mark.gui
def test_strip_publishes_only_the_newest_request(tk_root) -> None:
    profiles = SlowProfiles()
    profiles.gate.clear()
    strip = GenerationProfileStrip(tk_root, controller_getter=lambda: profiles)
    shown: list[str] = []
    original = strip._render
    strip._render = lambda view: (shown.append(view.status), original(view))  # type: ignore[method-assign]

    strip.refresh()
    strip.refresh()  # both arrive while the first read is still running
    profiles.gate.set()
    pump_until(tk_root, lambda: bool(shown))
    for _ in range(20):
        tk_root.update()
        time.sleep(0.01)

    assert shown == ["read 2"]  # one follow-up read; the stale first result is never shown


@pytest.mark.gui
def test_a_destroyed_strip_drops_a_late_result(tk_root) -> None:
    profiles = SlowProfiles()
    profiles.gate.clear()
    strip = GenerationProfileStrip(tk_root, controller_getter=lambda: profiles)
    errors: list[BaseException] = []
    tk_root.report_callback_exception = lambda _t, value, _tb: errors.append(value)

    strip.destroy()
    profiles.gate.set()
    for _ in range(20):
        tk_root.update()
        time.sleep(0.01)

    assert not errors


def test_ai_assist_poll_reads_status_on_a_worker_and_publishes_on_tk(journey) -> None:  # noqa: F811
    j = journey
    threads: list[str] = []

    def availability():
        threads.append(threading.current_thread().name)
        return OutcomeCode.NOT_INSTALLED, "from the worker"

    j.owner.availability = availability
    j.owner.trust_label = lambda: ""

    j.flow._refresh_in_background()
    pump_until(j.root, lambda: "from the worker" in j.flow.explanation.cget("text"))

    assert threads and threading.main_thread().name not in threads
    assert j.flow.button.instate(["disabled"])


def test_a_direct_ai_refresh_supersedes_a_slow_poll_result(journey) -> None:  # noqa: F811
    j = journey
    gate = threading.Event()
    done = threading.Event()

    def availability():
        if threading.current_thread() is not threading.main_thread():
            assert gate.wait(5)
            done.set()
            return OutcomeCode.NOT_INSTALLED, "stale poll"
        return OutcomeCode.NOT_INSTALLED, "fresh action"

    j.owner.availability = availability
    j.owner.trust_label = lambda: ""

    j.flow._refresh_in_background()
    j.flow.refresh()
    gate.set()
    assert done.wait(5)
    for _ in range(20):
        j.root.update()
        time.sleep(0.01)

    assert "fresh action" in j.flow.explanation.cget("text")


def test_registry_cache_is_complete_for_a_second_thread_while_it_loads(tmp_path) -> None:
    """The strip worker and Tk can both reach one shared registry; neither may see it half-loaded."""
    registry = AssetRegistry(tmp_path, cache_path=tmp_path / "cache.json")
    reading = threading.Event()
    release = threading.Event()
    original = registry._read_cache_file

    def slow_read():
        reading.set()
        release.wait(5)
        state, version, _entries = original()
        return state, version, {"known": {}}

    registry._read_cache_file = slow_read  # type: ignore[method-assign]
    seen: list[dict] = []
    first = threading.Thread(target=registry._load)
    first.start()
    assert reading.wait(5)

    def second_load() -> None:
        registry._load()
        seen.append(dict(registry._entries))

    second = threading.Thread(target=second_load)
    second.start()
    time.sleep(0.1)
    release.set()
    first.join(5)
    second.join(5)

    assert seen == [{"known": {}}]
