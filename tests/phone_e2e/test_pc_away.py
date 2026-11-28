"""A request made while the PC is away (RG-160), and every place the page then shows that it is waiting."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, SCHEMA_VERSION, pair, ready, wait_for


def publish_catalog(gateway) -> None:
    """What the PC offers while it is away. The PC never polls the outbox here, so the gateway has not seen it."""

    catalog = {
        "schema_version": SCHEMA_VERSION,
        "type": "choice_catalog",
        "published_at": gateway.clock.stamp(),
        "models": [{"id": "0123456789abcdef", "label": "juggernautXL.safetensors", "warnings": []}],
        "warnings": [],
        "ratios": [{"id": "1x1", "label": "Square 1:1"}],
        "video": {"available": True, "label": "Wan2.2 I2V"},
        "models_as_of": gateway.clock.stamp(),
        "image_backend_ready": True,
        "truncated": False,
    }
    response = gateway.sync.put("/sync/v1/choice-catalog", json=catalog)
    assert response.status_code == 200, response.text


def test_a_request_made_while_the_pc_is_away_waits_and_shows_everywhere(phone, gateway) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    publish_catalog(gateway)
    pair(phone, gateway, scopes=("review", "queue"))
    expect(phone.locator("#waiting")).to_be_hidden()
    phone.get_by_role("button", name="Review all (2)").click()
    ready(phone)

    phone.get_by_role("button", name="Make video", exact=True).click()
    phone.get_by_role("button", name="Queue when the PC is back").click()
    expect(phone.locator("#toast")).to_have_text("Saved; the PC runs it when it can")
    expect(phone.locator("#state")).to_have_text("Not decided · request waiting for PC")
    expect(phone.locator("#waiting")).to_have_text("1 waiting for PC")
    order = phone.evaluate("[...document.querySelectorAll('#bar > *')].map((node) => node.id)")
    assert order == ["back", "title", "unsent", "waiting", "rejected"]

    # Deleting that item asks first, on the item and for the whole run.
    phone.get_by_role("button", name="Delete", exact=True).click()
    expect(phone.get_by_role("heading", name="Delete this image?")).to_be_visible()
    phone.get_by_role("button", name="Cancel", exact=True).click()
    phone.goto(f"/#/run/{RUN}")
    expect(phone.locator(".grid .badge.waiting")).to_have_count(1)
    phone.get_by_role("button", name="Delete this run…").click()
    expect(phone.get_by_text("1 have a request waiting. Deleting cancels it.")).to_be_visible()
    phone.get_by_role("button", name="Cancel", exact=True).click()

    phone.locator("#waiting").click()
    expect(phone.locator("#title")).to_have_text("Waiting for the PC")
    expect(phone.get_by_role("heading", name="Make video")).to_be_visible()
    wait_for(
        lambda: [record for record in gateway.outbox() if record["kind"] == "action_request"],
        what="the waiting request at the gateway",
    )


def test_a_rework_queued_while_the_pc_is_away_moves_on_to_the_next_item(phone, gateway) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    publish_catalog(gateway)
    pair(phone, gateway, scopes=("review", "queue"))
    phone.get_by_role("button", name="Review all (2)").click()
    ready(phone)

    phone.get_by_role("button", name="Fix face", exact=True).click()
    expect(phone.get_by_role("button", name="Face", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    phone.get_by_role("button", name="Queue when the PC is back").click()

    expect(phone.locator(".status button")).to_contain_text("2 / 2")
    expect(phone.locator(".sheet")).to_have_count(0)
