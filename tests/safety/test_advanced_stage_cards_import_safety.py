from __future__ import annotations

from pathlib import Path


def test_advanced_stage_cards_import_safety():
    files = [
        Path("src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py"),
        Path("src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py"),
        Path("src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py"),
    ]
    forbidden = {"src.pipeline", "src.api", "src.learning"}
    for fp in files:
        content = fp.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in content, f"{fp} contains forbidden import {token}"
