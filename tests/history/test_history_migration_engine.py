from __future__ import annotations

from datetime import datetime

from src.history.history_migration_engine import HistoryMigrationEngine


def test_migrate_legacy_entries_idempotent() -> None:
    engine = HistoryMigrationEngine()
    legacy_v1 = {
        "job_id": "legacy-1",
        "pipeline_config": {
            "prompt": "a castle on a hill",
            "negative_prompt": "lowres",
            "model": "v1-5",
            "sampler": "Euler a",
            "width": 512,
            "height": 512,
            "steps": 12,
            "cfg_scale": 6.5,
        },
        "draft_bundle": {"unused": True},
    }
    legacy_v2 = {
        "job_id": "early-v2",
        "snapshot": {
            "normalized_job": {
                "job_id": "early-v2",
                "path_output_dir": "out",
                "filename_template": "{seed}",
                "seed": 7,
                "variant_index": 0,
                "variant_total": 1,
                "batch_index": 0,
                "batch_total": 1,
                "created_ts": 1.0,
                "prompt_pack_id": "",
                "prompt_pack_name": "",
                "prompt_pack_row_index": 0,
                "positive_prompt": "trees",
                "negative_prompt": "",
                "steps": 20,
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
    }

    migrated = engine.migrate_all([legacy_v1, legacy_v2])

    assert len(migrated) == 2
    assert all(entry["history_version"] == "2.6" for entry in migrated)
    assert all("pipeline_config" not in entry["njr_snapshot"] for entry in migrated)
    assert all("draft_bundle" not in entry["njr_snapshot"] for entry in migrated)

    migrated_again = engine.migrate_all(migrated)
    assert migrated_again == migrated


def test_migration_preserves_stable_ids() -> None:
    engine = HistoryMigrationEngine()
    ts = datetime.utcnow().isoformat()
    entry = {
        "job_id": "draft-job",
        "created_at": ts,
        "status": "completed",
        "bundle_summary": {"foo": "bar"},
        "snapshot": {
            "normalized_job": {
                "job_id": "draft-job",
                "path_output_dir": "out",
                "filename_template": "{seed}",
                "seed": 42,
                "variant_index": 0,
                "variant_total": 1,
                "batch_index": 0,
                "batch_total": 1,
                "created_ts": 1.0,
                "prompt_pack_id": "",
                "prompt_pack_name": "",
                "prompt_pack_row_index": 0,
                "positive_prompt": "mountain",
                "negative_prompt": "",
                "steps": 30,
                "cfg_scale": 7.5,
                "width": 640,
                "height": 640,
                "sampler_name": "Euler a",
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
    }

    migrated = engine.migrate_entry(entry)

    assert migrated["id"] == "draft-job"
    assert migrated["timestamp"] == ts
    assert migrated["status"] == "completed"
    assert "bundle_summary" not in migrated["njr_snapshot"]
