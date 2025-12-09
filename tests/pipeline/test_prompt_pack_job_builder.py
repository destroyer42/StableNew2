from __future__ import annotations

from dataclasses import dataclass

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.prompt_pack_job_builder import PromptPackNormalizedJobBuilder
from src.utils.config import ConfigManager


@dataclass
class SequentialIdGenerator:
    """Simple deterministic ID generator for JobBuilderV2 tests."""

    counter: int = 0

    def __call__(self) -> str:
        self.counter += 1
        return f"job-{self.counter}"


def test_prompt_pack_job_builder_creates_normalized_jobs() -> None:
    builder = PromptPackNormalizedJobBuilder(
        config_manager=ConfigManager(),
        job_builder=JobBuilderV2(time_fn=lambda: 1.0, id_fn=SequentialIdGenerator()),
    )

    entry = PackJobEntry(
        pack_id="SDXL_angelic_warriors_Realistic",
        pack_name="SDXL_angelic_warriors_Realistic",
        config_snapshot={"randomization": {"enabled": False}},
        stage_flags={"txt2img": True},
        randomizer_metadata={"enabled": False, "max_variants": 1},
    )

    records = builder.build_jobs([entry])
    assert records, "Builder should produce at least one normalized job record"

    record = records[0]
    assert record.prompt_pack_id == entry.pack_id
    assert "angelic knight" in record.positive_prompt.lower()
    assert record.stage_chain[0].stage_type == "txt2img"
    assert record.randomization_enabled is False
    assert record.pack_usage and record.pack_usage[0].pack_name == entry.pack_name
