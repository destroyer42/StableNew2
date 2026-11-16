"""LEARN-NAV-871 (real Tk): the Design step starts from an objective and says what the model can test, and why not.

No backend, GPU or live app. The Compatibility Probe entry is routed through an injected recorder; no dialog opens.
"""

from __future__ import annotations

from tkinter import ttk
from types import SimpleNamespace

import pytest

from src.gui.views import model_evidence_window as evidence_window
from src.gui.views.experiment_design_panel import ExperimentDesignPanel
from src.learning import study_catalog
from src.learning.model_comparison import study_type
from src.learning.study_eligibility import eligible_studies
from tests.gui_v2.tk_test_utils import get_shared_tk_root
from tests.learning_v2.test_learning_independent_baseline_650 import Bench
from tests.learning_v2.test_model_comparison_140 import SDXL, policy


def tk_or_skip():
    root = get_shared_tk_root()
    if root is None:
        pytest.skip("Tk is unavailable")
    return root


@pytest.fixture
def design(tmp_path):
    root = tk_or_skip()
    bench = Bench(tmp_path)
    bench.controller.app_state = SimpleNamespace(resources={}, content_visibility_mode="nsfw")
    bench.controller.copy_pipeline_settings("txt2img")
    widget = ExperimentDesignPanel(root, learning_controller=bench.controller, packs_dir=tmp_path)
    widget.pack()
    root.update()
    yield widget, bench, root
    widget.destroy()
    root.update_idletasks()


def set_model(widget, bench, model):
    bench.controller.update_baseline_field("txt2img", "model", model)
    widget._on_baseline_changed()


def status(widget, slug) -> str:
    return widget._objective_status[slug].get()


def texts(widget, kind) -> list[str]:
    found = []

    def walk(node):
        for child in node.winfo_children():
            if isinstance(child, kind):
                found.append(str(child.cget("text")))
            walk(child)

    walk(widget)
    return found


def entry_labels(widget) -> list[str]:
    return [
        text
        for text in texts(widget.study_section.body, ttk.Label)
        if text in {o.label for o in study_catalog.OBJECTIVES}
    ]


# -- structure --------------------------------------------------------------------------------------------------------


def test_the_selector_and_the_three_shortcut_buttons_are_gone_and_the_objectives_are_listed_in_order(
    design,
):
    widget, _bench, _root = design
    assert not hasattr(widget, "study_type_combo")
    assert "Prompt Slot Experiment" not in texts(widget, ttk.Button)
    assert texts(widget, ttk.Button).count("LoRA Composition") == 0
    assert texts(widget, ttk.Button).count("Embedding") == 0
    assert entry_labels(widget) == [
        "Does this model work here",
        "Find a better setting",
        "Is this adapter worth using",
        "Which do I prefer",
        "More comparisons",
    ]
    assert sorted(widget.objective_choices) == sorted(study_catalog.slugs())


def test_each_entry_sits_under_the_owner_approved_objective(design):
    widget, _bench, _root = design
    body = widget.study_section.body
    # Walk the grid in row order and group each choice under the most recent objective heading.
    heading_labels = {o.label for o in study_catalog.OBJECTIVES}
    by_row = {}
    for child in body.winfo_children():
        if child.grid_info():  # an empty status line is grid-removed
            by_row[int(child.grid_info()["row"])] = child
    current, grouped = "", {}
    for row in sorted(by_row):
        child = by_row[row]
        if isinstance(child, ttk.Label) and str(child.cget("text")) in heading_labels:
            current = str(child.cget("text"))
            grouped[current] = []
        elif isinstance(child, (ttk.Radiobutton, ttk.Button)):
            grouped[current].append(str(child.cget("text")))
    assert grouped == {
        "Does this model work here": ["Compatibility Probe (opens the Model Evidence Catalog)"],
        "Find a better setting": ["Controlled Variable"],
        "Is this adapter worth using": ["LoRA Composition", "Embedding"],
        "Which do I prefer": ["Prompt Slot", "Model Comparison"],
        "More comparisons": ["Two-Axis Grid", "Prompt x Model Matrix"],
    }


# -- every objective opens the existing frame -------------------------------------------------------------------------


