"""PR-IMG-MODELS-159: Preview shows the effective Z-Image channels/settings and a compact adaptation notice."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.preview_panel_v2 import PreviewPanelV2
from src.gui_v2.adaptation_notice import compact_adaptation_notice
from src.image_backends.model_policy import resolve_model_policy
from tests.gui_v2.test_zimage_policy_projection import Var, Widget
from tests.helpers.njr_factory import make_pipeline_njr
from tests.pipeline.test_zimage_compile_policy import _pack
from tests.pipeline.test_zimage_effective_config_159 import GLOBAL_POSITIVE, snapshot

pytestmark = pytest.mark.gui


@pytest.fixture
def panel(tk_root):
    widget = PreviewPanelV2(tk_root, controller=None, app_state=AppStateV2())
    yield widget
    widget.destroy()


def _text(widget) -> str:
    return widget.get("1.0", "end").strip()


def test_preview_shows_final_channels_effective_settings_and_a_compact_notice(panel, tmp_path, monkeypatch):
    builder, entry, path, original = _pack(tmp_path, monkeypatch)
    entry.config_snapshot = snapshot(
        builder, positive=(GLOBAL_POSITIVE, True), negative=("ugly, blurry", True), optimizer=True,
        txt2img={"clip_skip": 2, "sampler_name": "DPM++ 2M", "steps": 30},
    )
    (record,) = builder.build_jobs([entry])
    panel.set_preview_jobs([record])

    assert _text(panel.prompt_text) == f"{GLOBAL_POSITIVE}, A ceramic teapot on a wooden table."
    assert _text(panel.negative_prompt_text) == ""
    assert panel.sampler_label.cget("text") == "Sampler: Euler"
    assert panel.steps_label.cget("text") == "Steps: 9"
    notice = panel.adaptation_label.cget("text")
    assert notice.startswith("Adapted for target:")
    assert "global positive composed" in notice and "negative prompt omitted" in notice
    assert "prompt optimizer off" in notice and "clip_skip" in notice
    assert "ugly" not in notice and GLOBAL_POSITIVE not in notice  # content-free
    assert path.read_bytes() == original

    panel.set_preview_jobs([])
    assert panel.adaptation_label.cget("text") == ""


def test_an_unadapted_job_shows_no_notice(panel):
    panel.set_preview_jobs([make_pipeline_njr(positive_prompt="a lighthouse", base_model="ordinary.safetensors")])
    assert panel.adaptation_label.cget("text") == ""


def test_notice_is_compact_deterministic_and_content_free():
    ops = [
        {"code": "weighted_attention_flattened", "details": {"count": 2}},
        {"code": "break_separator_normalized", "details": {"count": 1}},
        {"code": "negative_prompt_dropped_unsupported", "details": {}},
        {"code": "global_positive_composed", "details": {}},
        {"code": "optimizer_not_applied", "details": {}},
        {"code": "profile_value_normalized", "details": {"setting": "clip_skip", "from": 2, "to": 1}},
        {"code": "profile_value_normalized", "details": {"setting": "global_positive_prompt", "cleared": True}},
    ]
    first = compact_adaptation_notice({"operations": ops})
    assert first == compact_adaptation_notice({"operations": ops})
    assert first.endswith("more") and first.count(";") <= 5
    assert "global_positive_prompt" not in first
    assert compact_adaptation_notice(None) == compact_adaptation_notice({}) == compact_adaptation_notice({"operations": []}) == ""


def test_global_positive_toggle_stays_operable_while_the_negative_toggle_locks_and_both_restore():
    from src.gui.zimage_optional_control_projection import ZImageOptionalControlProjection
    from src.gui_v2.model_policy_projection import project_model_selection

    positive_var, negative_var = Var(True), Var(True)
    positive = Widget(state="normal", variable=str(positive_var))
    negative = Widget(state="normal", variable=str(negative_var))
    sidebar = Widget(children=[positive, negative])
    sidebar.stage_states = {}
    sidebar.global_positive_enabled_var = positive_var
    sidebar.global_negative_enabled_var = negative_var
    card = SimpleNamespace(clip_skip_var=Var(2), _hires_frame=Widget(state="normal"), _setting_controls={})
    pipeline = SimpleNamespace(stage_cards_panel=SimpleNamespace(txt2img_card=card))
    optional = ZImageOptionalControlProjection(pipeline, SimpleNamespace(negative_editor=Widget(state="normal")), sidebar)

    zimage_model = resolve_model_policy("zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors").profile_ref
    assert zimage_model
    z = project_model_selection("zImageTurboQuantized_fp8ScaledE4m3fnKJ.safetensors", "forge_webui")
    optional.apply(z)
    assert positive["state"] == "normal"  # its text is composed safely, so it is not an unsupported capability
    assert negative["state"] == "disabled"
    assert positive_var.get() is True and negative_var.get() is True  # stored intent is never rewritten
    optional.apply(project_model_selection("sdxl", "forge_webui"))
    assert positive["state"] == negative["state"] == "normal"


def test_panel_notice_for_a_generic_job_is_built_from_its_effective_configuration_evidence():
    from src.pipeline.job_builder_v2 import JobBuilderV2
    from tests.pipeline.test_exact_profile_effective_config_159 import frozen

    record = JobBuilderV2(time_fn=lambda: 1, id_fn=lambda: "gen").build_jobs(
        base_config=frozen(negative_prompt="ugly, blurry", steps=30, terms="(sharp focus:1.3) BREAK cinematic")
    )[0]
    notice = PreviewPanelV2._adaptation_notice(record)
    for phrase in ("global positive composed", "negative prompt omitted", "weighted syntax flattened", "BREAK normalized"):
        assert phrase in notice
    assert "ugly" not in notice and "blurry" not in notice and "sharp focus" not in notice
