"""Pairing in a real browser: the code, the HttpOnly cookie, the home screen, and losing the pairing (S1, S11)."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import CODE, pair


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


# --- PHONE-CORE PP-1: the QR's link, "#/pair/<code>" ------------------------------------------------------------------

SCANNED = f"{CODE[:4]}-{CODE[4:]}"  # as the PC shows it, and as its QR link carries it


def test_a_scanned_link_fills_the_code_and_leaves_no_trace_of_it_in_history(phone, gateway) -> None:
    gateway.publish("one")
    gateway.offer()
    asked: list[str] = []
    phone.on("request", lambda request: asked.append(request.url))
    phone.goto("about:blank")

    phone.goto(f"/#/pair/{SCANNED}")

    expect(phone.get_by_label("Pairing code")).to_have_value(SCANNED)
    assert phone.evaluate("location.hash") == "#/pair"
    assert gateway.outbox_page()["enrolled_devices"] == [], "nothing pairs unasked"
    # The entry was rewritten, not added to: leaving and returning never shows the code again.
    phone.go_back()
    phone.go_forward()
    expect(phone.locator("#title")).to_have_text("Pair this phone")
    assert CODE[4:] not in phone.url
    assert not [url for url in asked if CODE[4:] in url], "the fragment never leaves the phone"

    phone.goto(f"/#/pair/{SCANNED}")
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.locator("#title")).to_have_text("Review")
    assert phone.evaluate("location.hash") == "#/"
    expect(phone.get_by_role("button", name="Review all (1)")).to_be_visible()


def test_a_link_opened_on_the_open_pairing_screen_fills_that_form(phone, gateway) -> None:
    gateway.offer()
    phone.goto("/")
    expect(phone.locator("#title")).to_have_text("Pair this phone")
    phone.get_by_label("Phone name").fill("Pocket")
    before = phone.evaluate("history.length")

    phone.evaluate(f"location.hash = '#/pair/{SCANNED}'")

    expect(phone.get_by_label("Pairing code")).to_have_value(SCANNED)
    expect(phone.get_by_label("Phone name")).to_have_value("Pocket")
    assert phone.evaluate("location.hash") == "#/pair"
    assert phone.evaluate("history.length") == before + 1
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.locator("#title")).to_have_text("Review")


def test_a_paired_phone_can_pair_again_from_a_link_or_leave_it(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    gateway.offer(code="M4NP7QRS")

    phone.goto("/#/pair/M4NP-7QRS")
    expect(phone.get_by_label("Pairing code")).to_have_value("M4NP-7QRS")
    phone.get_by_role("button", name="Back").click()
    expect(phone.locator("#title")).to_have_text("Review")
    assert len(gateway.outbox_page()["enrolled_devices"]) == 1

    phone.evaluate("location.hash = '#/pair/M4NP-7QRS'")
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.locator("#title")).to_have_text("Review")
    assert len(gateway.outbox_page()["enrolled_devices"]) == 2


def test_a_link_with_something_else_in_it_fills_nothing(phone, gateway) -> None:
    phone.goto("/#/pair/%3Cimg%20src%3Dx%3E")

    expect(phone.get_by_label("Pairing code")).to_have_value("")
    assert phone.evaluate("location.hash") == "#/pair"


def test_typing_the_code_still_pairs_after_a_link_expired(phone, gateway) -> None:
    gateway.publish("one")
    gateway.offer()
    phone.goto("/#/pair/WRNG-C0DE")
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.get_by_role("alert")).to_contain_text("That code did not work")

    phone.get_by_label("Pairing code").fill(SCANNED.lower())
    phone.get_by_role("button", name="Pair this phone").click()
    expect(phone.locator("#title")).to_have_text("Review")
