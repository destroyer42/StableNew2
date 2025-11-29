from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.learning.learning_record import LearningRecord


class MemoryWriter:
    def __init__(self):
        self.records = []

    def append_record(self, record):
        self.records.append(record)


def _record():
    return LearningRecord(
        run_id="r1",
        timestamp="t1",
        base_config={},
        variant_configs=[],
        randomizer_mode="",
        randomizer_plan_size=0,
        primary_model="m",
        primary_sampler="Euler",
        primary_scheduler="Normal",
        primary_steps=10,
        primary_cfg_scale=7.0,
        metadata={},
    )


def test_controller_writes_record_when_enabled():
    writer = MemoryWriter()
    controller = PipelineController(learning_record_writer=writer)
    controller.set_learning_enabled(True)
    controller.handle_learning_record(_record())
    assert writer.records, "Expected record to be written when learning is enabled"


def test_controller_skips_record_when_disabled():
    writer = MemoryWriter()
    controller = PipelineController(learning_record_writer=writer)
    controller.set_learning_enabled(False)
    controller.handle_learning_record(_record())
    assert not writer.records
