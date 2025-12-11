from src.controller.webui_connection_controller import WebUIConnectionState
from unittest import mock

from src.controller.pipeline_controller import PipelineController
from src.controller.pipeline_config_assembler import PipelineConfigAssembler, GuiOverrides
from src.queue.job_model import Job


def test_controller_uses_assembler_for_runs(monkeypatch):
    assembler = PipelineConfigAssembler()
    monkeypatch.setattr("src.controller.pipeline_controller.PipelineConfigAssembler", lambda *args, **kwargs: assembler)
    controller = PipelineController(config_assembler=assembler)
    controller._webui_connection.ensure_connected = lambda autostart=True: WebUIConnectionState.READY

    class JobShim(Job):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.controller.job_execution_controller.Job", JobShim)

    assembler.build_from_gui_input = mock.Mock(
        return_value=assembler.build_from_gui_input(overrides=GuiOverrides(prompt="p"))
    )
    controller._queue_execution_enabled = False

    def dummy_pipeline():
        return {}

    controller.start_pipeline(dummy_pipeline)
    assembler.build_from_gui_input.assert_called()
