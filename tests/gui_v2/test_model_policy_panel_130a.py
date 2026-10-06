"""PR-IMG-130A: the generic model-policy projection on the Base Generation panel (Tk, deterministic, no I/O).

Selecting a model re-projects the controls from its policy (configurable / supported-but-fixed / unsupported), the
operator's working values survive any number of family switches, and the projection never switches the backend. The
asset family evidence is injected: nothing here scans, hashes or reads user data.
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.image_backends import model_policy as mp
from src.image_backends.forge_klein_profile import latest_klein_profile
from src.image_backends.model_policy import (
    ControlMode,
    ControlPolicy,
    FeaturePolicy,
    ModelPolicy,
    Support,
)

KLEIN = "flux-2-klein-4b-fp8.safetensors"
SDXL_A = "sdxl_a.safetensors"
SDXL_B = "sdxl_b.safetensors"
MYSTERY = "mystery.safetensors"
FIXED_Z = "future_family.safetensors"
NO_VAE = "no_vae_family.safetensors"

_EVIDENCE = {
    SDXL_A: CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()),
    SDXL_B: CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ()),
    MYSTERY: CompatibilityProfile(CompatibilityStatus.UNKNOWN, None, ()),
}


def _lookup(name: str):
    return _EVIDENCE.get(name)


def _future_family(policy_id: str, **controls: ControlPolicy) -> ModelPolicy:
    """A synthetic future family: proves the projection is policy-driven, with no family-specific GUI branch."""

    return ModelPolicy(
        policy_id=policy_id,
        family=policy_id,
        display_name=f"{policy_id} test family",
        evidence=mp.EVIDENCE_PROFILE,
        controls={name: controls.get(name, ControlPolicy()) for name in mp.VALUE_CONTROLS},
        features={name: FeaturePolicy(Support.UNSUPPORTED) for name in mp.FEATURES},
        note=f"{policy_id} note",
    )


_Z = _future_family(
    "future_z",
    sampler=ControlPolicy(ControlMode.FIXED, "Euler"),
    steps=ControlPolicy(ControlMode.FIXED, 8),
    cfg_scale=ControlPolicy(ControlMode.FIXED, 2.5),
)
_NOVAE = _future_family("future_novae", vae=ControlPolicy(ControlMode.UNSUPPORTED))


def _resolver(name: str | None) -> ModelPolicy:
    if name == FIXED_Z:
        return _Z
    if name == NO_VAE:
        return _NOVAE
    return mp.resolve_model_policy(name, family_lookup=_lookup)


def _panel(tk_root: tk.Tk, backend_id: str = "forge_webui") -> BaseGenerationPanelV2:
    panel = BaseGenerationPanelV2(
        tk_root,
        models=[SDXL_A, SDXL_B, MYSTERY, KLEIN, FIXED_Z, NO_VAE],
        samplers=["Euler", "Euler a"],
        include_vae=True,
    )
    projection = panel._model_policy_projection
    projection._backend_id_provider = lambda: backend_id
    projection._policy_resolver = _resolver
    projection.refresh()
    return panel


def _set_working_values(panel: BaseGenerationPanelV2, *, steps: int = 37, cfg: float = 6.5, sampler: str = "Euler a") -> dict:
    panel.sampler_var.set(sampler)
    panel.scheduler_var.set("Karras")
    panel.steps_var.set(steps)
    panel.cfg_var.set(cfg)
    panel.vae_var.set("sdxl_vae.safetensors")
    panel.width_var.set("1152")
    panel.height_var.set("896")
    panel.resolution_preset_var.set("1152x896 (9:7)")
    return _values(panel)


def _values(panel: BaseGenerationPanelV2) -> dict:
    return {
        "sampler": panel.sampler_var.get(), "scheduler": panel.scheduler_var.get(), "steps": panel.steps_var.get(),
        "cfg": panel.cfg_var.get(), "vae": panel.vae_var.get(), "width": panel.width_var.get(),
        "height": panel.height_var.get(), "preset": panel.resolution_preset_var.get(),
    }


_WIDGETS = ("_sampler_combo", "_scheduler_combo", "_steps_spin", "_cfg_spin", "_vae_combo", "_width_combo", "_height_combo")


def _states(panel: BaseGenerationPanelV2) -> dict:
    return {name: str(getattr(panel, name).cget("state")) for name in _WIDGETS}


# --- 1: ordinary SDXL behavior is preserved ---------------------------------------------------------------------------


def test_selecting_an_sdxl_checkpoint_leaves_every_control_as_the_operator_set_it(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        before_states = _states(panel)
        before = _set_working_values(panel)

        panel.model_var.set(SDXL_A)
        panel.model_var.set(SDXL_B)

        assert _values(panel) == before and _states(panel) == before_states
        assert not panel._model_policy_projection.active and panel._model_policy_projection.drafts == {}
        assert all(state != "disabled" for state in _states(panel).values())
    finally:
        panel.destroy()


# --- 3: Klein projects exactly the accepted fixed values ------------------------------------------------------------------


def test_klein_fixes_and_locks_exactly_the_accepted_values(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(KLEIN)

        assert (panel.sampler_var.get(), panel.scheduler_var.get(), panel.steps_var.get(), panel.cfg_var.get()) == ("Euler", "Beta", 4, 1.0)
        assert tuple(panel._preset_combo["values"]) == ("768x1024 (3:4)", "1024x1024 (1:1)")
        assert panel.vae_var.get() == "No VAE (model default)"
        assert set(_states(panel).values()) == {"disabled"}
        assert panel._model_policy_projection.last_projection.policy.profile_ref == latest_klein_profile().reference()
    finally:
        panel.destroy()


# --- 5 / 6: working values survive family switches; repeats never overwrite a draft ----------------------------------------


def test_sdxl_to_klein_to_sdxl_restores_the_sdxl_working_values(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        before_states = _states(panel)
        before = _set_working_values(panel)

        panel.model_var.set(KLEIN)
        assert panel.steps_var.get() == 4
        panel.model_var.set(SDXL_B)  # a different SDXL checkpoint: same family draft

        assert _values(panel) == before and _states(panel) == before_states
        assert panel._model_policy_projection.drafts == {}
    finally:
        panel.destroy()


def test_repeated_refresh_and_reselection_never_overwrite_the_saved_draft(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        before = _set_working_values(panel)
        panel.model_var.set(KLEIN)
        draft = dict(panel._model_policy_projection.drafts["sdxl"])
        for _ in range(3):
            panel._model_policy_projection.refresh()
        panel.model_var.set(KLEIN)
        panel.model_var.set(FIXED_Z)  # constrained -> constrained must not snapshot the fixed values as a draft
        panel.model_var.set(KLEIN)

        assert panel._model_policy_projection.drafts == {"sdxl": draft}
        panel.model_var.set(SDXL_A)
        assert _values(panel) == before
    finally:
        panel.destroy()


def test_a_second_constrained_session_snapshots_the_values_of_that_time(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        _set_working_values(panel)
        panel.model_var.set(KLEIN)
        panel.model_var.set(SDXL_A)
        panel.steps_var.set(21)
        panel.cfg_var.set(4.0)
        panel.model_var.set(KLEIN)
        panel.model_var.set(SDXL_A)

        assert (panel.steps_var.get(), panel.cfg_var.get()) == (21, 4.0)
    finally:
        panel.destroy()


def test_more_than_two_families_round_trip_through_two_constrained_families(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        before = _set_working_values(panel)

        panel.model_var.set(KLEIN)      # fixed everything
        panel.model_var.set(FIXED_Z)    # a different constrained family
        assert (panel.steps_var.get(), panel.cfg_var.get(), panel.sampler_var.get()) == (8, 2.5, "Euler")
        panel.model_var.set(SDXL_A)

        assert _values(panel) == before
    finally:
        panel.destroy()


def test_an_unclassified_model_after_a_constrained_one_gets_the_last_working_values(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        before = _set_working_values(panel)
        panel.model_var.set(KLEIN)
        panel.model_var.set(MYSTERY)  # no draft for this family: the operator's last working values, not Klein's

        assert _values(panel) == before
        assert panel._model_policy_projection.last_projection.policy.family == mp.FAMILY_UNKNOWN
    finally:
        panel.destroy()


def test_moving_between_unconstrained_families_never_rewrites_values(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        _set_working_values(panel)
        panel.model_var.set(MYSTERY)
        panel.steps_var.set(12)
        panel.model_var.set(SDXL_A)

        assert panel.steps_var.get() == 12
    finally:
        panel.destroy()


# --- per-control modes: configurable / fixed / unsupported ----------------------------------------------------------------


def test_a_partially_constrained_family_locks_only_what_its_policy_constrains(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        _set_working_values(panel)
        panel.model_var.set(FIXED_Z)

        states = _states(panel)
        assert [name for name, state in states.items() if state == "disabled"] == ["_sampler_combo", "_steps_spin", "_cfg_spin"]
        assert panel.scheduler_var.get() == "Karras" and panel.vae_var.get() == "sdxl_vae.safetensors"  # untouched
        assert tuple(panel._preset_combo["values"]) != ("768x1024 (3:4)", "1024x1024 (1:1)")  # no geometry restriction

        panel.model_var.set(KLEIN)
        panel.model_var.set(FIXED_Z)  # moving away from a fully fixed family re-enables what this one leaves free
        assert [name for name, state in _states(panel).items() if state == "disabled"] == ["_sampler_combo", "_steps_spin", "_cfg_spin"]
    finally:
        panel.destroy()


def test_an_unsupported_control_is_clearly_unavailable_without_changing_the_persisted_value(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        _set_working_values(panel)
        panel.model_var.set(NO_VAE)

        assert str(panel._vae_combo.cget("state")) == "disabled"
        assert panel.vae_var.get() == "sdxl_vae.safetensors"  # not silently rewritten

        panel.model_var.set(SDXL_A)
        assert str(panel._vae_combo.cget("state")) != "disabled"
    finally:
        panel.destroy()


def test_the_helper_text_comes_from_the_policy_note_and_is_restored(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(SDXL_A)
        before = str(panel._helper_label.cget("text"))
        panel.model_var.set(FIXED_Z)
        assert str(panel._helper_label.cget("text")) == "future_z note"
        panel.model_var.set(SDXL_A)
        assert str(panel._helper_label.cget("text")) == before
    finally:
        panel.destroy()


# --- 7: unknown/conflicting evidence ---------------------------------------------------------------------------------------


def test_unknown_evidence_is_never_projected_as_sdxl(tk_root: tk.Tk) -> None:
    panel = _panel(tk_root)
    try:
        panel.model_var.set(MYSTERY)
        projection = panel._model_policy_projection.last_projection

        assert projection.policy.family == mp.FAMILY_UNKNOWN and projection.policy.policy_id != "sdxl"
        assert not projection.constrained  # generic WebUI usability preserved
    finally:
        panel.destroy()


# --- 8: no backend switching -----------------------------------------------------------------------------------------------


def test_selecting_a_model_never_switches_the_backend_it_only_explains_the_mismatch(tk_root: tk.Tk) -> None:
    provider = Mock(return_value="a1111_webui")
    panel = _panel(tk_root, "a1111_webui")
    try:
        panel._model_policy_projection._backend_id_provider = provider
        panel.model_var.set(KLEIN)
        panel.model_var.set(SDXL_A)
        panel.model_var.set(KLEIN)

        assert "runs only on the Forge WebUI backend" in str(panel._helper_label.cget("text"))
        assert "will not switch backends" in str(panel._helper_label.cget("text"))
        assert provider.return_value == "a1111_webui"
        assert not any(call.args or call.kwargs for call in provider.call_args_list)  # read-only: it is only ever asked
    finally:
        panel.destroy()


def test_the_default_projection_resolves_policy_without_a_scan(tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    """The panel's default family lookup is the persisted-snapshot lookup (no refresh/scan on the Tk thread)."""

    panel = BaseGenerationPanelV2(tk_root, models=[SDXL_A], samplers=["Euler"], include_vae=True)
    try:
        assert isinstance(panel._model_policy_projection._family_lookup, mp.RegistryFamilyLookup)
    finally:
        panel.destroy()
