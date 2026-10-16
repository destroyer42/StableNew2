from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # anchor to the repository, not the working directory


def test_advanced_stage_cards_import_safety():
    files = [
        ROOT / "src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py",
        ROOT / "src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py",
        ROOT / "src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py",
    ]
    forbidden = {"src.pipeline", "src.api", "src.learning"}
    for fp in files:
        content = fp.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content, f"{fp} contains forbidden import {token}"