FRAMES = {
    "controlled_variable": None,
    "prompt_slot": "prompt_slot_frame",
    "lora_composition": "lora_composition_frame",
    "embedding_experiment": "embedding_frame",
    "model_comparison": None,
    "two_axis_grid": "grid_frame",
    "prompt_model_matrix": "matrix_frame",
}


@pytest.mark.parametrize("slug", sorted(FRAMES))
def test_choosing_an_entry_opens_the_existing_design_frame(design, slug):
    widget, _bench, root = design
    other = "prompt_slot" if slug != "prompt_slot" else "controlled_variable"
    widget.objective_choices[other].invoke()  # leave the default first so the change is observable
    widget.objective_choices[slug].invoke()
    root.update()
    label = study_catalog.lookup(slug).label
    assert widget.study_type_var.get() == label
    assert widget.current_study_slug() == slug
    frame = FRAMES[slug]
    if frame:
        assert getattr(widget, frame).winfo_manager() == "grid"
    for name, other_frame in FRAMES.items():
        if other_frame and name != slug:
            assert getattr(widget, other_frame).winfo_manager() == ""
    assert widget.study_section.is_expanded()


def test_the_compatibility_probe_entry_opens_the_catalog_through_the_injected_route(design):
    widget, _bench, _root = design
    opened = []
    widget.set_on_open_model_evidence(lambda: opened.append(True))
    widget.objective_choices["compatibility_probe"].invoke()
    assert opened == [True]
    assert widget.study_type_var.get() == "Controlled Variable"  # it never switches the form
    with pytest.raises(ValueError):
        widget.choose_study("compatibility_probe")


# -- availability and reasons -------------------------------------------------------------------------------------------


def test_a_registry_sdxl_model_shows_its_variables_and_no_refusals(design):
    widget, bench, _root = design
    set_model(widget, bench, SDXL)
    for slug in ("prompt_slot", "lora_composition", "embedding_experiment", "two_axis_grid"):
        assert "Not available" not in status(widget, slug), slug
    assert status(widget, "controlled_variable").startswith("You can vary: ")
    assert "CFG Scale" in status(widget, "controlled_variable")


def test_an_unsupported_model_shows_each_studys_own_refusal_and_keeps_the_study_reachable(design):
    widget, bench, root = design
    set_model(widget, bench, "sd1")
    result = eligible_studies(policy("sd1"), bench.controller.authoring_baseline(), {}, model="sd1")
    for study in result.studies:
        if study.slug in ("controlled_variable", "compatibility_probe"):
            continue
        assert not study.available, study.slug
        assert study.reason in status(widget, study.slug)
        assert status(widget, study.slug).startswith("Not available on this model: ")
    widget.objective_choices[
        "prompt_slot"
    ].invoke()  # unavailable studies are shown, never hidden or disabled
    root.update()
    assert widget.current_study_slug() == "prompt_slot"
    # The existing readiness text is the same refusal the chooser showed.
    assert "registry-verified SDXL" in widget.readiness_reason()
    assert result.get("prompt_slot").reason in widget.readiness_reason()


def test_without_a_learning_model_every_entry_says_to_choose_one(design):
    widget, bench, _root = design
    set_model(widget, bench, "")
    for slug in widget.objective_choices:
        assert "Choose a model in the Learning baseline" in status(widget, slug)


def test_readiness_text_is_the_existing_text_and_not_the_chooser_s(design):
    widget, bench, root = design
    set_model(widget, bench, SDXL)
    widget.objective_choices["lora_composition"].invoke()
    root.update()
    reason = widget.readiness_reason()
    assert reason == str(widget._special_readiness())
    assert not reason.startswith("Not available on this model")


# -- saved sessions reopen to the right entry ------------------------------------------------------------------------


ALL_TYPES = [
    ("controlled_variable", "Controlled Variable"),
    ("prompt_slot", "Prompt Slot"),
    ("lora_composition", "LoRA Composition"),
    ("embedding_experiment", "Embedding"),
    ("model_comparison", "Model Comparison"),
    ("two_axis_grid", "Two-Axis Grid"),
    ("prompt_model_matrix", "Prompt x Model Matrix"),
]


