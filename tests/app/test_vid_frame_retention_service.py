"""VID-FRAME: the sweep runs only with the setting on and an empty queue, off the Tk thread."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.app import frame_retention_service as service
from src.utils.config import ConfigManager


def _app(tmp_path, jobs: list[Any]) -> Any:
    queue = SimpleNamespace(list_active_jobs_ordered=lambda: list(jobs))
    return SimpleNamespace(job_service=SimpleNamespace(job_queue=queue), output_dir=str(tmp_path))


def _settings(enabled: bool = True):
    return lambda key, default=None: enabled if key == service.SETTING_KEY else default


def test_it_sweeps_the_output_folder_only_when_idle_and_enabled(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        service, "sweep_retained_frames", lambda root, **_kwargs: calls.append(str(root))
    )

    service.run_frame_retention(_app(tmp_path, []), setting=_settings())
    assert calls == [str(tmp_path)]

    service.run_frame_retention(_app(tmp_path, ["queued job"]), setting=_settings())
    service.run_frame_retention(_app(tmp_path, []), setting=_settings(False))
    service.run_frame_retention(SimpleNamespace(), setting=_settings())
    assert calls == [str(tmp_path)]


def test_the_setting_defaults_to_on() -> None:
    assert ConfigManager().get_default_engine_settings()[service.SETTING_KEY] is True


def test_stopping_cancels_the_scheduled_run(tmp_path) -> None:
    scheduled: list[tuple[int, Any]] = []
    root = SimpleNamespace(after=lambda ms, call: scheduled.append((ms, call)))

    stop = service.schedule_frame_retention(root, _app(tmp_path, []))
    stop()
    scheduled[0][1]()

    assert [ms for ms, _call in scheduled] == [service.FIRST_RUN_MS]
