"""PHONE-CORE PW-1: the installable shell. The manifest and the service worker in a real browser: installability,
opening with no gateway, a new version offered and taken, what is never stored, Repair, and the Trusted Types limit.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import expect

from tests.phone_e2e.harness import decisions, pair, ready, wait_for

NEXT_COMMIT = "abcdef0" + "1" * 33

# Resolves once the worker controls this page.
CONTROLLED = """() => new Promise((resolve) => {
  if (navigator.serviceWorker.controller) return resolve(true);
  navigator.serviceWorker.addEventListener("controllerchange", () => resolve(true), { once: true });
})"""

# {cache name: [stored path]} for every cache of this origin.
STORED = """async () => {
  const found = {};
  for (const name of await caches.keys()) {
    const requests = await (await caches.open(name)).keys();
    found[name] = requests.map((request) => new URL(request.url).pathname + new URL(request.url).search).sort();
  }
  return found;
}"""

# Asks for the new worker and says how its installation ended: "installed" or "redundant".
UPDATE = """async () => {
  const registration = await navigator.serviceWorker.getRegistration();
  const outcome = new Promise((resolve) => {
    registration.addEventListener("updatefound", () => {
      const worker = registration.installing;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed" || worker.state === "redundant") resolve(worker.state);
      });
    }, { once: true });
  });
  await registration.update();
  return outcome;
}"""


def page_version(phone: Any) -> str:
    return phone.locator('meta[name="rg-version"]').get_attribute("content")


def shell_of(phone: Any, version: str) -> list[str]:
    """The paths that version's shell consists of, as the gateway lists them."""

    listing = phone.request.get(f"/s/{version}/files.json").json()
    return sorted(
        [f"/s/{version}/{name}" for name in listing["files"]] + ["/", "/manifest.webmanifest"]
    )


def saved(phone: Any) -> str:
    """Wait until the worker controls the page with its whole shell stored; return the page's version."""

    assert phone.evaluate(CONTROLLED)
    version = page_version(phone)
    assert phone.evaluate(STORED) == {f"rg-shell-{version}": shell_of(phone, version)}
    return version


def next_version(tmp_path: Path) -> tuple[Path, str]:
    """A copy of the page's files with one byte-level change, as a later commit would have, and its version."""

    from review_gateway.static_files import STATIC_DIR, load_static

    tree = tmp_path / "next-static"
    shutil.copytree(STATIC_DIR, tree)
    with (tree / "core" / "core.css").open("a", encoding="utf-8") as sheet:
        sheet.write("\n/* a later version */\n")
    return tree, load_static(tree).version


def test_the_app_is_installable_and_the_worker_controls_the_page(phone, gateway) -> None:
    phone.goto("/")
    saved(phone)

    worker = phone.evaluate(
        "async () => { const r = await navigator.serviceWorker.ready;"
        " return { script: navigator.serviceWorker.controller.scriptURL, scope: r.scope,"
        " via: r.updateViaCache }; }"
    )
    assert worker == {"script": f"{gateway.url}/sw.js", "scope": f"{gateway.url}/", "via": "none"}
    browser = phone.context.new_cdp_session(phone)
    manifest = browser.send("Page.getAppManifest")
    assert manifest["url"] == f"{gateway.url}/manifest.webmanifest"
    assert manifest["errors"] == []
    data = json.loads(manifest["data"])
    # The installed app on the owner's phone has start URL, scope and id "/": these keep it the same app.
    assert (data["id"], data["start_url"], data["scope"]) == ("/", "/", "/")
    assert manifest["parsed"]["scope"] == f"{gateway.url}/"
    assert data["display"] == "standalone"
    # Chromium's own installability verdict is not asserted: headless reports no problem even with no manifest.
    for icon in data["icons"]:
        size = phone.evaluate(
            "async (src) => { const image = await createImageBitmap(await (await fetch(src)).blob());"
            " return `${image.width}x${image.height}`; }",
            icon["src"],
        )
        assert size == icon["sizes"], icon["src"]
    # The first installation is not an update.
    expect(phone.locator("#update")).to_be_hidden()


