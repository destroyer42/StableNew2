"""RG-170 in a real browser: scores with notes, A or B pairs and a ranking, each as far as the submission the PC reads."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import expect

from tests.phone_e2e.harness import pair, wait_for
from tests.review_gateway_service.rating_samples import (
    pair_task,
    publish,
    ranking_task,
    score_task,
)

ANSWERS = "**/api/rating/tasks/*/answers"
UNSENT = "localStorage.getItem('rg.rating.unsent') || '{}'"


def open_task(phone: Any, title: str) -> None:
    phone.get_by_role("button", name="To rate").click()
    phone.get_by_role("heading", name=title).click()


def submit(phone: Any, gateway: Any) -> list[dict[str, Any]]:
    button = phone.locator("#rt-submit")
    expect(button).to_have_text("Submit ratings")
    phone.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(phone.locator("#toast")).to_contain_text("Submitted")
    (submission,) = wait_for(gateway.rating_submissions, what="the submission")
    return submission["answers"]


def test_scores_and_notes_made_while_unreachable_are_sent_when_back_and_submitted(
    phone, gateway
) -> None:
    publish(gateway, score_task())
    pair(phone, gateway)
    open_task(phone, "Demo scores")
    expect(phone.locator("#rt-submit")).to_have_text("0 of 1 answered")

    phone.context.route(ANSWERS, lambda route: route.abort("internetdisconnected"))
    for position, (score, happened) in enumerate((("4", "Yes"), ("2", "No"))):
        clip = phone.locator(".rt-scored").nth(position)
        clip.locator(".rt-options.score").first.get_by_role("button", name=score).click()
        clip.get_by_role("button", name=happened, exact=True).click()
    # A note is saved a moment after typing stops, without leaving the box.
    phone.get_by_placeholder("Notes (optional)").first.fill("soft face")
    wait_for(lambda: "soft face" in phone.evaluate(UNSENT), what="the note", page=phone)
    expect(phone.locator("#rt-submit")).to_have_text("Submit ratings")

    phone.context.unroute(ANSWERS)
    phone.evaluate("window.dispatchEvent(new Event('online'))")
    wait_for(lambda: phone.evaluate(UNSENT) == "{}", what="the answers to be sent", page=phone)

    # Leaving the task and opening it again reads the answers back from the gateway.
    phone.get_by_role("button", name="Back").click()
    expect(phone.get_by_text("ready to submit")).to_be_visible()
    phone.get_by_role("heading", name="Demo scores").click()
    first = phone.locator(".rt-scored").first
    expect(first.locator(".rt-options.score").first.locator("[data-value='4']")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(first.get_by_placeholder("Notes (optional)")).to_have_value("soft face")

    answers = {answer["clip_id"]: answer for answer in submit(phone, gateway)}
    assert answers["A"]["values"] == {"fidelity": "4", "action": "achieved"}
    assert answers["A"]["notes"] == "soft face"
    assert answers["B"]["values"] == {"fidelity": "2", "action": "not_achieved"}


def test_each_pair_of_an_a_or_b_set_is_chosen_and_submitted(phone, gateway) -> None:
    publish(gateway, pair_task())
    pair(phone, gateway)
    open_task(phone, "Demo A/B")

    for number in (1, 2):
        expect(phone.get_by_text(f"{number} of 2", exact=True)).to_be_visible()
        rows = phone.locator(".rt-options.choice")
        rows.nth(0).get_by_role("button", name="A", exact=True).click()
        rows.nth(1).get_by_role("button", name="Same", exact=True).click()
        if number == 1:
            phone.get_by_role("button", name="Next").click()

    answers = submit(phone, gateway)
    assert {answer["item_id"]: answer["values"] for answer in answers} == {
        item: {"motion": "A", "stable": "tie"} for item in ("p01", "p02")
    }


def test_a_ranking_is_tapped_best_first_and_submitted(phone, gateway) -> None:
    publish(gateway, ranking_task())
    pair(phone, gateway)
    open_task(phone, "Demo ranking")

    row = phone.locator(".rt-options.rank")
    row.get_by_role("button", name="B", exact=True).click()  # with two clips the other is second
    expect(row.locator("[data-clip='B']")).to_have_text("1. B")
    expect(row.locator("[data-clip='A']")).to_have_text("2. A")

    (answer,) = submit(phone, gateway)
    assert answer["values"] == {"motion": "B>A"}
