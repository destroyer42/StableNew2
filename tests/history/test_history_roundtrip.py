from __future__ import annotations

import json
from pathlib import Path

from src.history.job_history_store import JobHistoryStore


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_roundtrip_save_load_is_deterministic(tmp_path) -> None:
    history_path = tmp_path / "history.jsonl"
    legacy_entries = [
        {
            "job_id": "legacy-001",
            "pipeline_config": {
                "prompt": "ancient job",
                "model": "v1",
                "sampler": "Euler a",
                "width": 512,
                "height": 512,
                "steps": 10,
                "cfg_scale": 6.0,
            },
        },
        {
            "job_id": "snapshot-002",
            "status": "completed",
            "snapshot": {
                "normalized_job": {
                    "job_id": "snapshot-002",
                    "path_output_dir": "out",
                    "filename_template": "{seed}",
                    "seed": 11,
                    "variant_index": 0,
                    "variant_total": 1,
                    "batch_index": 0,
                    "batch_total": 1,
                    "created_ts": 1.0,
                    "prompt_pack_id": "",
                    "prompt_pack_name": "",
                    "prompt_pack_row_index": 0,
                    "positive_prompt": "sky",
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
        },
    ]
    _write_jsonl(history_path, legacy_entries)

    store = JobHistoryStore(history_path)
    first = store.load()
    store.save(first)
    second = store.load()

    assert [r.to_dict() for r in first] == [r.to_dict() for r in second]
    assert all(rec.history_version == "2.6" for rec in second)
    assert all("pipeline_config" not in rec.njr_snapshot for rec in second)
