from __future__ import annotations

from pathlib import Path

from src.gui.recipe_summary_v2 import build_saved_recipe_summary


def test_build_saved_recipe_summary_includes_core_fields(tmp_path: Path) -> None:
    recipe_path = tmp_path / "cinematic.json"
    recipe_path.write_text("{}", encoding="utf-8")

    summary = build_saved_recipe_summary(
        "cinematic",
        {
            "txt2img": {
                "model": "juggernaut",
                "sampler_name": "Euler",
                "width": 832,
                "height": 1216,
            },
            "pipeline": {
                "txt2img_enabled": True,
                "adetailer_enabled": True,
            },
        },
        recipe_path=recipe_path,
    )

    assert summary.name == "cinematic"
    assert summary.model == "juggernaut"
    assert summary.sampler == "Euler"
    assert summary.resolution == "832x1216"
    assert summary.enabled_stages == ("txt2img", "adetailer")
    assert "Saved Recipe: cinematic" in summary.to_label_text()
