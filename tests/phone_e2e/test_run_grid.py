"""The run grid when it has nothing to act on: no bulk buttons, and nothing printed in their place."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, pair


def test_a_fully_decided_run_grid_shows_no_stray_text(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    phone.goto(f"/#/run/{RUN}")
    phone.get_by_role("button", name="Keep the rest (1)").click()

    expect(phone.get_by_role("button", name="Keep the rest")).to_have_count(0)
    expect(phone.locator(".grid .tile")).to_have_count(1)
    expect(phone.locator("#view")).not_to_contain_text("null")


def test_an_empty_run_shows_no_stray_text(phone, gateway) -> None:
    pair(phone, gateway)
    phone.goto("/#/run/20261125_101500_gone")

    expect(phone.get_by_text("Nothing here any more.")).to_be_visible()
    expect(phone.locator("#view")).not_to_contain_text("null")
