"""V1-6 "Continue clip" in a real browser: offered on a video only, words, then the PC's summary, then Queue."""

from __future__ import annotations

from playwright.sync_api import expect

from tests.phone_e2e.harness import RUN, SCHEMA_VERSION, pair, png, sha, wait_for

REVISION = "cd" * 32


def publish_clip(gateway) -> dict[str, str]:
    """One video item. Its video bytes are not playable: the journey is about the action, not playback."""

    blobs = {
        "thumb_320": png(32, 48, (60, 90, 200)),
        "mobile_video": b"mobile-clip" * 16,
        "original": b"original-clip" * 16,
    }
    types = {"thumb_320": "image/png", "mobile_video": "video/mp4", "original": "video/mp4"}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "item_manifest",
        "item": {"library_id": "lib-clip____", "sha256": sha(blobs["original"])},
        "kind": "video",
        "duration_s": 5.0,
        "run_id": RUN,
        "created_at": gateway.clock.stamp(),
        "media": {
            variant: {"sha256": sha(data), "bytes": len(data), "content_type": types[variant]}
            for variant, data in blobs.items()
        },
        "display": {"model": "wan", "prompt_excerpt": "a lighthouse", "seed": 7},
        "source": "pipeline",
    }
    response = gateway.sync.post("/sync/v1/items", json=manifest)
    assert response.status_code == 200, response.text
    by_digest = {sha(data): data for data in blobs.values()}
    for digest in response.json()["missing"]:
        uploaded = gateway.sync.put(f"/sync/v1/media/{digest}", content=by_digest[digest])
        assert uploaded.status_code in (200, 201), uploaded.text
    return manifest["item"]


def actions(gateway, step: str) -> list[dict]:
    return [
        record
        for record in gateway.outbox()
        if record["kind"] == "action_request" and record["action_request"]["params"]["step"] == step
    ]


def summary(gateway) -> dict:
    return {
        "expires_at": gateway.clock.stamp(minutes=30),
        "action": "continue_clip",
        "revision": REVISION,
        "title": "Continue the clip",
        "lines": ["One take from the last frame"],
        "job_count": 1,
        "queue_position": "next",
        "warnings": [],
    }


def test_a_video_is_continued_with_words_after_the_pcs_summary(phone, gateway) -> None:
    clip = publish_clip(gateway)
    pair(phone, gateway, scopes=("review", "queue"))
    phone.get_by_role("button", name="Review all (1)").click()

    expect(phone.get_by_role("button", name="Fix face", exact=True)).to_have_count(0)
    phone.get_by_role("button", name="Continue clip", exact=True).click()
    phone.get_by_role("textbox", name="Continue clip").fill("she sits down")
    phone.get_by_role("button", name="Ask the PC", exact=True).click()

    (prepared,) = wait_for(lambda: actions(gateway, "prepare"), what="the prepare request")
    assert prepared["action_request"] == {
        "action": "continue_clip",
        "params": {"step": "prepare", "text": "she sits down"},
    }
    assert prepared["target"] == clip
    gateway.acknowledge(prepared["record_id"], receipt={"action_summary": summary(gateway)})
    expect(phone.get_by_text("One take from the last frame")).to_be_visible()

    phone.get_by_role("button", name="Queue", exact=True).click()
    (confirmed,) = wait_for(lambda: actions(gateway, "confirm"), what="the confirm request")
    assert confirmed["action_request"]["params"]["prepared_record"] == prepared["record_id"]
    gateway.acknowledge(
        confirmed["record_id"], receipt={"job_ids": ["b" * 32], "action_summary": summary(gateway)}
    )
    expect(phone.get_by_role("heading", name="Continue clip: queued")).to_be_visible()


def test_an_image_is_not_offered_continue_clip(phone, gateway) -> None:
    gateway.publish("one")
    pair(phone, gateway, scopes=("review", "queue"))
    phone.get_by_role("button", name="Review all (1)").click()

    expect(phone.get_by_role("button", name="Fix face", exact=True)).to_be_visible()
    expect(phone.get_by_role("button", name="Continue clip", exact=True)).to_have_count(0)
