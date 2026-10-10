"""PR-REFINE-160: ADetailer card defaults, control truth, detector separation and the effective-settings projection."""

from __future__ import annotations

from tkinter import ttk

import pytest

from src.gui.stage_cards_v2 import adetailer_stage_card_v2 as module
from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2
from src.pipeline.adetailer_contract import UNSUPPORTED_CONFIG_KEYS

FORGE = (("face_yolov8n.pt",), ("hand_yolov8n.pt",))


def make(tk_root, monkeypatch, fallbacks=FORGE):
    monkeypatch.setattr(module, "configured_adetailer_detector_fallbacks", lambda: fallbacks)
    return ADetailerStageCardV2(tk_root)


def label_texts(widget) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            texts.append(str(child.cget("text")))
        texts.extend(label_texts(child))
    return texts


@pytest.mark.gui
def test_a_fresh_card_enables_both_passes_and_exports_both_flags(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)
    exported = card.to_config_dict()
    assert card.enable_face_pass_var.get() is True and card.enable_hands_pass_var.get() is True
    assert exported["enable_face_pass"] is True and exported["enable_hands_pass"] is True
    assert exported["ad_hands_enabled"] is True  # synchronized compatibility mirror
    assert (
        "adetailer_enabled" not in exported and "enabled" not in exported
    )  # the overall stage is not this card's default


