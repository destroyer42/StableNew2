"""PipelineController learning hook tests."""

from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.learning.learning_record import LearningRecord


class MemoryWriter:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


def _sample_record() -> LearningRecord:
    return LearningRecord(
        run_id="xyz",
        timestamp="2025-01-01T00:00:00",
        base_config={"txt2img": {"model": "base"}},
        variant_configs=[],
        randomizer_mode="off",
        randomizer_plan_size=1,
        primary_model="base",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=20,
        primary_cfg_scale=7.5,
    )


def test_pipeline_controller_handles_learning_records():
    writer = MemoryWriter()
    callback_records = []

    controller = PipelineController(
        learning_record_writer=writer,
        on_learning_record=callback_records.append,
    )

    handler = controller.get_learning_record_handler()
    controller.set_learning_enabled(True)
    record = _sample_record()
    handler(record)

    assert writer.records[0] == record
    assert callback_records[0] == record
    assert controller.get_last_learning_record() == record
