from __future__ import annotations

from datetime import datetime

from src.learning.experiment_naming import build_experiment_identity


def test_build_experiment_identity_generates_name_description_and_summary() -> None:
    identity = build_experiment_identity(
        stage="txt2img",
        variable_label="Steps",
        prompt_text="Beautiful matrix portrait with cinematic lighting",
        model="juggernautXL_ragnarokBy.safetensors",
        vae="Automatic",
        timestamp=datetime(2026, 3, 10, 21, 49),
    )

    assert identity["name"].startswith("20260310_214900_txt2img_Steps_")
    assert "Steps" in identity["description"]
    assert "juggernautXL_ragnarokBy.safetensors" in identity["summary"]
