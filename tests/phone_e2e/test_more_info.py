"""NAME-INFO: "More info" in a real browser, on one item, an item published without it, and both compare sides."""

from __future__ import annotations

import re

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, pair

MORE_INFO = re.compile("More info")


def info(stage_path: str, seed: str) -> dict:
    return {
        "stage_path": stage_path,
        "model": "photoMomentum",
        "model_name": "photoMomentumSDXLNSFW_v20",
        "pack": "000-Style",
        "prompt_number": 1,
        "variant": 2,
        "made_at": "2026-11-27T16:48:00Z",
        "seed": seed,
        "batch": "<b>night</b> batch",
    }


def test_more_info_shows_what_made_an_item_as_text(phone, gateway) -> None:
    described = gateway.publish("described", info=info("txt2img → ADetailer", "123456789012345678"))
    pair(phone, gateway)
    phone.goto(f"/#/triage/{RUN}/{described['library_id']}")
    panel = phone.locator(".stage .info")
    expect(panel).to_be_hidden()

    phone.get_by_role("button", name=MORE_INFO).click()

    for line in (
        "Path: txt2img → ADetailer",
        "Model: photoMomentum (photoMomentumSDXLNSFW_v20)",
        "Prompt pack: 000-Style",
        "Prompt: prompt 1, variant 2",
        "Seed: 123456789012345678",
        "Batch: <b>night</b> batch",
    ):
        expect(panel.get_by_text(line, exact=True)).to_be_visible()
    assert panel.locator("b").count() == 0


def test_an_item_published_without_info_shows_what_it_has(phone, gateway) -> None:
    old = gateway.publish("old")
    pair(phone, gateway)
    phone.goto(f"/#/triage/{RUN}/{old['library_id']}")

    phone.get_by_role("button", name=MORE_INFO).click()

    panel = phone.locator(".stage .info")
    expect(panel.get_by_text("Model: juggernaut", exact=True)).to_be_visible()
    expect(panel.get_by_text("Seed: 42", exact=True)).to_be_visible()
    expect(panel.get_by_text("Path:", exact=False)).to_have_count(0)


def test_each_side_of_a_compare_has_its_own_info(phone, gateway) -> None:
    original = gateway.publish("orig", info=info("txt2img", "7"))
    result = gateway.publish(
        "result",
        run_id="20261125_120000_reprocess",
        parent=original,
        colour=2,
        info=info("txt2img → ADetailer", "8"),
    )
    pair(phone, gateway)
    phone.goto(f"/#/triage/{RUN}/{result['library_id']}")

    phone.get_by_role("button", name=MORE_INFO).click()

    panel = phone.locator(".stage .info")
    expect(panel.get_by_role("heading", name="Original", exact=True)).to_be_visible()
    expect(panel.get_by_role("heading", name="Rework", exact=True)).to_have_count(1)
    expect(panel.get_by_text("Path: txt2img", exact=True)).to_have_count(1)
    expect(panel.get_by_text("Path: txt2img → ADetailer", exact=True)).to_have_count(1)
    expect(panel.get_by_text("Seed: 7", exact=True)).to_have_count(1)
