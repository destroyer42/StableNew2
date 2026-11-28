"""Image open times in a real browser (PHONE-FAST gate): what a viewed item sends, and what is dropped.

Rows are read back through the PC's sync route. Leaving the page (``pagehide``) sends what is waiting.
"""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import pair, png, ready, release_held, wait_for

#: The harness publishes this rendition for the first colour.
PREVIEW_BYTES = len(png(120, 180, (200, 60, 60)))


def timings(gateway) -> list[dict]:
    response = gateway.sync.get("/sync/v1/open-timings")
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def sent(gateway, count: int, **options) -> list[dict]:
    return wait_for(
        lambda: len(found := timings(gateway)) >= count and found,
        what=f"{count} open time(s)",
        **options,
    )


def review(phone, gateway, *names: str) -> None:
    for name in names:
        gateway.publish(name)
    pair(phone, gateway)
    phone.get_by_role("button", name=f"Review all ({len(names)})").click()
    ready(phone)


def test_a_viewed_item_sends_one_open_time_once(phone, gateway) -> None:
    review(phone, gateway, "one")
    release_held(phone)

    (row,) = sent(gateway, 1)

    assert set(row) == {"at", "ms", "source", "bytes"}
    assert row["source"] == "network"
    assert row["bytes"] == PREVIEW_BYTES
    assert 0 <= row["ms"] < 60_000
    release_held(phone)
    phone.wait_for_timeout(500)
    assert len(timings(gateway)) == 1


def test_an_item_fetched_ahead_or_seen_before_is_not_counted_as_network(phone, gateway) -> None:
    review(phone, gateway, "one", "two")
    phone.get_by_role("button", name="Next item").click()
    expect(phone.locator(".status button")).to_contain_text("2 / 2")
    ready(phone)
    phone.get_by_role("button", name="Previous item").click()
    expect(phone.locator(".status button")).to_contain_text("1 / 2")
    ready(phone)
    release_held(phone)

    rows = sent(gateway, 3)

    assert [row["source"] for row in rows] == ["network", "prefetch", "cache"]
    assert all(row["bytes"] == PREVIEW_BYTES for row in rows)


def test_waiting_times_go_as_one_batch_and_not_before_thirty_seconds(phone, gateway) -> None:
    phone.clock.install()
    review(phone, gateway, "one", "two")
    phone.get_by_role("button", name="Next item").click()
    ready(phone)
    batches: list[str] = []
    phone.on(
        "request", lambda request: "/api/timings" in request.url and batches.append(request.url)
    )

    phone.clock.fast_forward(20_000)
    phone.wait_for_timeout(300)
    assert batches == []
    phone.clock.fast_forward(40_000)

    assert len(sent(gateway, 2, page=phone)) == 2
    assert len(batches) == 1


def test_open_times_are_dropped_when_the_phone_is_offline(phone, gateway) -> None:
    review(phone, gateway, "one", "two")
    phone.context.set_offline(True)
    release_held(phone)  # the first item's time cannot be sent
    phone.wait_for_timeout(300)
    phone.context.set_offline(False)
    phone.get_by_role("button", name="Next item").click()
    ready(phone)
    release_held(phone)

    sent(gateway, 1, page=phone)
    phone.wait_for_timeout(500)

    assert [row["source"] for row in timings(gateway)] == ["prefetch"]  # only the second item's


def test_a_batch_that_fails_is_tried_once_more_with_the_same_key(phone, gateway) -> None:
    bodies: list[dict] = []

    def reply_lost(route) -> None:
        bodies.append(route.request.post_data_json)
        route.fetch()  # the gateway stored it; the phone never hears
        route.abort("connectionreset")

    review(phone, gateway, "one")
    phone.context.route("**/api/timings", reply_lost)
    release_held(phone)
    sent(gateway, 1, page=phone)
    phone.wait_for_timeout(300)
    phone.context.unroute("**/api/timings")
    # The status only: Playwright never delivers the body of a keepalive request's response.
    with phone.expect_response("**/api/timings") as again:
        release_held(phone)

    assert again.value.status == 200
    assert again.value.request.post_data_json == bodies[0]
    assert len(timings(gateway)) == 1  # the gateway knew the key


def test_a_batch_that_fails_twice_is_dropped(phone, gateway) -> None:
    attempts: list[str] = []

    def unreachable(route) -> None:
        attempts.append(route.request.url)
        route.abort("internetdisconnected")

    review(phone, gateway, "one")
    phone.context.route("**/api/timings", unreachable)
    for _ in range(3):
        release_held(phone)
        phone.wait_for_timeout(300)

    assert len(attempts) == 2
    assert timings(gateway) == []
