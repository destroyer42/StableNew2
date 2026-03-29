from __future__ import annotations

import sys
import types
from pathlib import Path

if "src.state.output_routing" not in sys.modules:
    stub = types.ModuleType("src.state.output_routing")
    stub.OUTPUT_ROUTE_AUTO = "auto"
    stub.OUTPUT_ROUTE_PIPELINE = "pipeline"
    stub.OUTPUT_ROUTE_TESTING = "testing"
    stub.OUTPUT_ROUTE_LEARNING = "learning"
    stub.OUTPUT_ROUTE_MOVIE_CLIPS = "movie_clips"
    stub.OUTPUT_ROUTE_REPROCESS = "reprocess"
    stub.OUTPUT_ROUTE_SVD = "svd"
    stub.classify_njr_output_route = lambda *_args, **_kwargs: "images"
    stub.get_output_route_root = lambda *_args, **_kwargs: "outputs"
    stub.get_output_root = lambda *_args, **_kwargs: "outputs"
    stub.iter_output_run_dirs = lambda *_args, **_kwargs: []
    sys.modules["src.state.output_routing"] = stub

from src.gui.app_state_v2 import AppStateV2
from src.gui.content_visibility import (
    ContentVisibilityMode,
    ContentVisibilitySettings,
    normalize_content_visibility_mode,
)
from src.services.ui_state_store import UIStateStore


def test_normalize_content_visibility_mode_defaults_to_nsfw_for_unknown_values() -> None:
    assert normalize_content_visibility_mode("SFW") == ContentVisibilityMode.SFW
    assert normalize_content_visibility_mode("nsfw") == ContentVisibilityMode.NSFW
    assert normalize_content_visibility_mode("unknown") == ContentVisibilityMode.NSFW


def test_app_state_content_visibility_notifies_subscribers() -> None:
    state = AppStateV2()
    events: list[str] = []

    state.subscribe("content_visibility_mode", lambda: events.append(state.content_visibility_mode))

    normalized = state.set_content_visibility_mode("sfw")

    assert normalized == ContentVisibilityMode.SFW
    assert state.content_visibility_mode == "sfw"
    assert events == ["sfw"]


def test_ui_state_store_normalizes_invalid_content_visibility_mode(tmp_path: Path) -> None:
    store = UIStateStore(tmp_path / "ui_state.json")
    store.save_state(
        {
            "window": {"geometry": "1200x800+100+50", "state": "normal"},
            "tabs": {"selected_index": 0},
            "content_visibility": {"mode": "invalid"},
        }
    )
    loaded = store.load_state()
    assert loaded is not None
    assert loaded["content_visibility"] == {"mode": "nsfw"}


def test_content_visibility_settings_payload_roundtrip() -> None:
    settings = ContentVisibilitySettings(ContentVisibilityMode.SFW)
    restored = ContentVisibilitySettings.from_payload(settings.to_payload())
    assert restored.mode == ContentVisibilityMode.SFW
