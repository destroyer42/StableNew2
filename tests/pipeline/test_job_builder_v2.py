from __future__ import annotations

from src.gui.app_state_v2 import PackJobEntry
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_requests_v2 import PipelineRunMode, PipelineRunRequest, PipelineRunSource


def _build_pack_entry(index: int = 0) -> PackJobEntry:
    return PackJobEntry(
        pack_id=f"pack-{index}",
        pack_name="Angelic Heroes",
        config_snapshot={
            "txt2img": {
                "model": "juggernautXL_ragnarokBy.safetensors",
                "sampler_name": "DPM++ 2M",
                "steps": 40,
                "cfg_scale": 6.0,
                "width": 1216,
                "height": 832,
            },
        },
        prompt_text=f"Angelic hero variant {index}",
        negative_prompt_text="deformed hands",
        pack_row_index=index,
        matrix_slot_values={"environment": "volcanic lair"},
    )


def test_build_from_run_request_produces_normalized_job() -> None:
    builder = JobBuilderV2(id_fn=lambda: "job-abc", time_fn=lambda: 123.0)
    entry = _build_pack_entry()
    request = PipelineRunRequest(
        prompt_pack_id=entry.pack_id,
        selected_row_ids=[str(entry.pack_row_index)],
        config_snapshot_id="cfg-123",
        run_mode=PipelineRunMode.QUEUE,
        source=PipelineRunSource.ADD_TO_QUEUE,
        pack_entries=[entry],
    )

    jobs = builder.build_from_run_request(request)

    assert len(jobs) == 1
    record = jobs[0]
    assert record.job_id == "job-abc"
    assert record.prompt_pack_id == entry.pack_id
    assert record.positive_prompt == entry.prompt_text
    assert record.negative_prompt == entry.negative_prompt_text
    assert record.stage_chain and record.stage_chain[0].stage_type == "txt2img"


def test_build_from_run_request_limits_max_njr_count() -> None:
    builder = JobBuilderV2(id_fn=lambda: "job-limit", time_fn=lambda: 123.0)
    entries = [_build_pack_entry(i) for i in range(3)]
    request = PipelineRunRequest(
        prompt_pack_id=entries[0].pack_id,
        selected_row_ids=[str(entry.pack_row_index) for entry in entries],
        config_snapshot_id="cfg-xyz",
        run_mode=PipelineRunMode.QUEUE,
        source=PipelineRunSource.ADD_TO_QUEUE,
        max_njr_count=2,
        pack_entries=entries,
    )

    jobs = builder.build_from_run_request(request)
    assert len(jobs) == 2
