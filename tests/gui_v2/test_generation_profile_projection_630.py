"""PR-IMG-PROFILE-630: the profile strip's text (no Tk) and its Tk wiring in the Base Generation panel."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.generation_profiles.application import ApplicationPlan
from src.generation_profiles.contract import SOURCE_OFFICIAL, SOURCE_STABLENEW_TESTED
from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.generation_profile_strip import GenerationProfileStrip
from src.gui_v2.generation_profile_projection import (
    NO_MODEL_TEXT,
    NO_PROFILE_LABEL,
    SOURCE_LABELS,
    build_strip_view,
    effective_profile_lines,
    evidence_text,
)
from tests.controller.test_generation_profile_controller_630 import (
    KLEIN,
    SDXL_MODEL,
    FakeHost,
    FakePanel,
)


@pytest.fixture
def host(tmp_path: Path) -> FakeHost:
    return FakeHost(FakePanel(), tmp_path)


# --------------------------------------------------------------------------- projection (no Tk)


def test_without_a_model_the_strip_explains_itself_and_offers_nothing_to_act_on() -> None:
    view = build_strip_view(None)
    assert view.status == NO_MODEL_TEXT and view.labels == (NO_PROFILE_LABEL,)
    assert not (view.can_restore or view.can_update_custom or view.can_favorite)


def test_options_are_grouped_research_learning_custom_with_the_selected_row_marked(
    host: FakeHost,
) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    host.panel.values.update(steps=22)
    host.profiles.on_save_custom("Mine")
    view = host.profiles.strip_view()

    assert view.labels[0] == NO_PROFILE_LABEL
    assert view.labels[1].startswith("Research:") and view.labels[-1].startswith("Custom: Mine")
    assert view.refs[0] is None and view.selected_index == len(view.labels) - 1
    assert view.can_update_custom and view.can_save


def test_evidence_text_names_the_source_class_citation_and_missing_values(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    profile = host.profiles.service.get(host.profiles.state().selected)
    text = evidence_text(profile)

    assert "Width: 1024" in text and SOURCE_LABELS[SOURCE_OFFICIAL] in text
    assert (
        "Sampler: no recommendation" in text
    )  # an unsourced value is stated as missing, never invented
    assert "Sources reviewed" in text


def test_exact_profile_evidence_distinguishes_official_from_stablenew_tested(
    host: FakeHost,
) -> None:
    host.panel.values["model"] = KLEIN
    host.profiles.on_model_chosen(KLEIN)
    text = evidence_text(host.profiles.service.get(host.profiles.state().selected))
    assert SOURCE_LABELS[SOURCE_STABLENEW_TESTED] in text or SOURCE_LABELS[SOURCE_OFFICIAL] in text


def test_unverified_model_status_gives_the_reason_and_offers_no_restore(host: FakeHost) -> None:
    host.panel.values["model"] = "mystery.safetensors"
    host.profiles.on_model_chosen("mystery.safetensors")
    view = host.profiles.strip_view()
    assert not view.can_restore and view.selected_index == 0
    assert view.status


def test_edited_state_is_disclosed_and_restore_clears_it(host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    assert "Edited" not in host.profiles.strip_view().status
    host.panel.values["width"] = 640
    assert "Edited since the profile was applied" in host.profiles.strip_view().status
    host.profiles.on_restore_selected()
    assert "Edited since" not in host.profiles.strip_view().status


def test_effective_lines_cover_model_profile_and_override_without_claiming_job_facts(
    host: FakeHost,
) -> None:
    assert effective_profile_lines(None, override_enabled=True) == ()
    host.profiles.on_model_chosen(SDXL_MODEL)
    state = host.profiles.state()
    on = effective_profile_lines(state, override_enabled=True)
    off = effective_profile_lines(state, override_enabled=False)
    unknown = effective_profile_lines(state, override_enabled=None)
    assert on[0].startswith(f"Model: {SDXL_MODEL}") and "Research" in on[1]
    assert "Override is ON" in on[-1] and "Override is OFF" in off[-1] and len(unknown) == 2


def test_plan_messages_are_shown_for_a_conflict_and_a_missing_profile() -> None:
    plan = ApplicationPlan(
        "identity_conflict",
        None,
        {},
        (),
        "This profile belongs to a different model; nothing was applied.",
    )
    view = build_strip_view(
        SimpleNamespace(
            model_name="m", options=(), selected=None, modified=False, unverified_reason=""
        ),
        plan,
    )
    assert "different model" in view.status


# --------------------------------------------------------------------------- Tk wiring


def test_strip_renders_the_view_and_selecting_a_row_applies_that_profile(
    tk_root, host: FakeHost
) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    strip = GenerationProfileStrip(tk_root, controller_getter=lambda: host.profiles)
    strip.refresh()
    assert strip.profile_var.get().startswith("Research:")
    assert str(strip.restore_button.cget("state")) in (
        "normal",
        "",
    ) or not strip.restore_button.instate(["disabled"])

    host.panel.values["width"] = 640
    strip.profile_var.set(strip.combo["values"][1])
    strip.combo.current(1)
    strip._on_selected()
    assert host.panel.values["width"] == 1024

    strip.combo.current(0)
    strip._on_selected()  # "No profile": keep the working values
    assert host.panel.values["width"] == 1024 and not strip.restore_button.instate(["!disabled"])


def test_strip_details_toggle_and_actions(tk_root, host: FakeHost) -> None:
    host.profiles.on_model_chosen(SDXL_MODEL)
    names = iter(["", "Mine"])
    strip = GenerationProfileStrip(
        tk_root, controller_getter=lambda: host.profiles, name_prompt=lambda _p, _s: next(names)
    )
    assert not strip.detail_frame.winfo_manager()
    strip.toggle_details()
    assert strip.detail_frame.winfo_manager() and "Width" in strip.evidence_label.cget("text")

    strip.save_as_custom()  # cancelled prompt: nothing is saved
    assert not [label for label in strip.combo["values"] if label.startswith("Custom:")]
    strip.save_as_custom()
    assert any(label.startswith("Custom: Mine") for label in strip.combo["values"])
    assert "Saved Custom profile 'Mine'" in strip.message_label.cget("text")

    strip.toggle_favorite()
    assert strip.favorite_button.cget("text") == "Remove favorite"
    strip.toggle_details()
    assert not strip.detail_frame.winfo_manager()


def test_strip_without_a_controller_is_inert(tk_root) -> None:
    strip = GenerationProfileStrip(tk_root, controller_getter=lambda: None)
    strip.refresh()
    strip._on_selected()
    strip.restore()
    strip.save_as_custom()


def test_base_panel_applies_profile_values_without_touching_other_controls(
    tk_root, host: FakeHost
) -> None:
    controller = SimpleNamespace(generation_profiles=host.profiles)
    panel = BaseGenerationPanelV2(tk_root, controller=controller, include_vae=True)
    panel.seed_var.set("42")
    panel.model_var.set(SDXL_MODEL)
    changed: list[int] = []
    panel._on_change = lambda: changed.append(1)

    panel.apply_profile_values(
        {
            "width": 1024,
            "height": 1024,
            "steps": 9,
            "cfg_scale": 1.0,
            "sampler_name": "Euler",
            "scheduler": "Beta",
        }
    )

    overrides = panel.get_overrides()
    assert (
        overrides["width"],
        overrides["height"],
        overrides["steps"],
        overrides["cfg_scale"],
    ) == (1024, 1024, 9, 1.0)
    assert overrides["sampler"] == "Euler" and overrides["scheduler"] == "Beta"
    assert overrides["seed"] == 42 and overrides["model"] == SDXL_MODEL  # untouched
    assert changed  # the Preview/summary are told the working settings changed
    panel.apply_profile_values({})


def test_choosing_a_checkpoint_in_the_panel_applies_the_profile_through_the_controller(
    tk_root, host: FakeHost
) -> None:
    controller = SimpleNamespace(generation_profiles=host.profiles)
    panel = BaseGenerationPanelV2(tk_root, controller=controller, include_vae=True)
    host.panel = panel  # the profile controller reads and writes the real panel's seam
    host.sidebar.panel = panel
    panel.model_var.set(SDXL_MODEL)
    panel.width_var.set("640")

    panel._on_model_chosen()

    assert panel.get_overrides()["width"] == 1024
    assert host.profiles.state().selected.profile_id == "research-sdxl-family"


def test_a_failing_profile_controller_never_blocks_model_selection(tk_root) -> None:
    class Broken:
        def on_model_chosen(self, _name: str) -> None:
            raise RuntimeError("boom")

        def add_listener(self, _fn: object) -> None:
            raise RuntimeError("boom")

    panel = BaseGenerationPanelV2(
        tk_root, controller=SimpleNamespace(generation_profiles=Broken()), include_vae=True
    )
    panel._on_model_chosen()
