"""RG-170: rating tasks on the gateway. A projection and an answer queue; the PC stays the authority."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from review_gateway.contract import Contract, ContractError

from tests.review_gateway_service import rating_samples as samples
from tests.review_gateway_service.conftest import SCHEMA_PATH, SCHEMA_VERSION, Rig

KEY = "k" * 16


def paired(rig: Rig) -> str:
    return rig.pair()


def answer(
    rig: Rig, task_id: str, item_id: str, values: dict, *, clip_id: str = "", notes: str = ""
):
    return rig.phone.post(
        f"/api/rating/tasks/{task_id}/answers",
        json={"item_id": item_id, "clip_id": clip_id, "values": values, "notes": notes},
    )


def listed(rig: Rig) -> dict:
    response = rig.phone.get("/api/rating/tasks")
    assert response.status_code == 200, response.text
    return response.json()


def detail(rig: Rig, task_id: str) -> dict:
    response = rig.phone.get(f"/api/rating/tasks/{task_id}")
    assert response.status_code == 200, response.text
    return response.json()


def finish_pairs(rig: Rig, task_id: str = "demo-pairs") -> None:
    for item_id in ("p01", "p02"):
        assert answer(rig, task_id, item_id, {"motion": "A", "stable": "tie"}).status_code == 200


def submit(rig: Rig, task_id: str = "demo-pairs", key: str = KEY):
    return rig.phone.post(f"/api/rating/tasks/{task_id}/submit", json={"idempotency_key": key})


def pending(rig: Rig) -> list[dict]:
    response = rig.sync.get("/sync/v1/rating-submissions")
    assert response.status_code == 200, response.text
    return response.json()["submissions"]


# --- contract -------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def contract() -> Contract:
    return Contract(SCHEMA_PATH)


@pytest.mark.parametrize(
    "name, payload",
    [
        ("rating_task", samples.pair_task()),
        ("rating_task", samples.score_task()),
        ("rating_task", samples.choice_task()),
        ("rating_submission_page", samples.submission_page()),
        ("rating_acknowledgement", samples.acknowledgement()),
        (
            "rating_acknowledgement",
            samples.acknowledgement(outcome="refused", reason_code="already_rated"),
        ),
    ],
)
def test_rating_payloads_are_part_of_the_sync_contract(contract: Contract, name, payload) -> None:
    import json

    contract.validate(name, payload)
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(payload)


@pytest.mark.parametrize(
    "name, payload",
    [
        ("rating_task", samples.pair_task(arm="a14b")),
        ("rating_task", samples.pair_task(task_id="../x")),
        ("rating_task", samples.pair_task(items=[])),
        ("rating_acknowledgement", samples.acknowledgement(outcome="refused")),
    ],
)
def test_malformed_rating_payloads_are_refused(contract: Contract, name, payload) -> None:
    with pytest.raises(ContractError):
        contract.validate(name, payload)


# --- publishing -----------------------------------------------------------------------------------------------------


def test_health_lists_rating_tasks(rig: Rig) -> None:
    assert "rating_tasks" in rig.sync.get("/sync/v1/health").json()["features"]


def test_a_task_is_shown_only_once_all_its_media_arrived(rig: Rig) -> None:
    paired(rig)
    first = rig.sync.post("/sync/v1/rating-tasks", json=samples.pair_task()).json()
    assert first["status"] == "incomplete" and len(first["missing"]) == 3
    assert listed(rig)["tasks"] == []

    assert samples.publish(rig, samples.pair_task())["status"] == "ready"
    [task] = listed(rig)["tasks"]
    assert (task["task_id"], task["state"], task["answered"], task["total"]) == (
        "demo-pairs",
        "open",
        0,
        2,
    )
    assert listed(rig)["waiting"] == 1


def test_media_must_be_declared_and_match_its_digest(rig: Rig) -> None:
    assert rig.sync.put(f"/sync/v1/rating-media/{'a' * 64}", content=b"x").status_code == 409
    task = samples.pair_task()
    rig.sync.post("/sync/v1/rating-tasks", json=task)
    digest = task["items"][0]["clips"][0]["media"]["sha256"]
    assert rig.sync.put(f"/sync/v1/rating-media/{digest}", content=b"z" * 48).status_code == 422
    assert rig.sync.head(f"/sync/v1/rating-media/{digest}").status_code == 404


def test_rating_media_needs_an_enrolled_phone_and_belongs_to_its_task(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    digest = samples.pair_task()["items"][0]["clips"][0]["media"]["sha256"]
    url = f"/rating-media/demo-pairs/{digest}"
    assert rig.new_phone().get(url).status_code == 401
    paired(rig)
    response = rig.phone.get(url)
    assert response.content == samples.CLIP_A
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"].startswith("private")
    assert rig.phone.get(f"/rating-media/other-task/{digest}").status_code == 404


def test_the_sync_routes_are_not_on_the_phone_app_and_need_the_secret(rig: Rig) -> None:
    assert rig.phone.get("/sync/v1/rating-submissions").status_code == 404
    assert rig.client(rig.gateway.sync_app()).get("/sync/v1/rating-submissions").status_code == 401
    assert rig.new_phone().get("/api/rating/tasks").status_code == 401


def test_a_published_tasks_shape_cannot_change(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    assert answer(rig, "demo-pairs", "p01", {"motion": "A"}).status_code == 200

    retitled = rig.sync.post("/sync/v1/rating-tasks", json=samples.pair_task(title="New title"))
    assert retitled.status_code == 200
    assert detail(rig, "demo-pairs")["title"] == "New title"

    reshaped = samples.pair_task()
    reshaped["items"] = reshaped["items"][:1]
    assert rig.sync.post("/sync/v1/rating-tasks", json=reshaped).status_code == 409


def test_a_choice_task_without_media_is_ready_at_once(rig: Rig) -> None:
    paired(rig)
    reply = rig.sync.post("/sync/v1/rating-tasks", json=samples.choice_task()).json()
    assert reply == {"status": "ready", "missing": []}
    assert listed(rig)["waiting"] == 1


# --- answering ------------------------------------------------------------------------------------------------------


def test_progress_is_saved_per_item_and_a_sitting_resumes(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    assert answer(rig, "demo-pairs", "p01", {"motion": "A"}, notes="close").status_code == 200
    [task] = listed(rig)["tasks"]
    assert (task["state"], task["answered"]) == ("partly", 0)  # one of two required criteria
    assert answer(rig, "demo-pairs", "p01", {"motion": "B", "stable": "tie"}).status_code == 200

    shown = detail(rig, "demo-pairs")
    assert shown["answers"] == [
        {"item_id": "p01", "clip_id": "", "values": {"motion": "B", "stable": "tie"}, "notes": ""}
    ]
    assert (shown["state"], shown["answered"], shown["total"]) == ("partly", 1, 2)
    assert shown["items"][0]["clips"][0]["media"]["sha256"]


@pytest.mark.parametrize(
    "item_id, clip_id, values",
    [
        ("p09", "", {"motion": "A"}),
        ("p01", "A", {"motion": "A"}),  # pairs are judged per item
        ("p01", "", {"motion": "C"}),
        ("p01", "", {"colour": "A"}),
        ("p01", "", {"motion": 1}),
    ],
)
def test_an_answer_outside_the_task_is_refused(rig: Rig, item_id, clip_id, values) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    assert answer(rig, "demo-pairs", item_id, values, clip_id=clip_id).status_code == 422


def test_scores_are_per_clip_and_ranks_are_a_full_ordering(rig: Rig) -> None:
    samples.publish(rig, samples.score_task())
    samples.publish(rig, samples.ranking_task())
    paired(rig)

    assert answer(rig, "demo-scores", "p01", {"fidelity": "5"}).status_code == 422  # no clip
    assert answer(rig, "demo-scores", "p01", {"fidelity": "6"}, clip_id="A").status_code == 422
    assert answer(rig, "demo-scores", "p01", {"action": "maybe"}, clip_id="A").status_code == 422
    for clip in ("A", "B"):
        values = {"fidelity": "4", "action": "achieved"}
        assert answer(rig, "demo-scores", "p01", values, clip_id=clip).status_code == 200
    assert detail(rig, "demo-scores")["answered"] == 2  # the optional "overall" is not needed

    for refused in ("A", "A>A", "A>B>C", "B<A"):
        assert answer(rig, "demo-ranking", "p01", {"motion": refused}).status_code == 422
    for accepted in ("B>A", "A=B", "tie"):
        assert answer(rig, "demo-ranking", "p01", {"motion": accepted}).status_code == 200


def test_submit_needs_every_required_answer(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    answer(rig, "demo-pairs", "p01", {"motion": "A", "stable": "A"})
    response = submit(rig)
    assert response.status_code == 422 and response.json()["error"] == "incomplete"
    assert pending(rig) == []


def test_a_submission_reaches_the_pc_once_and_is_final(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    device = paired(rig)
    finish_pairs(rig)

    first = submit(rig).json()
    assert first["state"] == "submitted"
    assert submit(rig).json() == first  # a resent request is the same submission
    assert submit(rig, key="z" * 16).status_code == 409
    assert answer(rig, "demo-pairs", "p01", {"motion": "B"}).status_code == 409

    [sent] = pending(rig)
    assert (sent["submission_id"], sent["task_id"], sent["device_id"]) == (
        first["submission_id"],
        "demo-pairs",
        device,
    )
    assert [entry["item_id"] for entry in sent["answers"]] == ["p01", "p02"]
    Contract(SCHEMA_PATH).validate(
        "rating_submission_page", rig.sync.get("/sync/v1/rating-submissions").json()
    )
    assert listed(rig)["waiting"] == 0


def test_the_pc_answer_closes_the_task_and_carries_the_reveal(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    finish_pairs(rig)
    submission_id = submit(rig).json()["submission_id"]
    assert "reveal" not in detail(rig, "demo-pairs")

    table = {
        "title": "Wins per arm",
        "columns": ["Criterion", "x", "y"],
        "rows": [["motion", "1", "1"]],
    }
    payload = samples.acknowledgement(submission_id, reveal=[table])
    assert rig.sync.post("/sync/v1/rating-acknowledgements", json=payload).json() == {
        "status": "recorded"
    }
    assert rig.sync.post("/sync/v1/rating-acknowledgements", json=payload).json() == {
        "status": "already_acknowledged"
    }

    shown = detail(rig, "demo-pairs")
    assert shown["state"] == "done" and shown["reveal"] == [table]
    assert pending(rig) == []
    # Publishing the task again does not reopen it.
    samples.publish(rig, samples.pair_task())
    assert detail(rig, "demo-pairs")["state"] == "done"


def test_a_refused_submission_reopens_the_task_with_its_answers(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    finish_pairs(rig)
    submission_id = submit(rig).json()["submission_id"]
    rig.sync.post(
        "/sync/v1/rating-acknowledgements",
        json=samples.acknowledgement(submission_id, "refused", reason_code="already_rated"),
    )

    shown = detail(rig, "demo-pairs")
    assert (shown["state"], shown["reason_code"]) == ("refused", "already_rated")
    assert shown["answered"] == 2
    assert answer(rig, "demo-pairs", "p01", {"motion": "B", "stable": "B"}).status_code == 200
    assert submit(rig, key="z" * 16).json()["state"] == "submitted"


def test_an_unknown_submission_cannot_be_acknowledged(rig: Rig) -> None:
    response = rig.sync.post("/sync/v1/rating-acknowledgements", json=samples.acknowledgement())
    assert response.status_code == 404


def test_a_revoked_phone_can_neither_read_nor_submit(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    device = paired(rig)
    finish_pairs(rig)
    rig.gateway.store.revoke_device(device)
    assert rig.phone.get("/api/rating/tasks").status_code == 401
    assert submit(rig).status_code == 401


def test_withdrawn_tasks_disappear_and_a_desk_rating_shows_done(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    samples.publish(rig, samples.pair_task("demo-desk"))
    paired(rig)
    rig.sync.post("/sync/v1/rating-tasks", json=samples.pair_task(state="withdrawn"))
    rig.sync.post(
        "/sync/v1/rating-tasks",
        json=samples.pair_task("demo-desk", state="done", note="Rated on the PC."),
    )
    [task] = listed(rig)["tasks"]
    assert (task["task_id"], task["state"], task["note"]) == (
        "demo-desk",
        "done",
        "Rated on the PC.",
    )
    assert answer(rig, "demo-desk", "p01", {"motion": "A"}).status_code == 409


# --- retention ------------------------------------------------------------------------------------------------------


def blob_files(rig: Rig) -> list[Path]:
    return list((rig.settings.media_dir / "rating" / "blobs").glob("*/*"))


def test_open_tasks_survive_retention_and_finished_ones_are_purged(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    paired(rig)
    finish_pairs(rig)
    submission_id = submit(rig).json()["submission_id"]

    rig.clock.advance(days=40)
    rig.gateway.retention()
    assert len(blob_files(rig)) == 3  # submitted and unanswered: nothing goes

    rig.sync.post("/sync/v1/rating-acknowledgements", json=samples.acknowledgement(submission_id))
    rig.clock.advance(days=13)
    rig.gateway.retention()
    assert listed(rig)["tasks"]
    rig.clock.advance(days=2)
    rig.gateway.retention()
    assert listed(rig)["tasks"] == []
    assert blob_files(rig) == []


def test_review_retention_does_not_touch_rating_media(rig: Rig) -> None:
    samples.publish(rig, samples.pair_task())
    rig.clock.advance(days=3)
    rig.gateway.store.retention()
    assert len(blob_files(rig)) == 3


# --- the phone page -------------------------------------------------------------------------------------------------


def test_the_rating_page_is_served_and_never_writes_markup(rig: Rig) -> None:
    index = rig.phone.get("/").text
    assert re.search(r'src="/static/rating\.js"[\s\S]*src="/static/app\.js"', index)
    for path, kind in (
        ("/static/rating.js", "text/javascript"),
        ("/static/rating.css", "text/css"),
    ):
        response = rig.phone.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith(kind)
    script = rig.phone.get("/static/rating.js").text
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(", script)
    assert SCHEMA_VERSION not in script
