"""VID-FRAME / KEEP-SPACE: the first frame cleanup waits for the operator's confirmation; later ones run on schedule,
and a Recycle Bin that cannot take the frames is explained once."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.app import frame_retention_service as service
from src.utils.config import ConfigManager
from src.video.frame_retention import FrameSweep


class Settings(dict):
    def read(self, key: str, default: Any = None) -> Any:
        return self.get(key, default)

    def write(self, updates: dict[str, Any]) -> bool:
        self.update(updates)
        return True


class Root:
    def __init__(self) -> None:
        self.scheduled: list[tuple[int, Any]] = []

    def after(self, ms: int, call: Any) -> None:
        self.scheduled.append((ms, call))

    def run_next(self) -> int:
        ms, call = self.scheduled.pop(0)
        call()
        return ms


class InlineThreads:
    def spawn(self, target, **_kwargs) -> None:
        target()


def _app(tmp_path, jobs: list[Any] | None = None) -> Any:
    queued = list(jobs or [])
    queue = SimpleNamespace(list_active_jobs_ordered=lambda: list(queued))
    return SimpleNamespace(job_service=SimpleNamespace(job_queue=queue), output_dir=str(tmp_path))


@pytest.fixture
def sweeps(monkeypatch):
    calls: list[bool] = []

    def sweep(_root, *, dry_run=False, **_kwargs):
        calls.append(dry_run)
        return FrameSweep(frames=3, bytes=3_000_000_000, runs=1)

    monkeypatch.setattr(service, "sweep_retained_frames", sweep)
    monkeypatch.setattr(service, "RecycleBin", object)  # the real shell is never built
    monkeypatch.setattr(service, "get_thread_registry", lambda: InlineThreads())
    return calls


def _start(tmp_path, settings: Settings, asked: list[Any], jobs=None) -> Root:
    root = Root()
    service.schedule_frame_retention(
        root,
        _app(tmp_path, jobs),
        ask=lambda preview, choose: asked.append((preview, choose)),
        setting=settings.read,
        save=settings.write,
    )
    return root


def _drive(root: Root, steps: int) -> None:
    for _ in range(steps):
        if root.scheduled:
            root.run_next()


def test_the_rule_ships_on_and_unconfirmed() -> None:
    defaults = ConfigManager().get_default_engine_settings()

    assert defaults[service.SETTING_KEY] is True
    assert defaults[service.CONFIRMED_KEY] is False


def test_nothing_is_deleted_before_the_operator_confirms(tmp_path, sweeps) -> None:
    asked: list[Any] = []
    root = _start(tmp_path, Settings(), asked)

    _drive(root, 6)

    assert sweeps == [True]  # only the dry run, and only one question
    assert len(asked) == 1 and asked[0][0].frames == 3


def test_move_now_confirms_once_sweeps_and_never_asks_again(tmp_path, sweeps) -> None:
    asked: list[Any] = []
    settings = Settings()
    root = _start(tmp_path, settings, asked)
    _drive(root, 3)

    asked[0][1](service.CHOICE_MOVE_NOW)
    _drive(root, 3)

    assert settings[service.CONFIRMED_KEY] is True
    assert sweeps[:2] == [True, False]
    later: list[Any] = []
    _drive(_start(tmp_path, settings, later), 3)
    assert later == [] and sweeps[-1] is False


@pytest.mark.parametrize("choice", [service.CHOICE_NOT_NOW, service.CHOICE_TURN_OFF])
def test_not_now_and_turn_off_move_nothing(tmp_path, sweeps, choice) -> None:
    asked: list[Any] = []
    settings = Settings()
    root = _start(tmp_path, settings, asked)
    _drive(root, 3)

    asked[0][1](choice)
    _drive(root, 6)

    assert sweeps == [True] and len(asked) == 1
    assert settings.get(service.CONFIRMED_KEY) is not True
    assert settings.get(service.SETTING_KEY, True) is (choice == service.CHOICE_NOT_NOW)


def test_nothing_runs_while_jobs_wait_or_the_rule_is_off(tmp_path, sweeps) -> None:
    asked: list[Any] = []

    _drive(_start(tmp_path, Settings(), asked, jobs=["queued"]), 3)
    _drive(_start(tmp_path, Settings({service.SETTING_KEY: False}), asked), 3)

    assert sweeps == [] and asked == []


def test_an_empty_dry_run_asks_nothing(tmp_path, sweeps, monkeypatch) -> None:
    monkeypatch.setattr(service, "sweep_retained_frames", lambda *_a, **_k: FrameSweep())
    asked: list[Any] = []
    settings = Settings()

    _drive(_start(tmp_path, settings, asked), 3)

    assert asked == [] and service.CONFIRMED_KEY not in settings


def test_stopping_cancels_the_scheduled_run(tmp_path, sweeps) -> None:
    root = Root()
    stop = service.schedule_frame_retention(
        root, _app(tmp_path), ask=lambda *_a: None, setting=Settings().read, save=Settings().write
    )

    stop()
    root.run_next()

    assert root.scheduled == [] and sweeps == []


@pytest.mark.parametrize("confirmed", [False, True])
def test_a_bin_that_cannot_take_the_frames_is_explained_once(
    tmp_path, sweeps, monkeypatch, confirmed
) -> None:
    full = FrameSweep(bin_refusal="The Recycle Bin is full.")
    monkeypatch.setattr(service, "sweep_retained_frames", lambda *_a, **_k: full)
    asked: list[Any] = []
    settings = Settings({service.CONFIRMED_KEY: confirmed})

    _drive(_start(tmp_path, settings, asked), 8)  # several six-hour passes

    assert [preview for preview, _choose in asked] == [full]
    assert settings[service.CONFIRMED_KEY] is confirmed


def test_a_bin_that_filled_after_move_now_is_still_explained(tmp_path, sweeps, monkeypatch) -> None:
    def sweep(_root, *, dry_run=False, **_kwargs):
        return FrameSweep(frames=3, bytes=3, runs=1) if dry_run else FrameSweep(bin_refusal="Full.")

    monkeypatch.setattr(service, "sweep_retained_frames", sweep)
    asked: list[Any] = []
    root = _start(tmp_path, Settings(), asked)
    _drive(root, 3)

    asked[0][1](service.CHOICE_MOVE_NOW)
    _drive(root, 6)

    assert [preview.bin_refusal for preview, _choose in asked] == ["", "Full."]
