from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from src.controller.app_controller import AppController
from src.controller.content_visibility_resolver import (
    CONTENT_RATING_NSFW,
    CONTENT_RATING_UNKNOWN,
    REDACTED_TEXT,
    ContentVisibilityResolver,
)
from src.controller.job_history_service import JobHistoryService
from src.gui.app_state_v2 import AppStateV2
from src.gui.prompt_workspace_state import PromptWorkspaceState
from src.gui.widgets.lora_picker_panel import LoRAPickerPanel
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem
from src.learning.discovered_review_store import DiscoveredReviewStore
from src.learning.output_scanner import OutputScanner
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.job_queue import JobQueue
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class NoopPipelineRunner:
    def run(self, config, cancel_token, log_fn=None):
        return None


class DummyWidget:
    def configure(self, **_kwargs):
        return None


class DummyButton(DummyWidget):
    def __init__(self):
        self.command = None

    def configure(self, **kwargs):
        self.command = kwargs.get("command")


class DummyListbox:
    def __init__(self):
        self.items: list[str] = []

    def bind(self, *_args, **_kwargs):
        return None

    def delete(self, *_args):
        self.items = []

    def insert(self, _index, value):
        self.items.append(value)

    def curselection(self):
        return ()

    def get(self, index):
        return self.items[index]


class DummyCombobox(DummyWidget):
    def bind(self, *_args, **_kwargs):
        return None

    def get(self):
        return ""


class DummyText:
    def __init__(self):
        self.lines: list[str] = []

    def insert(self, _end, text: str):
        self.lines.append(text)

    def see(self, _end):
        return None


class DummyLeftZone:
    def __init__(self):
        self.load_pack_button = DummyButton()
        self.edit_pack_button = DummyButton()
        self.packs_list = DummyListbox()
        self.preset_combo = DummyCombobox()


class DummyHeaderZone:
    def __init__(self):
        self.run_button = DummyButton()
        self.stop_button = DummyButton()
        self.preview_button = DummyButton()
        self.settings_button = DummyButton()
        self.help_button = DummyButton()


class DummyBottomZone:
    def __init__(self):
        self.status_label = DummyWidget()
        self.api_status_label = DummyWidget()
        self.log_text = DummyText()


class DummyPromptTab:
    def __init__(self):
        self.config = {"enabled": True, "dedupe_enabled": True}

    def get_prompt_optimizer_config(self):
        return dict(self.config)

    def apply_prompt_optimizer_config(self, config):
        self.config = dict(config or {})


class DummyWindow:
    def __init__(self):
        self.header_zone = DummyHeaderZone()
        self.left_zone = DummyLeftZone()
        self.bottom_zone = DummyBottomZone()
        self.prompt_tab = DummyPromptTab()
        self.updated_packs: list[list[str]] = []
        self.connected_controller = None
        self.app_state = AppStateV2()

    def after(self, _delay, callback):
        callback()

    def update_pack_list(self, names: list[str]):
        self.updated_packs.append(names)

    def connect_controller(self, controller):
        self.connected_controller = controller


def _make_job_record(job_id: str, prompt: str) -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=1234,
        created_ts=1000.0,
        positive_prompt=prompt,
        negative_prompt="",
        steps=20,
        cfg_scale=7.0,
        width=832,
        height=1216,
        sampler_name="Euler",
        scheduler="normal",
        base_model="StableNew-XL",
    )


def test_resolver_flags_explicit_prompt_terms_and_redacts_in_sfw() -> None:
    resolver = ContentVisibilityResolver("sfw")
    subject = {"prompt": "cinematic nude portrait"}

    classification = resolver.classify_item(subject)
    decision = resolver.decide(subject, allow_redacted=True)

    assert classification.rating == CONTENT_RATING_NSFW
    assert "nude" in classification.matched_terms
    assert decision.visible is True
    assert decision.redacted is True
    assert resolver.redact_text(subject["prompt"], item=subject) == REDACTED_TEXT


def test_resolver_preserves_safe_payload_without_heuristic_hits() -> None:
    resolver = ContentVisibilityResolver("sfw")

    classification = resolver.classify_item(
        {"content_visibility": {"rating": "sfw", "safe_for_work": True}}
    )

    assert classification.rating == "sfw"
    assert classification.safe_for_work is True


def test_job_history_service_filters_lists_and_redacts_detail_in_sfw(tmp_path: Path) -> None:
    store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    queue = JobQueue(history_store=store)
    service = JobHistoryService(queue, store)

    safe_record = _make_job_record("safe-job", "heroic landscape")
    nsfw_record = _make_job_record("nsfw-job", "studio nude portrait")
    safe_view = safe_record.to_job_view(status="queued", created_at="2026-03-27T00:00:00Z")
    nsfw_view = nsfw_record.to_job_view(status="queued", created_at="2026-03-27T00:00:00Z")

    filtered = service._filter_job_views([safe_view, nsfw_view], "sfw")
    assert [job.job_id for job in filtered] == ["safe-job"]

    detail = service._apply_job_view_visibility(nsfw_view, "sfw", allow_redacted=True)
    assert detail is not None
    assert detail.prompt == REDACTED_TEXT
    assert detail.positive_preview == REDACTED_TEXT


