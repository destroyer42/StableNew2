"""Regression coverage for JobHistoryStore append/load behavior."""

from src.history.history_record import HistoryRecord
from src.history.job_history_store import JobHistoryStore


def _history_record(index: int) -> HistoryRecord:
    return HistoryRecord(
        id=f"test-job-{index}",
        timestamp=f"2026-03-28T00:00:{index:02d}Z",
        status="completed",
        njr_snapshot={
            "normalized_job": {
                "job_id": f"test-job-{index}",
                "path_output_dir": "out",
                "filename_template": "{seed}",
                "seed": index,
                "variant_index": 0,
                "variant_total": 1,
                "batch_index": 0,
                "batch_total": 1,
                "created_ts": float(index),
                "prompt_pack_id": "",
                "prompt_pack_name": "",
                "prompt_pack_row_index": 0,
                "positive_prompt": f"prompt {index}",
                "negative_prompt": "",
                "steps": 25,
                "cfg_scale": 7.0,
                "width": 512,
                "height": 512,
                "sampler_name": "Euler",
                "scheduler": "",
                "stage_chain": [],
                "loop_type": "pipeline",
                "loop_count": 1,
                "images_per_prompt": 1,
                "variant_mode": "standard",
                "run_mode": "QUEUE",
                "queue_source": "ADD_TO_QUEUE",
                "randomization_enabled": False,
                "matrix_slot_values": {},
                "lora_tags": [],
                "output_paths": [],
                "status": "completed",
            }
        },
    )


def test_append_and_load_roundtrip(tmp_path) -> None:
    store_path = tmp_path / "test_history.jsonl"
    store = JobHistoryStore(store_path)

    for i in range(10):
        store.append(_history_record(i))

    records = store.load()

    assert len(records) == 10
    assert records[0].id == "test-job-0"
    assert records[-1].id == "test-job-9"
