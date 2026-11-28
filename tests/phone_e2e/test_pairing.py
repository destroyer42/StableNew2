"""Pairing in a real browser: the code, the HttpOnly cookie, the home screen, and losing the pairing (S1, S11)."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import pair


def test_an_unpaired_phone_sees_the_pairing_screen_and_a_wrong_code_is_refused(
    phone, gateway
) -> None:
    gateway.offer()
    phone.goto("/")
    expect(phone.locator("#title")).to_have_text("Pair this phone")
    phone.get_by_label("Pairing code").fill("WRONG000")
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.get_by_role("alert")).to_contain_text("That code did not work")


def test_pairing_sets_an_httponly_cookie_and_opens_the_home_screen(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    cookie = next(c for c in phone.context.cookies() if c["name"] == "rg_session")
    assert cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Lax"
    assert phone.evaluate("document.cookie") == "", (
        "the session token is never visible to page script"
    )
    expect(phone.get_by_role("button", name="Review all (1)")).to_be_visible()
    expect(phone.get_by_role("button", name="Pipeline runs, 1 to review")).to_be_visible()


def test_a_revoked_phone_is_sent_back_to_pairing(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    (device,) = [d["device_id"] for d in gateway.outbox_page()["enrolled_devices"]]
    assert gateway.store.revoke_device(device)
    phone.reload()
    expect(phone.locator("#title")).to_have_text("Pair this phone")
