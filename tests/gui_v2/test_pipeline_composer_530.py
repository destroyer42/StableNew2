"""PR-GUI-UX-530: task-oriented Pipeline composer.

The grouping and collapsing is presentation only. These tests assert real stage flags and stored values, not
widget existence, so a hidden stage can never silently change the job that would be compiled.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.reprocess_panel_v2 import ReprocessPanelV2
from src.gui.view_contracts import pipeline_composer_contract as contract
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame

STAGE_CHAIN = ["txt2img", "img2img", "adetailer", "upscale"]


class _Controller:
    def __init__(self) -> None:
        self.stage_toggled_calls: list[tuple[str, bool]] = []

    def list_models(self) -> list[str]:
        return []

    def list_vaes(self) -> list[str]:
        return []

    def list_upscalers(self) -> list[str]:
        return []

    def get_available_samplers(self) -> list[str]:
        return []

    def get_available_schedulers(self) -> list[str]:
        return []

    def on_model_selected(self, *_a: object) -> None:
        return None

    def on_vae_selected(self, *_a: object) -> None:
        return None

    def get_last_run_config(self) -> dict[str, object]:
        return {}

    def get_current_config(self) -> dict[str, object]:
        return {
            "model": "m",
            "sampler": "Euler",
            "width": 832,
            "height": 832,
            "steps": 20,
            "cfg_scale": 7.5,
        }

    def on_stage_toggled(self, stage: str, enabled: bool) -> None:
        self.stage_toggled_calls.append((stage, enabled))

    def on_adetailer_config_changed(self, *_a: object) -> None:
        return None

    def get_lora_runtime_settings(self) -> list[dict[str, object]]:
        return []

    def update_lora_runtime_strength(self, *_a: object, **_k: object) -> None:
        return None

    def update_lora_runtime_enabled(self, *_a: object, **_k: object) -> None:
        return None


@pytest.fixture
def tab(tk_root: tk.Tk) -> PipelineTabFrame:
    controller = _Controller()
    frame = PipelineTabFrame(
        tk_root,
        app_state=AppStateV2(),
        app_controller=controller,
        pipeline_controller=controller,
    )
    frame.test_controller = controller  # type: ignore[attr-defined]
    tk_root.update_idletasks()
    return frame


def _enabled(sidebar) -> list[str]:
    return sidebar.get_enabled_stages()


# --- pure contract ------------------------------------------------------------------------------------------


def test_contract_groups_every_canonical_stage() -> None:
    assert contract.stage_group("txt2img") == "generate"
    assert contract.stage_group("adetailer") == "improve"
    assert contract.stage_group("upscale") == "improve"
    assert contract.stage_group("img2img") == "legacy"
    for stage in STAGE_CHAIN:
        assert contract.STAGE_LABELS[stage]
        assert contract.STAGE_HELP[stage]


def test_contract_summaries_are_accurate() -> None:
    assert contract.legacy_stage_status(["txt2img", "adetailer"]) == ("none enabled", False)
    assert contract.legacy_stage_status(["txt2img", "img2img"]) == ("img2img ON", True)
    assert contract.legacy_stage_notice(["txt2img"]) == contract.LEGACY_IMG2IMG_OFF
    assert contract.legacy_stage_notice(["img2img"]) == contract.LEGACY_IMG2IMG_ON
    assert contract.advanced_generation_status(refiner_enabled=False, hires_enabled=False) == (
        "both off",
        False,
    )
    assert contract.advanced_generation_status(refiner_enabled=True, hires_enabled=False) == (
        "Refiner ON",
        True,
    )
    assert contract.advanced_generation_status(refiner_enabled=True, hires_enabled=True) == (
        "Refiner ON, Hires fix ON",
        True,
    )


def test_contract_uses_no_literal_colors_or_enable_wording() -> None:
    source = Path(contract.__file__).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b", source)
    assert not any(label.startswith("Enable ") for label in contract.STAGE_LABELS.values())


# --- A. fresh generation ------------------------------------------------------------------------------------


def test_fresh_create_defaults_to_txt2img_without_img2img(tab: PipelineTabFrame) -> None:
    sidebar = tab.sidebar
    assert sidebar.stage_states["txt2img"].get() is True
    assert sidebar.stage_states["img2img"].get() is False
    assert sidebar.stage_states["upscale"].get() is False
    assert "img2img" not in _enabled(sidebar)
    assert _enabled(sidebar)[0] == "txt2img"


def test_img2img_has_no_normal_create_control_but_ordinary_stages_do(
    tab: PipelineTabFrame, tk_root
) -> None:
    sidebar = tab.sidebar
    body = sidebar.legacy_stage_section.body
    assert set(sidebar.stage_checkbuttons) == set(STAGE_CHAIN)
    for stage in ("txt2img", "adetailer", "upscale"):
        assert str(sidebar.stage_checkbuttons[stage].winfo_parent()) != str(body)
        assert sidebar.stage_checkbuttons[stage].winfo_ismapped()
    legacy = sidebar.stage_checkbuttons["img2img"]
    assert str(legacy.winfo_parent()) == str(body)
    assert not sidebar.legacy_stage_section.is_expanded()
    assert not legacy.winfo_ismapped()
    texts = [cb.cget("text") for cb in sidebar.stage_checkbuttons.values()]
    assert not any(text.startswith("Enable ") for text in texts)


def test_optional_postprocessing_toggles_real_stage_flags_and_invalidates_preview(
    tab: PipelineTabFrame,
) -> None:
    sidebar = tab.sidebar
    changes: list[int] = []
    sidebar._on_change = lambda: changes.append(1)

    sidebar.stage_checkbuttons["upscale"].invoke()
    assert _enabled(sidebar) == ["txt2img", "adetailer", "upscale"]
    assert tab.test_controller.stage_toggled_calls[-1] == ("upscale", True)
    assert changes, "a stage change must ask the existing debounced preview path to rebuild"

    changes.clear()
    sidebar.stage_checkbuttons["adetailer"].invoke()
    assert _enabled(sidebar) == ["txt2img", "upscale"]
    assert changes


# --- B/C. legacy configurations, stage state -----------------------------------------------------------------


def _apply_saved_pipeline_section(tab: PipelineTabFrame, section: dict[str, bool]) -> None:
    """Run the production config->sidebar stage-flag path with a minimal controller stand-in."""

    stand_in = SimpleNamespace(
        _set_sidebar_stage_state=lambda stage, enabled: tab.sidebar.set_stage_state(
            stage, enabled, emit_change=False
        ),
        _refresh_stage_visibility=tab._handle_sidebar_change,
    )
    AppController._apply_pipeline_stage_flags(stand_in, section)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        (
            {
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": False,
                "upscale_enabled": False,
            },
            ["txt2img"],
        ),
        (
            {
                "txt2img_enabled": True,
                "img2img_enabled": True,
                "adetailer_enabled": False,
                "upscale_enabled": False,
            },
            ["txt2img", "img2img"],
        ),
        (
            {
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": True,
                "upscale_enabled": False,
            },
            ["txt2img", "adetailer"],
        ),
        (
            {
                "txt2img_enabled": True,
                "img2img_enabled": False,
                "adetailer_enabled": False,
                "upscale_enabled": True,
            },
            ["txt2img", "upscale"],
        ),
        (
            {
                "txt2img_enabled": True,
                "img2img_enabled": True,
                "adetailer_enabled": True,
                "upscale_enabled": True,
            },
            STAGE_CHAIN,
        ),
    ],
)
def test_saved_configurations_load_exact_stage_chain(
    tab: PipelineTabFrame, tk_root, section: dict[str, bool], expected: list[str]
) -> None:
    _apply_saved_pipeline_section(tab, section)
    tk_root.update_idletasks()
    sidebar = tab.sidebar
    assert _enabled(sidebar) == expected
    legacy_on = "img2img" in expected
    assert sidebar.legacy_stage_section.header_text().endswith("img2img ON") is legacy_on
    # Presentation never decides stages: collapsed or not, the chain is the loaded one.
    assert not sidebar.legacy_stage_section.is_expanded()
    sidebar.legacy_stage_section.set_expanded(True)
    sidebar.legacy_stage_section.set_expanded(False)
    assert _enabled(sidebar) == expected
    # The center column still shows exactly the enabled stage cards, in canonical order.
    cards = tab.stage_cards_panel
    for stage in STAGE_CHAIN:
        assert bool(getattr(cards, f"{stage}_card").winfo_ismapped()) is (stage in expected)


def test_legacy_img2img_stays_enabled_until_explicitly_turned_off(
    tab: PipelineTabFrame, tk_root
) -> None:
    sidebar = tab.sidebar
    sidebar.set_stage_state("img2img", True)
    tk_root.update_idletasks()
    assert "img2img" in _enabled(sidebar)
    assert sidebar.legacy_stage_section.header_text().endswith("img2img ON")
    assert sidebar.legacy_stage_notice_label.cget("text") == contract.LEGACY_IMG2IMG_ON

    # Collapse/expand, a pack-list refresh and a model-target resource update never touch the flag.
    sidebar.legacy_stage_section.set_expanded(True)
    sidebar.legacy_stage_section.set_expanded(False)
    sidebar.refresh_prompt_packs()
    tab.stage_cards_panel.apply_resource_update({"models": ["a", "b"], "vaes": [], "upscalers": []})
    assert sidebar.stage_states["img2img"].get() is True

    # Explicit, authorized action through the legacy section.
    sidebar.legacy_stage_section.set_expanded(True)
    tk_root.update_idletasks()
    sidebar.stage_checkbuttons["img2img"].invoke()
    assert "img2img" not in _enabled(sidebar)
    assert tab.test_controller.stage_toggled_calls[-1] == ("img2img", False)
    assert sidebar.legacy_stage_notice_label.cget("text") == contract.LEGACY_IMG2IMG_OFF


def test_refiner_and_hires_collapsed_by_default_with_accurate_summary(
    tab: PipelineTabFrame,
) -> None:
    card = tab.stage_cards_panel.txt2img_card
    section = card.advanced_generation_section
    assert not section.is_expanded()
    assert section.header_text().endswith("both off")
    assert str(card._refiner_frame.winfo_parent()) == str(section.body)
    assert str(card._hires_frame.winfo_parent()) == str(section.body)

    card.refiner_enabled_var.set(True)
    assert section.header_text().endswith("Refiner ON")
    card.hires_enabled_var.set(True)
    assert section.header_text().endswith("Refiner ON, Hires fix ON")
    card.refiner_enabled_var.set(False)
    assert section.header_text().endswith("Hires fix ON")


def test_collapsing_advanced_sections_keeps_every_value(tab: PipelineTabFrame, tk_root) -> None:
    card = tab.stage_cards_panel.txt2img_card
    section = card.advanced_generation_section
    section.set_expanded(True)
    card.hires_enabled_var.set(True)
    card.hires_factor_var.set(1.75)
    card.hires_denoise_var.set(0.42)
    card.refiner_enabled_var.set(True)
    card.refiner_switch_var.set(65.0)
    before = card.to_stage_local_config_dict()

    section.set_expanded(False)
    tk_root.update_idletasks()
    assert not section.is_expanded()
    assert card.hires_enabled_var.get() is True
    assert card.hires_factor_var.get() == pytest.approx(1.75)
    assert card.refiner_enabled_var.get() is True
    assert card.to_stage_local_config_dict() == before

    section.set_expanded(True)
    assert card.to_stage_local_config_dict() == before


def test_stage_flags_and_values_survive_navigating_away_and_back(tk_root: tk.Tk) -> None:
    controller = _Controller()
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    frame = PipelineTabFrame(
        notebook, app_state=AppStateV2(), app_controller=controller, pipeline_controller=controller
    )
    other = ttk.Frame(notebook)
    notebook.add(frame, text="Pipeline")
    notebook.add(other, text="Review")
    sidebar = frame.sidebar
    sidebar.set_stage_state("upscale", True)
    sidebar.set_stage_state("img2img", True)
    card = frame.stage_cards_panel.txt2img_card
    card.hires_enabled_var.set(True)
    card.hires_factor_var.set(1.5)
    before_chain = _enabled(sidebar)

    notebook.select(other)
    tk_root.update_idletasks()
    notebook.select(frame)
    tk_root.update_idletasks()

    assert before_chain == ["txt2img", "img2img", "adetailer", "upscale"]
    assert _enabled(sidebar) == before_chain
    assert card.hires_enabled_var.get() is True
    assert card.hires_factor_var.get() == pytest.approx(1.5)
    assert card.advanced_generation_section.header_text().endswith("Hires fix ON")


# --- D. existing-image navigation ----------------------------------------------------------------------------


def test_existing_image_card_is_named_for_the_task_and_launches_review(
    tab: PipelineTabFrame,
) -> None:
    assert tab.sidebar.reprocess_card._title == contract.REVIEW_HANDOFF_TITLE
    assert tab.sidebar.reprocess_panel.open_review_button.cget("text") == "Open Review Workspace"


def test_review_launcher_selects_review_and_queues_nothing(tk_root: tk.Tk) -> None:
    notebook = ttk.Notebook(tk_root)
    notebook.pack(fill="both", expand=True)
    pipeline_frame, review_frame = ttk.Frame(notebook), ttk.Frame(notebook)
    notebook.add(pipeline_frame, text="Pipeline")
    notebook.add(review_frame, text="Review")

    class _Queue:
        calls: list[str] = []

        def __getattr__(self, name: str):
            _Queue.calls.append(name)
            raise AssertionError(f"navigation must not touch {name}")

    controller = SimpleNamespace(
        main_window=SimpleNamespace(center_notebook=notebook, review_tab=review_frame),
        job_service=_Queue(),
    )
    panel = ReprocessPanelV2(pipeline_frame, controller=controller)
    panel.pack()
    panel.open_review_button.invoke()

    assert notebook.tab(notebook.select(), "text") == "Review"
    assert _Queue.calls == []
    assert panel.helper_label.cget("text") != contract.REVIEW_HANDOFF_MISSING


def test_review_launcher_reports_when_review_cannot_open(tk_root: tk.Tk) -> None:
    logged: list[str] = []
    controller = SimpleNamespace(main_window=None, _append_log=logged.append)
    panel = ReprocessPanelV2(tk_root, controller=controller)
    panel.pack()
    panel.open_review_button.invoke()

    assert panel.helper_label.cget("text") == contract.REVIEW_HANDOFF_MISSING
    assert logged and "Review tab could not be activated" in logged[0]


# --- E. usability --------------------------------------------------------------------------------------------


def test_disclosure_headers_are_keyboard_reachable(tab: PipelineTabFrame, tk_root) -> None:
    for section in (
        tab.sidebar.legacy_stage_section,
        tab.stage_cards_panel.txt2img_card.advanced_generation_section,
    ):
        button = section.toggle_button
        assert str(button.cget("takefocus")) in {"1", "True", "true"}
        assert not section.is_expanded()
        assert button.bind("<Return>"), "Return must toggle the disclosure like Space does"
        assert section._on_return(SimpleNamespace()) == "break"
        assert section.is_expanded()
        button.invoke()
        assert not section.is_expanded()


def test_stage_help_wraps_to_a_narrow_sidebar(tab: PipelineTabFrame, tk_root) -> None:
    sidebar = tab.sidebar
    sidebar._on_stage_section_configure(SimpleNamespace(width=200))
    narrow = max(int(label.cget("wraplength")) for label in sidebar._stage_wrap_labels)
    sidebar._on_stage_section_configure(SimpleNamespace(width=500))
    wide = max(int(label.cget("wraplength")) for label in sidebar._stage_wrap_labels)
    assert narrow < wide <= 420
    assert narrow >= 160
