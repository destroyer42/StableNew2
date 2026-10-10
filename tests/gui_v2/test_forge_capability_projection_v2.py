"""PR-IMG-FORGE-120: the UI never advertises what the configured runtime cannot do (Forge by default, A1111 rollback).

Two presentation surfaces, real Tk: the ADetailer stage card's detector choices and the Randomizer's Hypernetwork row.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.randomizer_panel_v2 import (
    HYPERNETWORKS_UNAVAILABLE_LABEL,
    MatrixRow,
    RandomizerPanelV2,
)
from src.gui.stage_cards_v2.adetailer_stage_card_v2 import ADetailerStageCardV2

ACCEPTED_FACE = ["face_yolov8n.pt"]
ACCEPTED_HAND = ["hand_yolov8n.pt"]
GENERIC = {"face_yolov8s.pt", "mediapipe_face_full", "hand_yolov8s.pt", "person_yolov8n-seg.pt"}


def _identity(monkeypatch, identity: str | None) -> None:
    import src.utils.config as config_module

    class _Settings:
        def load_settings(self):
            return {"webui_runtime_identity": identity} if identity else {}

    monkeypatch.setattr(config_module, "ConfigManager", lambda *a, **k: _Settings())
    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)


def _values(combo) -> list[str]:
    return list(combo.cget("values"))


@pytest.mark.parametrize("identity", [None, "forge_webui"], ids=["default", "explicit-forge"])
def test_adetailer_card_offers_only_the_accepted_detectors_under_forge_even_when_refresh_is_unavailable(
    tk_root, monkeypatch, identity
) -> None:
    _identity(monkeypatch, identity)
    card = ADetailerStageCardV2(tk_root)
    try:
        assert _values(card._face_model_combo) == ACCEPTED_FACE
        assert _values(card._hands_model_combo) == ACCEPTED_HAND
        for unavailable in (None, {}, {"adetailer_models": []}):
            card.apply_webui_resources(unavailable)  # the refresh failed or returned nothing
            assert _values(card._face_model_combo) == ACCEPTED_FACE
            assert _values(card._hands_model_combo) == ACCEPTED_HAND
        card.apply_webui_resources({"adetailer_models": ["face_yolov8n.pt", "hand_yolov8n.pt"]})  # a real list is shown
        # PR-REFINE-160: each selector lists only its own kind of detector
        assert _values(card._face_model_combo) == ["face_yolov8n.pt"]
        assert _values(card._hands_model_combo) == ["hand_yolov8n.pt"]
        shown = set(_values(card._face_model_combo)) | set(_values(card._hands_model_combo))
        assert not shown & GENERIC
    finally:
        card.destroy()


def test_adetailer_card_keeps_the_generic_choices_for_the_explicit_a1111_rollback(tk_root, monkeypatch) -> None:
    _identity(monkeypatch, "a1111_webui")
    card = ADetailerStageCardV2(tk_root)
    try:
        assert "mediapipe_face_full" in _values(card._face_model_combo)
        card.apply_webui_resources({})
        assert "face_yolov8s.pt" in _values(card._face_model_combo)
        assert "hand_yolov8s.pt" in _values(card._hands_model_combo)
    finally:
        card.destroy()


def _panel_with_rows(tk_root, *, supported: bool):
    """The Randomizer panel's matrix logic without its full constructor.

    ``RandomizerPanelV2.__init__`` already fails on ``main`` with an unrelated Tk error (a ttk.Treeview is configured with
    ``background``) and the Pipeline tab does not mount the panel, which is separate debt. The Hypernetwork projection
    lives in the row-availability rule, the plan builders and the matrix UI rebuild, all of which run on this harness.
    """

    panel = object.__new__(RandomizerPanelV2)
    panel._hypernetworks_supported = supported
    panel._matrix_frame = ttk.Frame(tk_root)
    panel._handle_var_change = lambda *_a: None
    panel._rows = [
        MatrixRow("model", tk.StringVar(value="Model matrix entries"), tk.StringVar(value="m1, m2"), tk.BooleanVar(value=True)),
        MatrixRow(
            "hypernetwork",
            tk.StringVar(value="Hypernetworks (name[:strength])" if supported else HYPERNETWORKS_UNAVAILABLE_LABEL),
            tk.StringVar(value="styleA:0.5"),
            tk.BooleanVar(value=True),  # even a forced-on row must contribute nothing when unsupported
        ),
    ]
    panel._rebuild_matrix_ui_from_model()
    return panel


def test_randomizer_does_not_present_hypernetworks_as_usable_under_forge(tk_root, monkeypatch) -> None:
    from src.image_backends.backend_capabilities import configured_backend_supports_hypernetworks

    _identity(monkeypatch, None)  # the default: managed Forge
    assert configured_backend_supports_hypernetworks() is False  # what the panel's constructor consults
    panel = _panel_with_rows(tk_root, supported=False)
    try:
        hyper = next(row for row in panel._rows if row.key == "hypernetwork")
        assert panel._row_available(hyper) is False and panel._row_available(panel._rows[0]) is True
        # nothing about Hypernetworks reaches the plan, even with the row forced on and a value typed in
        assert panel._build_matrix_payload() == {"model": ["m1", "m2"]}
        assert panel._get_hypernetwork_entries() == []
        # every control of that row is disabled, so the operator cannot enable or edit it
        entries = [w for w in panel._matrix_frame.winfo_children() if isinstance(w, ttk.Entry)]
        hyper_entries = entries[2:]  # the second row's label and value entries
        assert len(hyper_entries) == 2 and all("disabled" in str(entry.cget("state")) for entry in hyper_entries)
        assert all(str(entry.cget("state")) != "disabled" for entry in entries[:2])  # the model row stays editable
    finally:
        panel._matrix_frame.destroy()


def test_randomizer_keeps_hypernetworks_for_the_explicit_a1111_rollback(tk_root, monkeypatch) -> None:
    from src.image_backends.backend_capabilities import configured_backend_supports_hypernetworks

    _identity(monkeypatch, "a1111_webui")
    assert configured_backend_supports_hypernetworks() is True
    panel = _panel_with_rows(tk_root, supported=True)
    try:
        assert panel._build_matrix_payload() == {"model": ["m1", "m2"], "hypernetwork": [{"name": "styleA", "strength": 0.5}]}
        assert panel._get_hypernetwork_entries() == [{"name": "styleA", "strength": 0.5}]
        assert all(str(entry.cget("state")) != "disabled" for entry in panel._matrix_frame.winfo_children() if isinstance(entry, ttk.Entry))
    finally:
        panel._matrix_frame.destroy()
