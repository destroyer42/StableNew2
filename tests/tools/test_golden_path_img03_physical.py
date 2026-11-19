"""QUAL-921: IMG-03's gated physical lane, its frozen inputs and its pre-dispatch gate.

Deterministic, no display, runtime, model or GPU.  The journey itself (simulated, and its physical code path against
loopback servers, with and without a tampered plan) runs in ``test_golden_path_journeys`` under the ``journey`` marker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from tests.tools.test_golden_path_contracts import LIMITS, authorize, make_probes
from tools.operator_journey.evidence import HOLD, PASS, JourneyEvidence
from tools.operator_journey.golden import definitions as defs
from tools.operator_journey.golden import img03_frozen as f
from tools.operator_journey.golden.frozen import (
    PlanGate,
    PlanMismatch,
    input_problems,
    journey_inputs,
    njr_mismatches,
)
from tools.operator_journey.golden.modes import ModeRefusal, validate_combination
from tools.operator_journey.golden.plan import build_plan, plan_digest, shape_problems

MODEL = "sdxl-base.safetensors"


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    path = tmp_path / MODEL
    path.write_bytes(b"model")
    return path


def edit_target(model_file: Path, **over: Any) -> dict[str, Any]:
    target: dict[str, Any] = {
        "runtime": {
            "kind": "forge",
            "ownership": "external",
            "base_url": "http://127.0.0.1:7860",
            "identity": "forge_webui@d70373ebcf1a",
        },
        "model": {"name": MODEL, "path": str(model_file), "sha256": f"sha:{MODEL}"},
        "settings": {"width": 512, "height": 512, "steps": 8, "seed": f.SEED},
        "job_count": 5,
        "expected_artifacts": 5,
    }
    target.update(over)
    return target


def limits(**over: Any) -> dict[str, Any]:
    return {**LIMITS, "max_jobs": 5, "max_artifacts": 6, **over}


def frozen_plan(tmp_path: Path, target: dict[str, Any], **limit_over: Any) -> dict[str, Any]:
    return build_plan(
        targets={"image-edit": target},
        limits=limits(**limit_over),
        evidence_dir=str(tmp_path),
        probes=make_probes(tmp_path),
    )


def refreeze(plan: dict[str, Any]) -> dict[str, Any]:
    plan = copy.deepcopy(plan)
    plan["digest"] = plan_digest(plan)
    return plan


# --- definition --------------------------------------------------------------------------------------------------------


def test_img03_has_a_physical_lane_with_the_campaign_acceptance() -> None:
    journey = defs.JOURNEYS["image-edit"]
    assert journey.physical is True
    assert journey.physical_acceptance == (
        "source SHA-256",
        "protected region byte-identical",
        "edited region changed",
        "mask geometry frozen in the NJR",
        "new job identity with parent lineage",
        "Compare with Parent shows the right pair",
        "model and runtime identity",
        "peak VRAM, host RAM and commit",
        "teardown evidence",
    )
    joined = " ".join(journey.steps)
    assert "Extend Canvas" in joined and "Regenerate with Changes" in joined and "Replay" in joined
    # every other advanced journey stays simulated-only
    assert [j.key for j in defs.select("advanced") if j.physical] == ["image-edit"]


def test_alignment_and_size_rules_match_the_product() -> None:
    from src.pipeline import outpaint_canvas

    assert f._ALIGNMENT == outpaint_canvas.ALIGNMENT and f._MAX_SIDE == outpaint_canvas.MAX_SIDE


# --- frozen inputs -----------------------------------------------------------------------------------------------------


def test_build_plan_freezes_every_operator_input_and_the_plan_is_valid(
    tmp_path, model_file
) -> None:
    plan = frozen_plan(tmp_path, edit_target(model_file))
    inputs = plan["targets"]["image-edit"]["inputs"]
    assert inputs == journey_inputs("image-edit") == f.default_inputs()
    assert inputs["optional_steps"] == ["outpaint", "regenerate", "replay"]
    assert shape_problems(plan) == []


def test_the_plan_values_override_the_journey_defaults(tmp_path, model_file) -> None:
    chosen = {"edit_prompt": "a boat", "optional_steps": ["replay"], "regenerate_seed": 9}
    plan = frozen_plan(
        tmp_path, edit_target(model_file, job_count=3, expected_artifacts=3, inputs=chosen)
    )
    target = plan["targets"]["image-edit"]
    resolved = f.resolved_inputs(target)
    assert resolved["edit_prompt"] == "a boat" and resolved["regenerate_seed"] == 9
    assert resolved["outpaint_prompt"] == f.OUTPAINT_PROMPT  # unbound keys keep the frozen defaults
    assert f.selected_steps(resolved) == ("replay",) and f.expected_job_count(resolved) == 3
    assert f.resolved_settings(target) == {"width": 512, "height": 512, "steps": 8, "seed": f.SEED}
    assert shape_problems(plan) == []


def test_steps_are_selected_in_their_fixed_order() -> None:
    assert f.selected_steps({"optional_steps": ["replay", "outpaint"]}) == ("outpaint", "replay")
    assert f.selected_steps({"optional_steps": []}) == ()
    assert f.expected_job_count({"optional_steps": []}) == 2


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda t: t.update(runtime={**t["runtime"], "kind": "comfy"}), "Forge only"),
        (lambda t: t.update(job_count=4), "job_count 4 != 5"),
        (lambda t: t.update(expected_artifacts=9), "expected_artifacts 9 != 5"),
        (lambda t: t["settings"].pop("seed"), "whole-number settings ['seed']"),
        (
            lambda t: t["inputs"].update(optional_steps=["outpaint", "inpaint"]),
            "unknown steps ['inpaint']",
        ),
        (lambda t: t["inputs"].update(optional_steps=["replay", "replay"]), "lists a step twice"),
        (lambda t: t["inputs"].update(optional_steps="replay"), "optional_steps must be a list"),
        (
            lambda t: t["inputs"].update(
                outpaint_extents={"left": 0, "right": 12, "top": 0, "bottom": 0}
            ),
            "multiple of 8",
        ),
        (
            lambda t: t["inputs"].update(
                outpaint_extents={"left": 0, "right": 0, "top": 0, "bottom": 0}
            ),
            "extend no side",
        ),
        (lambda t: t["inputs"].update(outpaint_extents={"right": 8}), "must name exactly"),
        (
            lambda t: t["inputs"].update(
                outpaint_extents={"left": 0, "right": 640, "top": 0, "bottom": 0}
            ),
            "exceeds max_width",
        ),
        (lambda t: t["inputs"].update(regenerate_seed=f.SEED), "equals the source seed"),
        (lambda t: t["inputs"].update(regenerate_seed=-1), "regenerate_seed must be"),
        (lambda t: t["inputs"].update(edit_denoise=0), "edit_denoise must be"),
        (lambda t: t["inputs"].update(mask_strokes=[[0.1, 0.1, 1.5, 0.2]]), "mask_strokes[0]"),
        (lambda t: t["inputs"].update(mask_strokes=[[0.2, 0.2, 0.2, 0.2]]), "has no length"),
        (lambda t: t["inputs"].update(mask_strokes=[]), "1 to 8 strokes"),
        (lambda t: t["inputs"].update(edit_prompt=""), "plan inputs missing: edit_prompt"),
        (lambda t: t["inputs"].update(regenerate_prompt_suffix="  "), "regenerate_prompt_suffix"),
        (lambda t: t.pop("inputs"), "does not bind the operator inputs"),
        (lambda t: t["model"].pop("sha256"), "SHA-256 identity"),
    ],
)
def test_a_malformed_image_edit_target_is_a_shape_problem(
    tmp_path, model_file, change, expected
) -> None:
    plan = frozen_plan(tmp_path, edit_target(model_file))
    change(plan["targets"]["image-edit"])
    problems = " | ".join(shape_problems(refreeze(plan)))
    assert expected in problems, problems


def test_a_plan_target_for_a_journey_without_a_physical_lane_is_refused(
    tmp_path, model_file
) -> None:
    plan = frozen_plan(tmp_path, edit_target(model_file))
    plan["targets"]["storyboard"] = copy.deepcopy(plan["targets"]["image-edit"])
    assert any("no physical lane: storyboard" in p for p in shape_problems(refreeze(plan)))


def test_input_problems_are_reported_with_the_journey_key(model_file) -> None:
    target = edit_target(model_file, inputs={**f.default_inputs(), "optional_steps": ["teleport"]})
    assert input_problems("image-edit", target) == [
        "image-edit: optional_steps has unknown steps ['teleport'] (choose from ['outpaint', 'regenerate', 'replay'])"
    ]


# --- the pre-dispatch gate ---------------------------------------------------------------------------------------------


def _njr(
    *,
    prompt: str,
    seed: int = f.SEED,
    parent: str | None = None,
    img2img: Any = None,
    replay: bool = False,
):
    config: dict[str, Any] = {
        "model": MODEL,
        "width": 512,
        "height": 512,
        "steps": 8,
        "seed": seed,
        "prompt": prompt,
    }
    if img2img is not None:
        config["img2img"] = img2img
    return {
        "source": {"parent_job_id": parent},
        "workload": {
            "positive_prompt": prompt,
            "negative_prompt": "x, blurry, low quality",
            "config": config,
        },
        "provenance": {"metadata": {"replay": True} if replay else {}},
    }


def _edit_stage(**over: Any) -> dict[str, Any]:
    stage = {
        "denoising_strength": f.EDIT_DENOISE,
        "image_edit_inputs": {
            "mask": {"sha256": "a" * 64},
            "source": {"width": 512, "height": 512},
        },
    }
    stage.update(over)
    return stage


def _outpaint_stage(extents: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "edit_operation": "outpaint",
        "image_edit_inputs": {
            "mask": {"sha256": "b" * 64},
            "original": {"width": 512, "height": 512},
            "outpaint": {"extents": extents or dict(f.DEFAULT_OUTPAINT_EXTENTS)},
        },
    }


def good_njrs() -> dict[str, dict[str, Any]]:
    return {
        "source": _njr(prompt=f.PROMPT),
        "masked_edit": _njr(prompt=f.EDIT_PROMPT, parent="p", img2img=_edit_stage()),
        "outpaint": _njr(prompt=f.OUTPAINT_PROMPT, parent="p", img2img=_outpaint_stage()),
        "regenerate": _njr(
            prompt=f.PROMPT + f.REGENERATE_SUFFIX, seed=f.REGENERATE_SEED, parent="p"
        ),
        "replay": _njr(prompt=f.PROMPT, parent="p", replay=True),
    }


def test_every_frozen_step_agrees_with_the_plan(model_file) -> None:
    target = edit_target(model_file, inputs=f.default_inputs())
    njrs = good_njrs()
    assert [f.classify(n) for n in njrs.values()] == [
        "txt2img",
        "masked_edit",
        "outpaint",
        "txt2img",
        "replay",
    ]
    for name, njr in njrs.items():
        assert njr_mismatches("image-edit", target, {"normalized_job": njr}) == [], name


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        ("source", lambda n: n["workload"].update(positive_prompt="other"), "prompt: plan"),
        ("source", lambda n: n["workload"]["config"].update(steps=9), "steps: plan 8 != NJR 9"),
        (
            "source",
            lambda n: n["workload"]["config"].update(model="other.safetensors"),
            "model: plan",
        ),
        (
            "source",
            lambda n: n["workload"]["config"].update(seed=1),
            "neither the frozen source seed",
        ),
        (
            "masked_edit",
            lambda n: n["workload"].update(positive_prompt="a cat"),
            "edit prompt: plan",
        ),
        (
            "masked_edit",
            lambda n: n["workload"]["config"]["img2img"].update(denoising_strength=0.9),
            "edit denoise",
        ),
        (
            "masked_edit",
            lambda n: n["workload"]["config"]["img2img"]["image_edit_inputs"].update(mask={}),
            "no mask identity",
        ),
        ("masked_edit", lambda n: n["source"].update(parent_job_id=None), "records no parent job"),
        (
            "outpaint",
            lambda n: n["workload"]["config"].update(
                img2img=_outpaint_stage({"left": 8, "right": 0, "top": 0, "bottom": 0})
            ),
            "outpaint extents",
        ),
        ("outpaint", lambda n: n["workload"].update(positive_prompt="a cat"), "outpaint prompt"),
        (
            "regenerate",
            lambda n: n["workload"].update(positive_prompt=f.PROMPT),
            "prompt change is not in the NJR",
        ),
        ("regenerate", lambda n: n["source"].update(parent_job_id=None), "records no parent job"),
        ("replay", lambda n: n["workload"]["config"].update(seed=f.REGENERATE_SEED), "replay seed"),
    ],
)
def test_any_disagreement_with_the_frozen_step_is_reported(
    model_file, name, mutate, expected
) -> None:
    target = edit_target(model_file, inputs=f.default_inputs())
    njr = good_njrs()[name]
    mutate(njr)
    problems = " | ".join(njr_mismatches("image-edit", target, njr))
    assert expected in problems, problems


@pytest.mark.parametrize("step", ["outpaint", "regenerate", "replay"])
def test_a_step_the_plan_does_not_select_is_declined(model_file, step) -> None:
    inputs = {**f.default_inputs(), "optional_steps": [s for s in f.OPTIONAL_STEPS if s != step]}
    target = edit_target(model_file, inputs=inputs, job_count=4, expected_artifacts=4)
    problems = njr_mismatches("image-edit", target, good_njrs()[step])
    assert any(f"does not select the {step} step" in p for p in problems), problems


class _Record:
    def __init__(self, njr: dict[str, Any], job_id: str) -> None:
        self._njr, self.job_id = njr, job_id

    def to_dict(self) -> dict[str, Any]:
        return {"normalized_job": self._njr}


class _Service:
    def __init__(self) -> None:
        self.queued: list[str] = []

    def submit_njrs(self, records: Any, *args: Any, **kwargs: Any) -> int:
        self.queued.extend(r.job_id for r in records)
        return len(self.queued)


def test_the_plan_gate_admits_the_frozen_jobs_and_declines_a_sixth(model_file) -> None:
    target = edit_target(model_file, inputs=f.default_inputs())
    service = _Service()
    gate = PlanGate("image-edit", target)
    gate.install(service)
    for index, njr in enumerate(good_njrs().values()):
        service.submit_njrs([_Record(njr, f"j{index}")])
    assert service.queued == ["j0", "j1", "j2", "j3", "j4"] and gate.verified == 5
    with pytest.raises(PlanMismatch, match="exceed the frozen 5"):
        service.submit_njrs([_Record(good_njrs()["replay"], "j5")])
    assert service.queued == ["j0", "j1", "j2", "j3", "j4"]


def test_the_plan_gate_declines_a_disagreeing_edit_before_anything_is_queued(model_file) -> None:
    target = edit_target(model_file, inputs={**f.default_inputs(), "edit_prompt": "frozen edit"})
    service = _Service()
    gate = PlanGate("image-edit", target)
    gate.install(service)
    with pytest.raises(PlanMismatch, match="edit prompt"):
        service.submit_njrs([_Record(good_njrs()["masked_edit"], "j1")])
    assert service.queued == [] and gate.mismatches


# --- physical refusal and dispatch -------------------------------------------------------------------------------------


def test_physical_image_edit_is_refused_under_pytest_and_in_ci(tmp_path) -> None:
    from tools.operator_journey.golden.suite import run_suite

    with pytest.raises(ModeRefusal, match="refused under pytest"):
        run_suite(
            journeys_choice="image-edit",
            mode="physical",
            driver="windows",
            plan_path=tmp_path / "plan.json",
            evidence_root=tmp_path,
            env={},
        )
    with pytest.raises(ModeRefusal, match="refused in CI|never used in CI"):
        validate_combination(mode="physical", driver="windows", plan="p.json", env={"CI": "true"})
    with pytest.raises(ModeRefusal, match="requires --plan"):
        validate_combination(mode="physical", driver="windows", plan=None, env={})
    assert not list(tmp_path.iterdir()), "a refused run must create nothing"


def _evidence(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))


def _run_physical(tmp_path: Path, plan_path: Path, executor: Any) -> tuple[str, Path]:
    from tools.operator_journey.golden.physical import run_physical

    return run_physical(
        plan_path,
        journeys=[defs.JOURNEYS["image-edit"]],
        evidence_root=tmp_path / "evidence",
        confirm=lambda _prompt: pytest.fail("no launch prompt may be reached"),
        executor=executor,
        probes=make_probes(tmp_path),
    )


def test_without_a_plan_the_physical_lane_holds_and_runs_nothing(tmp_path) -> None:
    verdict, run_dir = _run_physical(
        tmp_path,
        tmp_path / "missing.json",
        lambda *_: pytest.fail("nothing may run without a plan"),
    )
    assert verdict == HOLD and "cannot be read" in _evidence(run_dir)["outcomes"]["reason"]
    assert _evidence(run_dir)["outcomes"]["physical_execution"] == "NOT RUN"


def test_an_unauthorized_or_misnamed_plan_holds_and_runs_nothing(tmp_path, model_file) -> None:
    plan = frozen_plan(tmp_path, edit_target(model_file))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")
    verdict, run_dir = _run_physical(tmp_path, path, lambda *_: pytest.fail("unauthorized"))
    assert verdict == HOLD and "not authorized" in _evidence(run_dir)["outcomes"]["reason"]
    # An authorization that covers only other journeys, or names another digest, does not authorize this plan either.
    other_journey = authorize(plan, journeys=("image",))
    other_digest = authorize(plan, journeys=("image-edit",))
    other_digest["authorization"]["plan_digest"] = "0" * 64
    for auth in (other_journey, other_digest):
        path.write_text(json.dumps(auth), "utf-8")
        verdict, run_dir = _run_physical(tmp_path, path, lambda *_: pytest.fail("unauthorized"))
        assert verdict == HOLD and "not authorized" in _evidence(run_dir)["outcomes"]["reason"]


def test_the_physical_executor_dispatches_image_edit_to_img03_with_the_frozen_target(
    tmp_path, model_file, monkeypatch
) -> None:
    from tools.operator_journey.golden import img03, physical, session

    target = frozen_plan(tmp_path, edit_target(model_file))["targets"]["image-edit"]
    captured: dict[str, Any] = {}

    def fake_body_runner(journey_id: str, body: Any, config: Any, **kwargs: Any) -> JourneyEvidence:
        captured.update(journey_id=journey_id, body=body, config=config, kwargs=kwargs)
        return JourneyEvidence(journey_id=journey_id, backend_mode="physical")

    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(session, "run_journey_body", fake_body_runner)
    monkeypatch.setattr(
        physical, "_engine_settings", lambda _t: {"webui_runtime_identity": "forge_webui"}
    )
    monkeypatch.setattr(
        img03, "register_frozen_checkpoint", lambda run, t: calls.append(("register", t))
    )
    monkeypatch.setattr(
        img03,
        "run_img03",
        lambda run, *, simulated=True, physical=None: calls.append(("run", (simulated, physical))),
    )
    monitor = SimpleNamespace(tripped=None)
    physical.real_executor(defs.JOURNEYS["image-edit"], target, monitor, tmp_path)  # type: ignore[arg-type]
    assert captured["journey_id"] == "IMG-03" and captured["kwargs"]["execution_mode"] == "physical"
    assert captured["config"].driver == "windows"
    assert (
        captured["config"].extras["target"] is target
        and captured["config"].extras["journey_key"] == "image-edit"
    )
    captured["body"](object())
    assert calls == [("register", target), ("run", (False, target))]


def test_the_physical_executor_refuses_a_journey_without_a_physical_lane(tmp_path) -> None:
    from tools.operator_journey.golden import physical

    target = {
        "runtime": {
            "kind": "forge",
            "ownership": "external",
            "base_url": "http://x",
            "identity": "i",
        }
    }
    with pytest.raises(ValueError, match="no physical lane"):
        physical.real_executor(
            defs.JOURNEYS["storyboard"], target, SimpleNamespace(tripped=None), tmp_path
        )  # type: ignore[arg-type]


def test_readiness_evaluates_an_image_edit_plan_without_starting_anything(
    tmp_path, model_file
) -> None:
    from tests.tools.test_golden_path_contracts import ctx_for
    from tools.operator_journey.golden.readiness import evaluate_readiness

    probes = make_probes(tmp_path)
    plan = frozen_plan(tmp_path, edit_target(model_file))
    report = evaluate_readiness(plan, ctx_for(probes))
    assert report["verdict"] == PASS, [g for g in report["gates"] if g["state"] != PASS]
    assert report["started_runtime"] is False and report["physical_run_authorized"] is False
    assert {"image-edit:endpoint", "image-edit:runtime_identity"} <= {
        g["id"] for g in report["gates"]
    }


# --- frozen checkpoint registration (physical preparation) ------------------------------------------------------------


def test_registering_a_missing_checkpoint_is_a_hold(tmp_path) -> None:
    from tools.operator_journey.golden.img03 import register_frozen_checkpoint
    from tools.operator_journey.golden.session import JourneyHold

    run = SimpleNamespace(ws=SimpleNamespace(root=tmp_path, state_dir=tmp_path / "state"))
    with pytest.raises(JourneyHold, match="not a file"):
        register_frozen_checkpoint(run, {"model": {"path": str(tmp_path / "absent.safetensors")}})  # type: ignore[arg-type]


def test_registering_writes_only_the_disposable_workspace_and_holds_on_a_wrong_digest(
    tmp_path,
) -> None:
    from tools.operator_journey.golden.img03 import register_frozen_checkpoint
    from tools.operator_journey.golden.session import JourneyHold
    from tools.operator_journey.workspace import OperatorWorkspace

    checkpoint = tmp_path / "elsewhere" / MODEL
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"not a real checkpoint")
    before = sorted(p.name for p in checkpoint.parent.iterdir())
    workspace = OperatorWorkspace(root=tmp_path / "ws", webui_base_url="http://127.0.0.1:9")
    evidence = JourneyEvidence(journey_id="IMG-03", backend_mode="physical")
    with workspace.activate():
        run = SimpleNamespace(ws=workspace, ev=evidence)
        target = {"model": {"name": MODEL, "path": str(checkpoint), "sha256": "0" * 64}}
        with pytest.raises(JourneyHold, match="differs from the plan"):
            register_frozen_checkpoint(run, target)  # type: ignore[arg-type]
        from src.state.workspace_paths import workspace_paths

        cache = json.loads(workspace_paths.asset_registry_cache().read_text(encoding="utf-8"))
    assert (
        sorted(p.name for p in checkpoint.parent.iterdir()) == before
    )  # nothing written beside the model
    entries = cache.get("entries") or {}
    assert [Path(k).name for k in entries] == [MODEL]
    observed = next(
        o["value"] for o in evidence.observations if o["name"] == "frozen_checkpoint_registration"
    )
    assert observed["registry_sha256"] and observed["registry_sha256"] != "0" * 64


# --- pixel measures ----------------------------------------------------------------------------------------------------


def _save(image: Image.Image, path: Path, **info: str) -> Path:
    from PIL import PngImagePlugin

    meta = PngImagePlugin.PngInfo()
    for key, value in info.items():
        meta.add_text(key, value)
    image.save(path, pnginfo=meta)
    return path


def test_region_preservation_separates_the_protected_and_the_edited_region(tmp_path) -> None:
    source = _save(Image.new("RGB", (64, 64), (10, 20, 30)), tmp_path / "s.png")
    mask_img = Image.new("L", (64, 64), 0)
    mask_img.paste(255, (20, 20, 30, 30))
    mask = _save(mask_img, tmp_path / "m.png")
    composited = Image.new("RGB", (64, 64), (10, 20, 30))
    composited.paste((200, 0, 0), (20, 20, 30, 30))
    good = f.region_preservation(source, _save(composited, tmp_path / "good.png"), mask, margin=4)
    assert good["protected_identical"] and good["edited_region_changed"]
    assert good["edited_changed_pixels"] == good["edited_pixels"] == 100
    composited.putpixel((1, 1), (11, 20, 30))  # one protected pixel off by one level
    leaked = f.region_preservation(source, _save(composited, tmp_path / "bad.png"), mask, margin=4)
    assert not leaked["protected_identical"] and leaked["protected_changed_pixels"] == 1
    composited.putpixel((1, 1), (10, 20, 30))
    composited.putpixel((33, 25), (0, 0, 0))  # inside the blur margin: not counted as protected
    feathered = f.region_preservation(source, _save(composited, tmp_path / "f.png"), mask, margin=4)
    assert feathered["protected_identical"]
    assert f.mask_bbox(mask) == (20, 20, 30, 30)
    unchanged = f.region_preservation(source, source, mask, margin=4)
    assert not unchanged["edited_region_changed"]
    other = _save(Image.new("RGB", (32, 32)), tmp_path / "small.png")
    assert f.region_preservation(source, other, mask, margin=4)["comparable"] is False


def test_outpaint_preservation_uses_the_products_canvas(tmp_path) -> None:
    from src.pipeline.outpaint_canvas import Extents, prepare_outpaint_canvas

    original = Image.new("RGB", (64, 64), (5, 6, 7))
    original.paste((90, 80, 70), (10, 10, 30, 30))
    original_path = _save(original, tmp_path / "o.png")
    canvas = prepare_outpaint_canvas(original_path.read_bytes(), Extents(right=16, bottom=8))
    expanded_path = tmp_path / "e.png"
    expanded_path.write_bytes(canvas.expanded_png)
    bbox = canvas.record["original_bbox"]
    result = Image.new("RGB", (80, 72), (250, 250, 250))
    result.paste(original, (0, 0))
    measure = f.outpaint_preservation(
        original_path, expanded_path, _save(result, tmp_path / "r.png"), bbox
    )
    assert measure["original_identical"] and measure["exterior_changed_pixels"] > 0
    result.putpixel((5, 5), (0, 0, 0))
    broken = f.outpaint_preservation(
        original_path, expanded_path, _save(result, tmp_path / "r2.png"), bbox
    )
    assert not broken["original_identical"]


def test_pixel_identity_ignores_file_metadata(tmp_path) -> None:
    image = Image.new("RGB", (16, 16), (1, 2, 3))
    a = _save(image, tmp_path / "a.png", job="one")
    b = _save(image, tmp_path / "b.png", job="two")
    assert a.read_bytes() != b.read_bytes() and f.pixels_identical(a, b)
    image.putpixel((0, 0), (1, 2, 4))
    assert not f.pixels_identical(a, _save(image, tmp_path / "c.png"))


def test_readiness_mode_reaches_the_plan_for_image_edit(tmp_path, monkeypatch) -> None:
    """IMG-03 is no longer refused for --mode readiness: the frozen plan's own gates decide."""

    from tools.operator_journey.golden import suite

    seen: list[Path] = []
    monkeypatch.setattr(
        suite, "run_readiness", lambda plan_path, **_: seen.append(plan_path) or (HOLD, None)
    )
    verdict, _ = suite.run_suite(
        journeys_choice="image-edit",
        mode="readiness",
        driver="tk",
        plan_path=tmp_path / "plan.json",
        evidence_root=tmp_path,
        env={},
    )
    assert verdict == HOLD and seen == [tmp_path / "plan.json"]