@pytest.mark.gui
def test_explicit_saved_pass_choices_are_preserved_including_a_disabled_hand_pass(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    card.load_from_dict({"enable_face_pass": False, "enable_hands_pass": False})
    assert (card.enable_face_pass_var.get(), card.enable_hands_pass_var.get()) == (False, False)
    exported = card.to_config_dict()
    assert exported["enable_hands_pass"] is False and exported["ad_hands_enabled"] is False
    card.load_from_dict({"ad_hands_enabled": True})
    assert card.enable_hands_pass_var.get() is True


@pytest.mark.gui
def test_loading_a_legacy_configuration_that_omits_the_hand_flag_does_not_enable_hands(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    assert card.enable_hands_pass_var.get() is True  # fresh default
    card.load_from_dict({"adetailer_model": "face_yolov8n.pt", "adetailer_confidence": 0.4})
    assert card.enable_hands_pass_var.get() is False  # historical meaning kept
    assert card.to_config_dict()["enable_hands_pass"] is False


@pytest.mark.gui
def test_misleading_controls_are_gone_and_top_k_is_labelled_accurately(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)
    texts = label_texts(card)
    assert "Max Detections" not in texts and "Mask Feather" not in texts
    assert texts.count("Retained Masks (Top-K)") == 2 and "Mask Max-K" not in texts
    assert texts.count("Mask Blur") == 2  # the supported control stays
    assert not hasattr(card, "max_detections_var") and not hasattr(card, "face_mask_feather_var")
    assert card.MASK_FILTER_OPTIONS == ["Area", "Confidence"]
    exported = card.to_config_dict()
    assert not (set(exported) & UNSUPPORTED_CONFIG_KEYS)
    assert exported["ad_mask_k_largest"] == 3 and exported["ad_hands_mask_k"] == 6


@pytest.mark.gui
def test_historical_unsupported_values_round_trip_without_being_presented_or_changed(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    card.load_from_dict(
        {
            "max_detections": 9,
            "mask_feather": 7,
            "ad_hands_mask_feather": 5,
            "enable_hands_pass": True,
        }
    )
    exported = card.to_config_dict()
    assert (
        exported["max_detections"] == 9
        and exported["mask_feather"] == 7
        and exported["ad_hands_mask_feather"] == 5
    )
    card.load_from_dict({"enable_hands_pass": True})
    assert (
        "max_detections" not in card.to_config_dict()
    )  # a later load without them does not resurrect them


@pytest.mark.gui
def test_cfg_is_bounded_by_the_schema_maximum(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)

    def spin_max(frame, label):
        for child in frame.winfo_children():
            if isinstance(child, ttk.Label) and str(child.cget("text")) == label:
                row = int(child.grid_info()["row"])
                spin = next(
                    w
                    for w in frame.winfo_children()
                    if int(w.grid_info().get("row", -1)) == row and isinstance(w, ttk.Spinbox)
                )
                return float(spin.cget("to"))
        raise AssertionError(label)

    assert spin_max(card._face_tab, "CFG") == 24.0 and spin_max(card._hand_tab, "CFG") == 24.0


@pytest.mark.gui
def test_live_detector_lists_are_separated_and_mediapipe_and_body_models_are_never_offered_under_forge(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    card.apply_webui_resources(
        {
            "adetailer_models": [
                "face_yolov8n.pt",
                "face_yolov8s.pt",
                "hand_yolov8n.pt",
                "person_yolov8n-seg.pt",
                "mediapipe_face_full",
            ]
        }
    )
    assert list(card._face_model_combo["values"]) == ["face_yolov8n.pt", "face_yolov8s.pt"]
    assert list(card._hands_model_combo["values"]) == ["hand_yolov8n.pt"]


@pytest.mark.gui
def test_a_generic_runtime_may_offer_mediapipe_for_faces_but_never_for_hands(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch, fallbacks=None)
    card.apply_webui_resources(
        {
            "adetailer_models": [
                "face_yolov8n.pt",
                "mediapipe_face_full",
                "hand_yolov8n.pt",
                "hand_yolov8s.pt",
            ]
        }
    )
    assert "mediapipe_face_full" in card._face_model_combo["values"]
    assert all("hand" in v for v in card._hands_model_combo["values"])


@pytest.mark.gui
def test_an_unavailable_saved_detector_is_kept_flagged_and_never_substituted(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)
    card.load_from_dict(
        {
            "adetailer_model": "face_custom.pt",
            "adetailer_hands_model": "hand_custom.pt",
            "enable_hands_pass": True,
        }
    )
    card.apply_webui_resources({"adetailer_models": ["face_yolov8n.pt", "hand_yolov8n.pt"]})
    assert (
        card.face_model_var.get() == "face_custom.pt"
        and card.hands_model_var.get() == "hand_custom.pt"
    )
    assert card.to_config_dict()["adetailer_model"] == "face_custom.pt"
    summary = card.effective_summary()
    assert "face_custom.pt - not installed; it is kept, not substituted" in summary
    assert "hand_custom.pt - not installed; it is kept, not substituted" in summary


@pytest.mark.gui
def test_a_detector_of_the_wrong_kind_is_flagged(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)
    card.hands_model_var.set("face_yolov8n.pt")
    assert "not a hand detector" in card.effective_summary()


@pytest.mark.gui
def test_the_effective_summary_reports_pass_enablement_detectors_and_rejected_settings(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    card.apply_webui_resources({"adetailer_models": ["face_yolov8n.pt", "hand_yolov8n.pt"]})
    summary = card.effective_summary()
    assert (
        "Face pass: on, detector face_yolov8n.pt" in summary
        and "Hand pass: on, detector hand_yolov8n.pt" in summary
    )
    card.enable_hands_pass_var.set(False)
    card._sync_pass_states()
    assert "Hand pass: off" in card.effective_summary()
    card.face_mask_filter_method_var.set(
        "largest"
    )  # a legacy value the pinned extension would reject
    assert "ad_mask_filter_method" in card.effective_summary()
    assert "Face pass:" in str(card._effective_summary_label.cget("text"))


@pytest.mark.gui
def test_legacy_filter_values_the_extension_never_accepted_are_shown_as_area_with_a_visible_note(
    tk_root, monkeypatch
):
    card = make(tk_root, monkeypatch)
    card.load_from_dict(
        {
            "ad_mask_filter_method": "largest",
            "ad_hands_mask_filter_method": "all",
            "enable_hands_pass": True,
        }
    )
    exported = card.to_config_dict()
    assert (
        exported["ad_mask_filter_method"] == "Area"
        and exported["ad_hands_mask_filter_method"] == "Area"
    )
    summary = card.effective_summary()
    assert "Face mask filter 'largest' was never supported" in summary
    assert "Hand mask filter 'all' was never supported" in summary
    card.load_from_dict({"ad_mask_filter_method": "Confidence"})
    assert "Note:" not in card.effective_summary()  # supported values carry no note


@pytest.mark.gui
def test_the_projection_says_no_correction_will_run_when_both_passes_are_off(tk_root, monkeypatch):
    card = make(tk_root, monkeypatch)
    card.enable_face_pass_var.set(False)
    card.enable_hands_pass_var.set(False)
    card._sync_pass_states()
    assert "No correction will run" in card.effective_summary()
    card.enable_hands_pass_var.set(True)
    assert "No correction will run" not in card.effective_summary()
