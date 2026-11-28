"""Triage in a real browser: touch swipes, reason tags, Undo, the run grid, and what reaches the gateway's outbox.

Every outcome is asserted on the gateway (the records the PC would list), not only on the screen, so a refactor of
the page that changes what is sent fails here even when it looks the same.
"""

from __future__ import annotations

import time

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, decisions, pair, ready, release_held, swipe, wait_for


def by_item(records) -> dict[str, dict]:
    return {record["target"]["library_id"]: record for record in decisions(records)}


def test_swipes_keep_delete_and_favorite_with_tags(phone, gateway) -> None:
    for index, name in enumerate(("one", "two", "three")):
        gateway.publish(name, colour=index)
    pair(phone, gateway)
    phone.get_by_role("button", name="Review all (3)").click()

    ready(phone)
    expect(phone.locator("#state")).to_have_text("Not decided")
    swipe(phone, 220, 0)  # right: keep
    expect(phone.locator(".status button")).to_contain_text("2 / 3")

    ready(phone)
    phone.get_by_role("button", name="Face", exact=True).click()
    swipe(phone, -220, 0)  # left: delete
    expect(phone.locator(".status button")).to_contain_text("3 / 3")

    ready(phone)
    swipe(phone, 0, -260)  # up: favorite
    expect(phone.locator("#toast")).to_have_text("Nothing more to review")
    release_held(phone)

    sent = wait_for(
        lambda: len(decisions(gateway.outbox())) == 3 and gateway.outbox(), what="three decisions"
    )
    records = by_item(sent)
    assert records["lib-one_____"]["decision"] == {"verdict": "keep", "favorite": False, "tags": []}
    assert records["lib-two_____"]["decision"] == {
        "verdict": "delete",
        "favorite": False,
        "tags": ["face"],
    }
    assert records["lib-three___"]["decision"] == {"verdict": "keep", "favorite": True, "tags": []}
    assert len({record["idempotency_key"] for record in records.values()}) == 3


def test_undo_takes_back_the_held_decision_before_it_is_sent(phone, gateway) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    pair(phone, gateway)
    phone.get_by_role("button", name="Review all (2)").click()
    ready(phone)
    phone.get_by_role("button", name="Delete", exact=True).click()
    phone.locator("#undo").click()
    expect(phone.locator("#toast")).to_have_text("Undone")
    expect(phone.locator(".status button")).to_contain_text("1 / 2")
    ready(phone)
    time.sleep(0.5)
    assert decisions(gateway.outbox()) == [], "an undone decision never leaves the phone"

    phone.get_by_role("button", name="Keep", exact=True).click()
    release_held(phone)
    sent = wait_for(lambda: decisions(gateway.outbox()), what="the kept decision")
    assert [record["decision"]["verdict"] for record in sent] == ["keep"]


def test_the_run_grid_keeps_the_rest(phone, gateway) -> None:
    for index, name in enumerate(("one", "two", "three")):
        gateway.publish(name, colour=index)
    pair(phone, gateway)
    phone.get_by_role("button", name="Pipeline runs, 3 to review").click()
    phone.locator("section.run").first.click()
    expect(phone.locator(".grid .tile")).to_have_count(3)
    phone.get_by_role("button", name="Keep the rest (3)").click()
    expect(phone.locator("#toast")).to_have_text("3 kept")

    sent = wait_for(
        lambda: len(decisions(gateway.outbox())) == 3 and gateway.outbox(), what="three keeps"
    )
    assert {record["decision"]["verdict"] for record in decisions(sent)} == {"keep"}
    assert {record["target"]["library_id"] for record in decisions(sent)} == {
        "lib-one_____",
        "lib-two_____",
        "lib-three___",
    }


def test_deleting_a_run_asks_first(phone, gateway) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    pair(phone, gateway)
    phone.goto(f"/#/run/{RUN}")
    phone.get_by_role("button", name="Delete this run…").click()
    expect(phone.get_by_role("heading", name="Delete 2?")).to_be_visible()
    assert decisions(gateway.outbox()) == [], "nothing is deleted before the owner confirms"
    phone.locator(".sheet-actions button").last.click()
    sent = wait_for(
        lambda: len(decisions(gateway.outbox())) == 2 and gateway.outbox(), what="two deletes"
    )
    assert {record["decision"]["verdict"] for record in decisions(sent)} == {"delete"}
