"""What the phone does when the gateway refuses, cannot be reached or loses a reply; the To rate tab; Update the PC."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import decisions, pair, ready, release_held, wait_for
from tests.review_gateway_service.rating_samples import choice_task

HEAD = "1" * 40
MAIN = "2" * 40


def test_a_decision_the_gateway_will_not_take_is_kept_as_not_saved(phone, gateway) -> None:
    item = gateway.publish("one")
    pair(phone, gateway)
    phone.get_by_role("button", name="Review all (1)").click()
    ready(phone)
    assert (
        gateway.store.withdraw([item["library_id"]]) == 1
    )  # gone from the gateway after the page loaded it
    phone.get_by_role("button", name="Keep", exact=True).click()
    release_held(phone)

    lost = phone.locator("#rejected")
    expect(lost).to_have_text("1 not saved")
    lost.click()
    expect(phone.get_by_role("heading", name="Keep was not saved")).to_be_visible()
    expect(phone.get_by_role("button", name="Try again")).to_be_visible()
    assert decisions(gateway.outbox()) == []


def test_a_decision_made_while_the_gateway_is_unreachable_is_sent_once_when_it_is_back(
    phone, gateway
) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    phone.get_by_role("button", name="Review all (1)").click()
    ready(phone)
    phone.context.route("**/api/decisions", lambda route: route.abort("internetdisconnected"))
    phone.get_by_role("button", name="Keep", exact=True).click()
    release_held(phone)
    expect(phone.locator("#unsent")).to_have_text("1 unsent")
    assert decisions(gateway.outbox()) == []

    phone.context.unroute("**/api/decisions")
    phone.evaluate("window.dispatchEvent(new Event('online'))")
    expect(phone.locator("#unsent")).to_be_hidden()
    sent = wait_for(lambda: decisions(gateway.outbox()), what="the decision")
    assert len(sent) == 1


def test_a_lost_reply_is_resent_with_the_same_key_and_recorded_once(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    phone.get_by_role("button", name="Review all (1)").click()
    ready(phone)
    keys: list[str] = []

    def reply_lost(route) -> None:
        keys.append(route.request.post_data_json["idempotency_key"])
        route.fetch()  # the gateway records it...
        route.abort("connectionreset")  # ...and the phone never hears back

    phone.context.route("**/api/decisions", reply_lost)
    phone.get_by_role("button", name="Keep", exact=True).click()
    release_held(phone)
    wait_for(lambda: keys, what="the first send", page=phone)
    phone.context.unroute("**/api/decisions")
    phone.evaluate("window.dispatchEvent(new Event('online'))")
    expect(phone.locator("#unsent")).to_be_hidden()

    (record,) = decisions(gateway.outbox())
    assert record["idempotency_key"] == keys[0], (
        "the resend reuses the key, so the gateway keeps one record"
    )


def test_the_to_rate_tab_saves_an_answer_and_submits(phone, gateway) -> None:
    gateway.rating_task(choice_task())
    pair(phone, gateway)
    phone.get_by_role("button", name="To rate").click()
    phone.get_by_role("heading", name="Which step count next?").click()
    phone.locator("button[data-value='hy12']").click()
    submit = phone.locator("#rt-submit")
    expect(submit).to_have_text("Submit ratings")
    phone.once("dialog", lambda dialog: dialog.accept())
    submit.click()
    expect(phone.locator("#toast")).to_contain_text("Submitted")

    (submission,) = wait_for(gateway.rating_submissions, what="the submission")
    assert submission["task_id"] == "demo-choice"
    answers = submission["answers"]
    assert [answer["values"] for answer in answers] == [{"pick": "hy12"}]


def test_the_update_screen_shows_when_the_pc_last_reported(phone, gateway) -> None:
    gateway.pc_status(HEAD, MAIN)
    pair(phone, gateway, scopes=("review", "queue", "admin"))
    phone.get_by_role("button", name="Update the PC…").click()
    report = phone.locator(".run.pc")
    expect(report).to_contain_text("PC last reported")
    expect(report).to_contain_text(f"Running main at {HEAD[:10]}")
    expect(report).to_contain_text(f"origin/main is {MAIN[:10]} (3 new commits)")
    assert "NaN" not in report.inner_text(), "both times are real durations"
