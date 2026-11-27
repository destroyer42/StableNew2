"""Synthetic rating payloads (RG-170). No real eval content: names and text here are placeholders."""

from __future__ import annotations

import uuid
from typing import Any

from tests.review_gateway_service.conftest import SCHEMA_VERSION, Rig, sha

NOW = "2026-11-25T12:00:00Z"
CLIP_A = b"clip-a" * 8
CLIP_B = b"clip-b" * 8
REFERENCE = b"reference" * 4


def media(data: bytes, content_type: str = "video/mp4") -> dict[str, Any]:
    return {"sha256": sha(data), "bytes": len(data), "content_type": content_type}


def pair_task(task_id: str = "demo-pairs", **changes: Any) -> dict[str, Any]:
    task = {
        "schema_version": SCHEMA_VERSION,
        "type": "rating_task",
        "task_id": task_id,
        "title": "Demo A/B",
        "kind": "pairs",
        "state": "open",
        "instructions": "Play both, then choose.",
        "created_at": NOW,
        "criteria": [
            {
                "criterion_id": "motion",
                "label": "Better motion",
                "type": "choice",
                "required": True,
            },
            {"criterion_id": "stable", "label": "More stable", "type": "choice", "required": True},
        ],
        "items": [
            {
                "item_id": item_id,
                "context": "a placeholder request",
                "reference": media(REFERENCE, "image/webp"),
                "clips": [
                    {"clip_id": "A", "label": "A", "media": media(CLIP_A)},
                    {"clip_id": "B", "label": "B", "media": media(CLIP_B)},
                ],
            }
            for item_id in ("p01", "p02")
        ],
    }
    task.update(changes)
    return task


def score_task(task_id: str = "demo-scores") -> dict[str, Any]:
    task = pair_task(task_id, kind="scores", title="Demo scores")
    task["criteria"] = [
        {
            "criterion_id": "fidelity",
            "label": "Looks like the source",
            "type": "score",
            "required": True,
        },
        {
            "criterion_id": "action",
            "label": "Did the action happen?",
            "type": "enum",
            "required": True,
            "options": [
                {"value": "achieved", "label": "Yes"},
                {"value": "not_achieved", "label": "No"},
            ],
        },
        {"criterion_id": "overall", "label": "Overall", "type": "score", "required": False},
    ]
    task["items"] = task["items"][:1]
    return task


def ranking_task(task_id: str = "demo-ranking") -> dict[str, Any]:
    task = pair_task(task_id, kind="ranking", title="Demo ranking")
    task["criteria"] = [
        {"criterion_id": "motion", "label": "Motion", "type": "rank", "required": True}
    ]
    task["items"] = task["items"][:1]
    return task


def choice_task(task_id: str = "demo-choice") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "rating_task",
        "task_id": task_id,
        "title": "Which step count next?",
        "kind": "choice",
        "state": "open",
        "created_at": NOW,
        "criteria": [
            {
                "criterion_id": "pick",
                "label": "Pick one",
                "type": "enum",
                "required": True,
                "options": [
                    {"value": "hy8", "label": "8 steps", "recommended": True},
                    {"value": "hy12", "label": "12 steps"},
                ],
            }
        ],
        "items": [{"item_id": "q1", "context": "Which should run?"}],
    }


def submission_page() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "rating_submission_page",
        "submissions": [
            {
                "submission_id": str(uuid.uuid4()),
                "task_id": "demo-pairs",
                "device_id": "device-0001",
                "created_at": NOW,
                "answers": [
                    {"item_id": "p01", "clip_id": "", "values": {"motion": "A"}, "notes": ""}
                ],
            }
        ],
    }


def acknowledgement(
    submission_id: str | None = None, outcome: str = "applied", **fields: Any
) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "rating_acknowledgement",
        "submission_id": submission_id or str(uuid.uuid4()),
        "outcome": outcome,
        "acknowledged_at": NOW,
    }
    payload.update(fields)
    return payload


BLOBS = {sha(data): data for data in (CLIP_A, CLIP_B, REFERENCE)}


def publish(rig: Rig, task: dict[str, Any]) -> dict[str, Any]:
    """Send a task and the bytes the gateway asks for; returns the final reply."""

    response = rig.sync.post("/sync/v1/rating-tasks", json=task)
    assert response.status_code == 200, response.text
    for digest in response.json()["missing"]:
        uploaded = rig.sync.put(f"/sync/v1/rating-media/{digest}", content=BLOBS[digest])
        assert uploaded.status_code in (200, 201), uploaded.text
    return rig.sync.post("/sync/v1/rating-tasks", json=task).json()
