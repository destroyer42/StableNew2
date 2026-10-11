"""Tk-free panel stand-ins prove fixed projection, draft restoration and no runtime switch."""

from types import SimpleNamespace

from src.gui.model_policy_panel_projection import ModelPolicyPanelProjection
from src.gui_v2.model_policy_projection import project_model_selection
from src.image_backends.forge_klein_profile import KLEIN_PROFILE_V1
from src.image_backends.forge_zimage_profile import ZIMAGE_PROFILE_V1 as P


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget(dict):
    def cget(self, key):
        return self[key]

    def configure(self, **kw):
        self.update(kw)

    def winfo_children(self):
        return self.get("children", [])


def test_sdxl_and_klein_drafts_survive_zimage_projection():
    p = SimpleNamespace(**{k: Var(v) for k, v in {
        "model_var": "sdxl", "sampler_var": "Euler a", "scheduler_var": "Karras", "steps_var": 24,
        "cfg_var": 7, "vae_var": "sdxl_vae", "width_var": "1152", "height_var": "896",
        "resolution_preset_var": "1152x896",
    }.items()})
    for name in ("_sampler_combo", "_scheduler_combo", "_steps_spin", "_cfg_spin", "_vae_combo", "_width_combo", "_height_combo"):
        setattr(p, name, Widget(state="normal"))
    p._preset_combo = Widget(values=("1152x896",))
    p._helper_label = Widget(text="helper")
    p._preset_map, p._preset_reverse_map = {}, {}
    projection = ModelPolicyPanelProjection(p, backend_id_provider=lambda: "forge_webui", family_lookup=lambda _: None)
    projection.refresh()
    p.model_var.set(KLEIN_PROFILE_V1.transformer.filename)
    projection.refresh()
    p.width_var.set("768")
    p.height_var.set("1024")
    p.model_var.set(P.transformer.filename)
    z = projection.refresh()
    assert (p.width_var.get(), p.height_var.get(), p.steps_var.get(), p.cfg_var.get()) == ("1024", "1024", 9, 1)
    assert z.presets == (("1024x1024 (1:1)", 1024, 1024),)
    assert p._steps_spin["state"] == "disabled"
    p.model_var.set(KLEIN_PROFILE_V1.transformer.filename)
    projection.refresh()
    assert (p.width_var.get(), p.height_var.get(), p.steps_var.get()) == ("768", "1024", 4)
    p.model_var.set("sdxl")
    projection.refresh()
    assert (p.width_var.get(), p.height_var.get(), p.steps_var.get(), p.cfg_var.get()) == ("1152", "896", 24, 7)
    assert p._steps_spin["state"] == "normal"


def test_projection_requires_forge_without_changing_the_selected_runtime():
    z = project_model_selection(P.transformer.filename, "a1111_webui")
    assert "select the Forge" in z.blocking
    assert z.policy.required_backend == "forge_webui"
    assert not z.policy.feature("negative_prompt").supported
    assert not z.policy.feature("lora").supported


def test_optional_controls_lock_without_deleting_stored_conflicts_and_restore():
    from src.gui.zimage_optional_control_projection import ZImageOptionalControlProjection

    stage_var = Var(True)
    check = Widget(state="normal", variable=str(stage_var))
    sidebar = Widget(children=[check])
    sidebar.stage_states = {"adetailer": stage_var}
    clip = Var(2)
    hires = Widget(state="normal")
    card = SimpleNamespace(clip_skip_var=clip, _hires_frame=hires, _setting_controls={})
    pipeline = SimpleNamespace(stage_cards_panel=SimpleNamespace(txt2img_card=card))
    negative = Widget(state="normal")
    optional = ZImageOptionalControlProjection(pipeline, SimpleNamespace(negative_editor=negative), sidebar)
    z = project_model_selection(P.transformer.filename, "forge_webui")
    optional.apply(z)
    optional.apply(z)
    assert clip.get() == 1 and stage_var.get() is True
    assert check["state"] == hires["state"] == negative["state"] == "disabled"
    optional.apply(project_model_selection("sdxl", "forge_webui"))
    assert clip.get() == 2 and stage_var.get() is True
    assert check["state"] == hires["state"] == negative["state"] == "normal"
