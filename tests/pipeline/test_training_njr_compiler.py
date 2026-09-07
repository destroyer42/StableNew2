from __future__ import annotations

from src.pipeline.training_njr_compiler import TrainingIntent, compile_training_intent


def test_training_compiler_emits_training_njr_without_pack_identity() -> None:
    record = compile_training_intent(
        TrainingIntent(
            config={
                "train_lora": {
                    "enabled": True,
                    "character_name": "Ada",
                    "image_dir": "images/ada",
                    "output_dir": "weights",
                    "epochs": 2,
                    "learning_rate": 0.0001,
                    "base_model": "sdxl",
                }
            },
            character_name="Ada",
            character_key="ada",
            output_dir="weights",
        ),
        id_fn=lambda: "train-1",
    )

    assert record.job_id == "train-1"
    assert record.source.kind.value == "training"
    assert record.prompt_pack_id == ""
    assert record.workload_kind.value == "training"
    assert record.stage_chain[0].stage_type == "train_lora"
