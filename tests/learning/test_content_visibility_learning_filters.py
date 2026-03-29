from __future__ import annotations

import json
from pathlib import Path

from src.controller.content_visibility_resolver import (
    CONTENT_RATING_NSFW,
    CONTENT_RATING_SFW,
    CONTENT_RATING_UNKNOWN,
)
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.output_scanner import OutputScanner


def _write_manifest_run(root: Path, stem: str, payload: dict[str, object]) -> None:
    run_dir = root / stem
    manifests_dir = run_dir / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{stem}.png").write_bytes(b"png")
    (manifests_dir / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_output_scanner_normalizes_sfw_nsfw_and_unknown_visibility_payloads(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    _write_manifest_run(
        output_root,
        "safe",
        {
            "prompt": "sunlit meadow",
            "content_visibility": {"rating": "sfw", "safe_for_work": True},
            "generation": {"sampler_name": "Euler", "steps": 20, "cfg_scale": 7.0, "width": 832, "height": 1216},
        },
    )
    _write_manifest_run(
        output_root,
        "legacy-explicit",
        {
            "prompt": "portrait study",
            "content_rating": "explicit",
            "safe_for_work": False,
            "generation": {"sampler_name": "Euler", "steps": 20, "cfg_scale": 7.0, "width": 832, "height": 1216},
        },
    )
    _write_manifest_run(
        output_root,
        "unknown",
        {
            "prompt": "portrait study",
            "content_visibility": {"rating": "not-valid"},
            "generation": {"sampler_name": "Euler", "steps": 20, "cfg_scale": 7.0, "width": 832, "height": 1216},
        },
    )

    records = OutputScanner(output_root).scan_full()
    ratings = {
        Path(record.artifact_path).stem: record.extra_fields["content_visibility"]["rating"]
        for record in records
    }

    assert ratings["safe"] == CONTENT_RATING_SFW
    assert ratings["legacy-explicit"] == CONTENT_RATING_NSFW
    assert ratings["unknown"] == CONTENT_RATING_UNKNOWN


def test_discovered_review_store_normalizes_missing_and_invalid_visibility_payloads(
    tmp_path: Path,
) -> None:
    store = DiscoveredReviewStore(tmp_path / "learning")
    experiment = DiscoveredReviewExperiment(
        group_id="disc-visibility",
        display_name="Visibility",
        stage="txt2img",
        prompt_hash="abc123",
        items=[
            DiscoveredReviewItem(item_id="item-safe", artifact_path="safe.png", extra_fields={}),
            DiscoveredReviewItem(
                item_id="item-invalid",
                artifact_path="invalid.png",
                extra_fields={"content_visibility": {"rating": "not-valid"}},
            ),
            DiscoveredReviewItem(
                item_id="item-explicit",
                artifact_path="explicit.png",
                extra_fields={"content_visibility": {"rating": "nsfw", "safe_for_work": False}},
            ),
        ],
    )

    store.save_group(experiment)
    loaded = store.load_group("disc-visibility")

    assert loaded is not None
    ratings = {
        item.item_id: item.extra_fields["content_visibility"]["rating"]
        for item in loaded.items
    }
    assert ratings == {
        "item-safe": CONTENT_RATING_UNKNOWN,
        "item-invalid": CONTENT_RATING_UNKNOWN,
        "item-explicit": CONTENT_RATING_NSFW,
    }