def test_prompt_workspace_state_exposes_visibility_aware_text() -> None:
    workspace = PromptWorkspaceState()
    workspace.new_pack("Test Pack")
    workspace.set_slot_text(0, "soft nude study")

    payload = workspace.get_current_content_visibility_payload()

    assert payload["rating"] == CONTENT_RATING_NSFW
    assert workspace.get_current_prompt_text_for_mode("sfw") == REDACTED_TEXT
    assert workspace.get_current_prompt_text_for_mode("nsfw") == "soft nude study"


def test_app_controller_load_packs_filters_nsfw_packs_in_sfw_mode(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "alpha.txt").write_text("sunlit mountains\n", encoding="utf-8")
    (packs_dir / "beta.txt").write_text("nude portrait\n", encoding="utf-8")

    window = DummyWindow()
    window.app_state.set_content_visibility_mode("sfw")
    controller = AppController(
        window,
        threaded=False,
        packs_dir=packs_dir,
        pipeline_runner=NoopPipelineRunner(),
        job_service=make_stubbed_job_service(),
    )

    controller.load_packs()

    assert [pack.name for pack in controller.packs] == ["alpha"]
    assert window.updated_packs[-1] == ["alpha"]


def test_app_controller_reloads_visible_packs_when_mode_changes(tmp_path: Path) -> None:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "alpha.txt").write_text("sunlit mountains\n", encoding="utf-8")
    (packs_dir / "beta.txt").write_text("nude portrait\n", encoding="utf-8")

    window = DummyWindow()
    controller = AppController(
        window,
        threaded=False,
        packs_dir=packs_dir,
        pipeline_runner=NoopPipelineRunner(),
        job_service=make_stubbed_job_service(),
    )
    controller.load_packs()
    assert window.updated_packs[-1] == ["alpha", "beta"]

    window.app_state.set_content_visibility_mode("sfw")

    assert [pack.name for pack in controller.packs] == ["alpha"]
    assert window.updated_packs[-1] == ["alpha"]


def test_output_scanner_stamps_visibility_payload_from_manifest(tmp_path: Path) -> None:
    output_root = tmp_path / "output" / "job-1"
    manifests = output_root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (output_root / "sample.png").write_bytes(b"not-a-real-png")
    (manifests / "sample.json").write_text(
        '{"prompt":"nude portrait","generation":{"sampler_name":"Euler","steps":20,"cfg_scale":7.0,"width":832,"height":1216}}',
        encoding="utf-8",
    )

    scanner = OutputScanner(tmp_path / "output")
    records = scanner.scan_full()

    assert len(records) == 1
    assert records[0].extra_fields["content_visibility"]["rating"] == CONTENT_RATING_NSFW


def test_discovered_review_store_normalizes_invalid_visibility_payload(tmp_path: Path) -> None:
    store = DiscoveredReviewStore(tmp_path / "learning")
    experiment = DiscoveredReviewExperiment(
        group_id="disc-1",
        display_name="Test",
        stage="txt2img",
        prompt_hash="abc123",
        items=[
            DiscoveredReviewItem(
                item_id="item-1",
                artifact_path="artifact.png",
                extra_fields={"content_visibility": {"rating": "not-valid"}},
            )
        ],
    )

    store.save_group(experiment)
    loaded = store.load_group("disc-1")

    assert loaded is not None
    assert loaded.items[0].extra_fields["content_visibility"]["rating"] == CONTENT_RATING_UNKNOWN


@pytest.mark.gui
def test_lora_picker_filters_nsfw_resources_in_sfw_mode(monkeypatch, tk_root) -> None:
    class _Resource:
        def __init__(self, description: str) -> None:
            self.keywords: list[str] = []
            self.description = description

    class _Scanner:
        def scan_loras(self, force_rescan: bool = False):
            return {}

        def get_lora_names(self) -> list[str]:
            return ["PortraitHelper", "NSFWPosePack"]

        def get_lora_info(self, name: str):
            if name == "NSFWPosePack":
                return _Resource("nude anatomy helper")
            return _Resource("portrait lighting helper")

    monkeypatch.setattr("src.gui.widgets.lora_picker_panel.get_lora_scanner", lambda *_args, **_kwargs: _Scanner())

    parent = tk.Frame(tk_root)
    parent.app_state = AppStateV2()
    parent.app_state.set_content_visibility_mode("sfw")
    panel = LoRAPickerPanel(parent)
    try:
        panel._scan_loras()
        assert list(panel.lora_name_combo["values"]) == ["PortraitHelper"]
    finally:
        panel.destroy()
        parent.destroy()
