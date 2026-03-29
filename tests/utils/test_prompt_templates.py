from __future__ import annotations

import json

import pytest

from src.utils.prompt_templates import (
    apply_prompt_template,
    clear_prompt_template_cache,
    compose_prompt_text,
    get_prompt_template,
    load_prompt_templates,
)


def test_load_prompt_templates_reads_valid_catalog(tmp_path) -> None:
    template_path = tmp_path / "prompt_templates.json"
    template_path.write_text(
        json.dumps(
            {
                "templates": {
                    "hero_intro": {
                        "label": "Hero Intro",
                        "category": "shot",
                        "template": "dramatic reveal of {subject} in {environment}",
                        "description": "Simple fixture template.",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    clear_prompt_template_cache()
    templates = load_prompt_templates(template_path)

    assert set(templates.keys()) == {"hero_intro"}
    assert templates["hero_intro"].label == "Hero Intro"
    assert templates["hero_intro"].placeholders == ("subject", "environment")


def test_load_prompt_templates_rejects_invalid_payload(tmp_path) -> None:
    template_path = tmp_path / "prompt_templates.json"
    template_path.write_text('{"templates": []}', encoding="utf-8")

    clear_prompt_template_cache()
    with pytest.raises(ValueError, match="templates"):
        load_prompt_templates(template_path)


def test_apply_prompt_template_requires_all_values() -> None:
    definition = get_prompt_template("tracking_action")

    with pytest.raises(ValueError, match="action"):
        apply_prompt_template(
            definition,
            {"subject": "the courier", "environment": "the market", "camera": "handheld"},
        )


def test_compose_prompt_text_combines_template_and_freeform_details() -> None:
    composed = compose_prompt_text(
        "moody_portrait",
        {
            "subject": "the detective",
            "environment": "a neon alley",
            "lighting": "rim lighting",
            "mood": "quiet tension",
            "style": "35mm film still",
        },
        "rain drifting through the frame",
    )

    assert "moody portrait of the detective" in composed
    assert "rain drifting through the frame" in composed
