from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.app_factory import build_v2_app
from src.controller.job_service import JobService, SubmissionPolicy
from src.queue.job_model import JobStatus
from src.utils.config import ConfigManager
from src.utils.thread_registry import get_thread_registry
from tests.helpers.njr_factory import make_pipeline_njr
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


def _pump_until(root, predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    root.update()
    assert predicate(), "timed out waiting for the hosted projection"


def _ids_and_statuses(jobs) -> list[tuple[str, str]]:
    return [
        (
            str(job.job_id),
            str(job.status.value if hasattr(job.status, "value") else job.status).upper(),
        )
        for job in jobs
    ]


def _active_projection_snapshot(controller, tab) -> dict[str, object]:
    queue = controller.job_service.queue
    active = {JobStatus.RUNNING, JobStatus.QUEUED}
    return {
        "repository": _ids_and_statuses(queue.repository.list_job_models(active)),
        "job_queue": _ids_and_statuses(queue.list_active_jobs_ordered()),
        "app_state": _ids_and_statuses(controller.app_state.queue_jobs),
        "queue_panel": _ids_and_statuses(tab.queue_panel._jobs),
        "rows": tab.queue_panel.job_listbox.size(),
        "coordinator_revision": controller._runtime_projection_coordinator.get_metrics_snapshot()[
            "surface_revisions"
        ].get("queue", 0),
        "sink_revision": controller._projection_sink.get_metrics_snapshot()[
            "surface_revisions"
        ].get("queue", 0),
    }


def _pump_until_exact_projection(root, controller, tab, expected) -> None:
    def _matches() -> bool:
        snapshot = _active_projection_snapshot(controller, tab)
        return all(snapshot[layer] == expected for layer in (
            "repository",
            "job_queue",
            "app_state",
            "queue_panel",
        )) and snapshot["rows"] == len(expected)

    _pump_until(root, _matches)


@pytest.mark.gui
def test_pipeline_tab_pack_add_preview_and_queue_projection(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the production application-factory projection path."""

    # Other GUI tests may exercise the process-wide registry shutdown path;
    # this isolated harness must begin with a live registry.
    registry = get_thread_registry()
    registry._shutdown_requested = False

    monkeypatch.chdir(tmp_path)
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    (packs_dir / "native_one_row.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "Native one row",
                    "slots": [
                        {"index": 0, "text": "a lighthouse at dawn", "negative": "blur"}
                    ],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )

    config_manager = ConfigManager(presets_dir=tmp_path / "presets")
    _, app_state, controller, window = build_v2_app(
        root=tk_root,
        threaded=False,
        config_manager=config_manager,
        pipeline_runner=FakePipelineRunner(),
    )
    try:
        tab = window.pipeline_tab
        sidebar = tab.sidebar
        assert controller.app_state is app_state
        assert controller.pipeline_controller._app_state is app_state
        assert controller._projection_sink._app_state is app_state
        assert tab.app_state is app_state
        assert tab.queue_panel.app_state is app_state
        assert tab.preview_panel.app_state is app_state
        assert sidebar.pack_listbox.size() == 1
        sidebar.pack_listbox.selection_set(0)
        controller.on_set_auto_run_v2(False)
        sidebar._on_add_to_job()

        _pump_until(
            tk_root,
            lambda: bool(controller.app_state.job_draft.packs)
            and bool(controller.app_state.preview_jobs),
        )
        assert tab.preview_panel.add_to_queue_button.instate(["!disabled"])

        # Production button callback; no direct state mutation or manual panel
        # refresh is used to deliver the queue projection.
        tab.preview_panel.add_to_queue_button.invoke()
        _pump_until(
            tk_root,
            lambda: len(controller.app_state.queue_jobs) == 1
            and tab.queue_panel.job_listbox.size() == 1,
        )
        controller.on_queue_clear_v2()
        _pump_until(
            tk_root,
            lambda: not controller.app_state.queue_jobs
            and tab.queue_panel.job_listbox.size() == 0,
        )
        queue = controller.job_service.queue
        controller.on_set_auto_run_v2(False)
        controller.job_service.auto_run_enabled = False

        # One projection owner and one AppState object in production composition.
        assert controller.pipeline_controller._app_state_queue_updates_managed_externally is True
        assert controller.app_state is app_state
        assert controller.pipeline_controller._app_state is app_state
        assert controller._projection_sink._app_state is app_state
        assert tab.app_state is app_state
        assert tab.queue_panel.app_state is app_state
        assert tab.preview_panel.app_state is app_state

        emitted: list[list[tuple[str, str]]] = []
        controller.job_service.register_callback(
            JobService.EVENT_QUEUE_UPDATED,
            lambda _summaries: emitted.append(_ids_and_statuses(queue.list_active_jobs_ordered())),
        )

        for count in (1, 2, 3):
            records = [
                make_pipeline_njr(
                    job_id=f"matrix-{count}-{index}",
                    prompt_pack_id="native-matrix-pack",
                    prompt_pack_name="Native matrix pack",
                    prompt_pack_row_index=index,
                )
                for index in range(count)
            ]
            expected = [(record.job_id, "QUEUED") for record in records]
            emitted.clear()
            submitted = controller.job_service.submit_njrs(
                records,
                SubmissionPolicy(start_when_idle=False),
            )
            assert submitted == [record.job_id for record in records]
            assert emitted[-1] == expected  # event observes the complete atomic mutation
            _pump_until_exact_projection(tk_root, controller, tab, expected)
            assert tab.queue_panel.send_job_button.instate(["!disabled"])

            first = queue.claim_next_job()
            assert first is not None and first.job_id == records[0].job_id
            expected[0] = (first.job_id, "RUNNING")
            _pump_until_exact_projection(tk_root, controller, tab, expected)

            queue.mark_completed(first.job_id, {"success": True, "variants": []})
            expected.pop(0)
            _pump_until_exact_projection(tk_root, controller, tab, expected)

            for record in records[1:]:
                claimed = queue.claim_next_job()
                assert claimed is not None and claimed.job_id == record.job_id
                expected[0] = (claimed.job_id, "RUNNING")
                _pump_until_exact_projection(tk_root, controller, tab, expected)
                queue.mark_completed(claimed.job_id, {"success": True, "variants": []})
                expected.pop(0)
                _pump_until_exact_projection(tk_root, controller, tab, expected)

            if count == 1:
                assert controller.on_replay_history_job_v2(records[0].job_id) is True
                _pump_until(tk_root, lambda: len(queue.list_active_jobs_ordered()) == 1)
                replay = queue.list_active_jobs_ordered()[0]
                assert replay._normalized_record.source.parent_job_id == records[0].job_id
                replay_expected = [(replay.job_id, "QUEUED")]
                _pump_until_exact_projection(tk_root, controller, tab, replay_expected)
                queue.mark_cancelled(replay.job_id, "test cleanup")
                _pump_until_exact_projection(tk_root, controller, tab, [])
    finally:
        window.cleanup()
        registry._shutdown_requested = False
