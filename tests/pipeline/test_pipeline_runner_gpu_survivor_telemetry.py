from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.pipeline.pipeline_runner import PipelineRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


class _Recorder:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.events: list[tuple[str, str | None]] = []
        self.closed: str | None = None

    def start(self) -> None:
        self.events.append(("started", None))

    def enter_stage(self, stage: str, *, backend_id: str | None = None) -> None:
        self.events.append((f"enter:{stage}", backend_id))

    def leave_stage(self, stage: str) -> None:
        self.events.append((f"leave:{stage}", None))

    def close(self, *, outcome: str) -> None:
        self.closed = outcome


def test_pipeline_runner_uses_survivor_telemetry_as_an_observer(monkeypatch, tmp_path) -> None:
    class DummyPipeline:
        def __init__(self, api_client, structured_logger, status_callback=None):
            self.api_client = api_client
            self.logger = structured_logger
            self.status_callback = status_callback

        def run_txt2img_stage(self, _prompt, _negative, _payload, run_dir, **kwargs):
            return {"path": str(run_dir / kwargs["image_name"]), "images": []}

    recorders: list[_Recorder] = []

    def recorder_factory(**kwargs: Any) -> _Recorder:
        recorder = _Recorder(**kwargs)
        recorders.append(recorder)
        return recorder

    monkeypatch.setattr("src.pipeline.executor.Pipeline", DummyPipeline)
    runner = PipelineRunner(
        api_client=SimpleNamespace(),
        structured_logger=StructuredLogger(output_dir=str(tmp_path)),
        runs_base_dir=str(tmp_path / "runs"),
        survivor_telemetry_factory=recorder_factory,
    )
    monkeypatch.setattr(
        runner,
        "_execute_image_backend",
        lambda **kwargs: {
            "path": str(kwargs["run_dir"] / kwargs["image_name"]),
            "all_paths": [str(kwargs["run_dir"] / kwargs["image_name"])],
        },
    )

    result = runner.run_njr(
        make_pipeline_njr(stage_chain=[make_stage_config()]),
        cancel_token=SimpleNamespace(is_cancelled=lambda: False),
    )

    assert result.success
    assert len(recorders) == 1
    recorder = recorders[0]
    assert recorder.kwargs["job_id"]
    assert recorder.kwargs["workflow"] == ["txt2img"]
    assert recorder.events == [
        ("started", None),
        ("enter:txt2img", "a1111_webui"),
        ("leave:txt2img", None),
    ]
    assert recorder.closed == "runner_finished"