@pytest.mark.parametrize(("literal", "label"), ALL_TYPES)
def test_a_saved_session_reopens_on_its_own_entry(design, literal, label):
    widget, _bench, root = design
    experiment = SimpleNamespace(
        name="saved",
        description="",
        stage="txt2img",
        variable_under_test="",
        input_image_path="",
        images_per_value=1,
        prompt_text="a lighthouse",
        execution_snapshot_json="",
        metadata={"study_type": literal, "prompt_source": "custom"},
    )
    assert study_type(experiment) == literal
    widget.restore_state(experiment)
    root.update()
    assert widget.study_type_var.get() == label
    assert widget.current_study_slug() == literal
    assert study_catalog.lookup(literal).objective_group in {
        o.key for o in study_catalog.OBJECTIVES
    }


def test_a_reopened_compatibility_probe_session_is_marked_as_the_probe_entry(design):
    widget, _bench, root = design
    experiment = SimpleNamespace(
        name="probe",
        description="",
        stage="txt2img",
        variable_under_test="Compatibility Recipe",
        input_image_path="",
        images_per_value=2,
        prompt_text="",
        execution_snapshot_json="",
        metadata={"study_type": "compatibility_probe"},
    )
    widget.restore_state(experiment)
    root.update()
    assert widget.current_study_slug() == "compatibility_probe"
    assert "Compatibility Probe" in widget.study_hint_var.get()
    widget.objective_choices["prompt_slot"].invoke()
    assert widget.current_study_slug() == "prompt_slot"  # choosing again clears the marker


def test_preview_staleness_still_follows_the_design_signature_and_study_type(design):
    widget, bench, root = design
    widget.objective_choices["prompt_slot"].invoke()
    root.update()
    bench.state.current_experiment = SimpleNamespace(
        execution_snapshot_json='{"study_type": "prompt_slot"}'
    )
    widget._preview_signature = widget.design_signature()
    assert not widget.preview_is_stale()
    widget.objective_choices["lora_composition"].invoke()
    root.update()
    assert widget.preview_is_stale()
    assert widget.design_signature()[0] == "LoRA Composition"


# -- Model Evidence Catalog details ---------------------------------------------------------------------------------


def test_the_catalog_details_block_lists_what_this_model_can_test():
    target = SimpleNamespace(policy=policy(SDXL), identity=SimpleNamespace(display_name=SDXL))
    lines = evidence_window._can_test_lines(target, None)
    text = "\n".join(lines)
    assert "Does this model work here:" in text and "Compatibility Probe: available" in text
    unsupported = SimpleNamespace(
        policy=policy("sd1"), identity=SimpleNamespace(display_name="sd1")
    )
    refusal = "\n".join(evidence_window._can_test_lines(unsupported, None))
    assert (
        "Prompt Slot: not available - Prompt Slot currently requires registry-verified SDXL txt2img."
        in refusal
    )
    broken = SimpleNamespace(policy=None, identity=SimpleNamespace(display_name="x"))
    assert evidence_window._can_test_lines(broken, None)[0].startswith("Not available yet")


def test_the_catalog_details_pane_renders_the_block_beside_the_existing_assessment():
    root = tk_or_skip()
    owner = ttk.Frame(root)
    owner._on_open_experiment_library = lambda: None
    window = evidence_window.ModelEvidenceWindow(owner)
    try:
        relative = "models/Stable-diffusion/test.safetensors"
        row = {
            "kind": "checkpoint",
            "relative": relative,
            "identity_status": "pending",
            "family": "sdxl",
            "size": 1,
            "header": {},
        }
        window.census = {"assets": [row]}
        window._assessments = {
            relative: evidence_window.RowAssessment(
                "Verified",
                "sdxl",
                0,
                "Nothing to vary yet.",
                ("Identity: Verified",),
                {},
                ("Find a better setting:", "  Controlled Variable: available"),
            )
        }
        window._history_state = "ready"
        window._history = {}
        window._render_assets()
        window.tree.selection_set(window.tree.get_children()[0])
        window._paths[relative] = object()
        window._render_details()
        details = window.details.get("1.0", "end")
        assert "WHAT YOU CAN TEST ON THIS MODEL" in details
        assert "  Controlled Variable: available" in details
        assert "PAST RUNS" in details and "Identity: Verified" in details
    finally:
        window._close()
        owner.destroy()
