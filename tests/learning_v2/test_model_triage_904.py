"""MEC-904: plain-language hypotheses for checkpoints that do not work, from facts already held."""

from src.learning.model_run_history import ModelRunSummary
from src.learning.model_triage import triage


def causes(**kw):
    return triage(**{"header": {}, "family": "sdxl", "history": None, **kw})


def test_structural_hypotheses_from_the_header():
    assert "inpainting" in causes(header={"checkpoint_architecture": "sdxl_inpaint"})[0]
    assert "refiner" in causes(header={"checkpoint_architecture": "sdxl_refiner"})[0]
    assert "Quantized" in causes(header={"quantization_formats": ["nf4"]})[0]
    assert "diffusion-only" in causes(header={"checkpoint_architecture": "unrecognized"})[0]
    assert "incomplete" in causes(header={"error": "malformed or truncated safetensors header"})[0]


def test_turbo_is_compared_with_the_steps_your_runs_used():
    history = ModelRunSummary(completed=32, settings=(("steps", (("36", 30),)),))
    text = causes(
        header={"checkpoint_variant": "turbo", "checkpoint_architecture": "sdxl_base"},
        history=history,
    )
    assert "1–4 steps" in text[0] and "mostly used 36 steps" in text[0]


def test_history_errors_and_civitai_lineage_become_hypotheses():
    history = ModelRunSummary(
        failed=5,
        errors=(
            ("Model dependencies present but not selected: clip_l", 3),
            ("CUDA out of memory", 2),
        ),
    )
    text = causes(
        history=history,
        civitai_base_model="SD 1.5",
        header={"checkpoint_architecture": "sdxl_base"},
    )
    assert any("SD 1.5" in line and "'sdxl'" in line for line in text)
    assert any("missing components" in line for line in text)
    assert any("GPU memory" in line for line in text)
    assert text[-1].startswith("Confirm with a Compatibility Probe")


def test_unknown_family_with_a_civitai_label_suggests_probing_that_lineage():
    text = causes(
        family="unknown", civitai_base_model="Pony", header={"checkpoint_architecture": "sdxl_base"}
    )
    assert "Probe with that lineage" in text[0]


def test_no_visible_problem_still_points_at_a_probe():
    text = causes(header={"checkpoint_architecture": "sdxl_base"})
    assert "wrong lineage" in text[0] and len(text) == 2