def test_with_no_gateway_the_saved_app_opens_and_says_it_is_offline(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway)
    version = saved(phone)
    phone.close()

    gateway.stop()
    phone.context.set_offline(True)
    again = phone.context.new_page()
    errors: list[str] = []
    again.on("pageerror", lambda error: errors.append(str(error)))
    response = again.goto("/")

    assert response.from_service_worker
    assert "trusted-types rg-sw" in response.headers["content-security-policy"]
    expect(again.locator("#title")).to_have_text("Review")
    expect(again.get_by_text("Offline: could not reach the gateway.")).to_be_visible()
    again.get_by_role("button", name="Settings").click()
    expect(again.locator("#about-version")).to_contain_text(f"Version {version}")
    expect(again.get_by_text("Saved on this phone: it opens without the gateway.")).to_be_visible()

    gateway.start()
    phone.context.set_offline(False)
    again.get_by_role("button", name="Back").click()
    expect(again.get_by_role("button", name="Review all (1)")).to_be_visible()
    assert not errors, errors


def test_a_new_version_is_offered_never_forced_and_reload_activates_it(
    phone, gateway, tmp_path
) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    pair(phone, gateway)
    old = saved(phone)
    tree, new = next_version(tmp_path)

    gateway.deploy(tree, NEXT_COMMIT)
    assert phone.evaluate(UPDATE) == "installed"

    banner = phone.locator("#update")
    expect(banner).to_contain_text(f"Update available · {NEXT_COMMIT[:7]}")
    assert page_version(phone) == old, "nothing is forced"
    phone.reload()
    assert page_version(phone) == old, "an ordinary reload stays on the running version"
    expect(banner).to_be_visible()

    # A decision still held for Undo is sent by Reload, as on leaving the page.
    phone.get_by_role("button", name="Review all (2)").click()
    ready(phone)
    phone.get_by_role("button", name="Keep", exact=True).click()
    assert decisions(gateway.outbox()) == [], "still held"
    banner.get_by_role("button", name="Reload").click()

    expect(phone.locator('meta[name="rg-version"]')).to_have_attribute("content", new)
    # Well inside the 8 seconds it would otherwise have been held.
    wait_for(lambda: decisions(gateway.outbox()), timeout=4, what="the held decision")
    assert len(decisions(gateway.outbox())) == 1
    assert saved(phone) == new, "the old version's cache is gone"
    expect(banner).to_be_hidden()
    phone.evaluate("location.hash = '#/settings'")
    expect(phone.locator("#about-version")).to_have_text(
        f"Version {new} · commit {NEXT_COMMIT[:7]}"
    )


def test_a_version_with_wrong_bytes_is_not_installed(phone, gateway, tmp_path) -> None:
    phone.goto("/")
    old = saved(phone)
    tree, new = next_version(tmp_path)

    gateway.deploy(tree, NEXT_COMMIT, corrupt=f"/s/{new}/core/text.js")
    assert phone.evaluate(UPDATE) == "redundant"

    assert phone.evaluate(STORED).keys() == {f"rg-shell-{old}"}
    expect(phone.locator("#update")).to_be_hidden()
    phone.reload()
    assert page_version(phone) == old

    gateway.deploy(tree, NEXT_COMMIT)  # the same version, served whole
    assert phone.evaluate(UPDATE) == "installed"
    expect(phone.locator("#update")).to_be_visible()


