"""Rework compare and the two-step phone actions (RG-140) in a real browser, with the PC played over the sync API."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, decisions, pair, release_held, wait_for

REVISION = "ab" * 32


def summary(gateway) -> dict:
    return {
        "expires_at": gateway.clock.stamp(minutes=30),
        "action": "fix_face",
        "revision": REVISION,
        "title": "Fix face",
        "lines": ["ADetailer face pass on this image"],
        "job_count": 1,
        "queue_position": "next",
        "warnings": [
            {
                "code": "image_model_family_unverified",
                "subject": "juggernautXL.safetensors",
                "title": "Unclassified checkpoint.",
                "why": "<b>not</b> markup",
                "fix": "Classify it.",
            }
        ],
    }


def actions(gateway, step: str) -> list[dict]:
    return [
        record
        for record in gateway.outbox()
        if record["kind"] == "action_request" and record["action_request"]["params"]["step"] == step
    ]


def test_a_rework_is_compared_with_its_original_and_keep_rework_archives_the_original(
    phone, gateway
) -> None:
    original = gateway.publish("orig")
    result = gateway.publish(
        "result", run_id="20261125_120000_reprocess", parent=original, colour=2
    )
    pair(phone, gateway)
    phone.goto(f"/#/triage/{RUN}/{result['library_id']}")
    expect(phone.locator("#state")).to_have_text("Rework result: which is better?")
    for mode in ("Flip", "Slider", "Side by side"):
        phone.get_by_role("button", name=mode, exact=True).click()
    keep_rework = phone.get_by_role("button", name="Keep rework", exact=True)
    expect(keep_rework).to_be_enabled()
    keep_rework.click()
    release_held(phone)

    sent = wait_for(
        lambda: len(decisions(gateway.outbox())) == 2 and gateway.outbox(), what="the compare pick"
    )
    verdicts = {
        record["target"]["library_id"]: record["decision"]["verdict"] for record in decisions(sent)
    }
    assert verdicts == {result["library_id"]: "keep", original["library_id"]: "delete"}


def test_fix_face_shows_the_pcs_summary_as_text_then_queues_and_shows_the_receipt(
    phone, gateway
) -> None:
    gateway.publish("one")
    pair(phone, gateway, scopes=("review", "queue"))
    phone.get_by_role("button", name="Review all (1)").click()
    phone.get_by_role("button", name="Fix face", exact=True).click()

    (prepared,) = wait_for(lambda: actions(gateway, "prepare"), what="the prepare request")
    gateway.acknowledge(prepared["record_id"], receipt={"action_summary": summary(gateway)})
    expect(phone.get_by_text("ADetailer face pass on this image")).to_be_visible()
    # S7: PC-written text is shown as text, never as markup.
    expect(phone.get_by_text("<b>not</b> markup", exact=False)).to_be_visible()
    assert phone.locator(".sheet b").count() == 0

    phone.get_by_role("button", name="Queue", exact=True).click()
    (confirmed,) = wait_for(lambda: actions(gateway, "confirm"), what="the confirm request")
    params = confirmed["action_request"]["params"]
    assert params["prepared_record"] == prepared["record_id"]
    assert params["summary_revision"] == REVISION
    gateway.acknowledge(
        confirmed["record_id"], receipt={"job_ids": ["a" * 32], "action_summary": summary(gateway)}
    )
    expect(phone.get_by_role("heading", name="Fix face: queued")).to_be_visible()
    expect(phone.get_by_text("1 job admitted on the PC.", exact=False)).to_be_visible()