def test_api_answers_media_and_originals_are_never_stored(phone, gateway) -> None:
    item = gateway.publish("one")
    pair(phone, gateway)
    version = saved(phone)
    through_worker: dict[str, bool] = {}

    def seen(response: Any) -> None:
        path = response.url.removeprefix(gateway.url)
        if path.startswith(("/api/", "/media/", "/rating-media/", "/sw.js")):
            through_worker[path] = response.from_service_worker

    phone.on("response", seen)
    phone.get_by_role("button", name="Review all (1)").click()
    ready(phone)
    media = f"/media/{item['library_id']}/{item['sha256']}"
    statuses = phone.evaluate(
        "async (paths) => Promise.all(paths.map(async (path) =>"
        " (await fetch(path, { headers: { 'X-Review-Gateway': '1' } })).status))",
        [f"{media}/original", f"{media}/preview", f"{media}/thumb", "/api/session", "/api/status"],
    )
    assert statuses == [200] * 5
    phone.goto(f"{media}/original")  # opened by itself, as a long press would
    phone.goto("/")
    expect(phone.get_by_role("button", name="Review all (1)")).to_be_visible()

    assert f"{media}/original" in through_worker and "/api/session" in through_worker
    assert not any(through_worker.values()), through_worker
    assert phone.evaluate(STORED) == {f"rg-shell-{version}": shell_of(phone, version)}

    # A revoked phone: the 401 comes from the network, never from anything stored, and only the shell is left.
    (device,) = [d["device_id"] for d in gateway.outbox_page()["enrolled_devices"]]
    assert gateway.store.revoke_device(device)
    phone.reload()
    expect(phone.locator("#title")).to_have_text("Pair this phone")
    assert phone.evaluate(STORED) == {f"rg-shell-{version}": shell_of(phone, version)}


def test_repair_fetches_the_app_again_and_keeps_pairing_and_unsent_work(phone, gateway) -> None:
    gateway.publish("one")
    gateway.publish("two", colour=1)
    pair(phone, gateway)
    version = saved(phone)
    phone.context.route("**/api/decisions", lambda route: route.abort("internetdisconnected"))
    phone.get_by_role("button", name="Review all (2)").click()
    ready(phone)
    phone.get_by_role("button", name="Keep", exact=True).click()
    expect(phone.locator("#unsent")).to_have_text("1 unsent")
    phone.evaluate("location.hash = '#/'")
    phone.get_by_role("button", name="Settings").click()
    # Something only the old copy has, so that its removal shows.
    phone.evaluate(
        "async (name) => (await caches.open(name)).put('/s/stale.js', new Response('old'))",
        f"rg-shell-{version}",
    )

    with phone.expect_event("load"):
        phone.get_by_role("button", name="Repair this app").click()

    expect(phone.locator("#unsent")).to_have_text("1 unsent")
    assert any(cookie["name"] == "rg_session" for cookie in phone.context.cookies())
    wait_for(
        lambda: phone.evaluate(STORED).get(f"rg-shell-{version}") == shell_of(phone, version),
        what="the shell to be stored again",
        page=phone,
    )
    phone.reload()
    assert saved(phone) == version


def test_repair_without_the_gateway_asks_first(phone, gateway) -> None:
    phone.goto("/")
    version = saved(phone)
    phone.evaluate("location.hash = '#/settings'")
    expect(phone.get_by_role("button", name="Repair this app")).to_be_visible()
    gateway.stop()
    questions: list[str] = []

    def refuse(dialog: Any) -> None:
        questions.append(dialog.message)
        dialog.dismiss()

    phone.on("dialog", refuse)
    phone.get_by_role("button", name="Repair this app").click()

    wait_for(lambda: questions, what="the question", page=phone)
    assert "will not open until the gateway is back" in questions[0]
    assert phone.evaluate(STORED).keys() == {f"rg-shell-{version}"}
    gateway.start()


def test_no_script_address_can_be_named_but_through_the_workers_own_policy(phone) -> None:
    phone.goto("/")
    saved(phone)

    refused = phone.evaluate(
        """async () => {
          const attempt = async (act) => {
            try {
              await act();
              return false;
            } catch {
              return true;
            }
          };
          return {
            anotherPolicy: await attempt(() => trustedTypes.createPolicy("other", {})),
            aSecondOfTheSame: await attempt(() => trustedTypes.createPolicy("rg-sw", {})),
            aBareAddress: await attempt(() => navigator.serviceWorker.register("/sw.js")),
          };
        }"""
    )

    assert refused == {"anotherPolicy": True, "aSecondOfTheSame": True, "aBareAddress": True}
