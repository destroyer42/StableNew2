"""IMG-03's frozen operator inputs, their validation, the pre-dispatch NJR comparison and pixel measures (QUAL-921).

Pure functions (no Tk, no application import at module load), shared by the journey (``img03``), the plan
(``plan.shape_problems``) and the frozen-plan gate (``frozen.njr_mismatches``).  A physical run reads every value the
operator types from the plan target's ``inputs`` and ``settings``; a simulated run uses ``default_inputs()``.

The masked edit always runs.  Three further steps are selected by ``inputs.optional_steps`` (any subset, in this order):

* ``outpaint``: Review's Extend Canvas on the source image, queued as one frozen img2img outpaint;
* ``regenerate``: History's Regenerate with Changes on the source job, with a new seed and a prompt suffix;
* ``replay``: History's Replay Job on the source job, compared with its recorded parent.

Every selected step submits exactly one job, so a target's ``job_count`` is ``2 + len(optional_steps)``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

PACK_NAME = "golden_img03"
PROMPT = "golden path edit, a lighthouse on a rocky coast, watercolour"
NEGATIVE = "blurry, low quality"
EDIT_PROMPT = "a bright red buoy floating near the rocks"
EDIT_DENOISE = 0.5
OUTPAINT_PROMPT = "more rocky shoreline and calm sea"
REGENERATE_SEED = 404404
REGENERATE_SUFFIX = ", at golden hour"
SEED = 303303
STEPS = 8
SIZE = 512

OPTIONAL_STEPS = ("outpaint", "regenerate", "replay")
#: Two crossing strokes, each ``[x0, y0, x1, y1]`` as fractions of the mask editor's visible canvas.
DEFAULT_MASK_STROKES = ((0.35, 0.42, 0.65, 0.58), (0.35, 0.58, 0.65, 0.42))
DEFAULT_OUTPAINT_EXTENTS = {"left": 0, "right": 128, "top": 0, "bottom": 0}
_SIDES = ("left", "right", "top", "bottom")
_ALIGNMENT = 8  # src.pipeline.outpaint_canvas.ALIGNMENT; a parity test pins the two
_MAX_SIDE = 4096


def default_inputs() -> dict[str, Any]:
    """The fixed inputs of the journey; ``build_plan`` freezes them into an ``image-edit`` target."""

    return {
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE,
        "pack_name": PACK_NAME,
        "edit_prompt": EDIT_PROMPT,
        "edit_denoise": EDIT_DENOISE,
        "mask_strokes": [list(stroke) for stroke in DEFAULT_MASK_STROKES],
        "optional_steps": list(OPTIONAL_STEPS),
        "outpaint_prompt": OUTPAINT_PROMPT,
        "outpaint_extents": dict(DEFAULT_OUTPAINT_EXTENTS),
        "regenerate_seed": REGENERATE_SEED,
        "regenerate_prompt_suffix": REGENERATE_SUFFIX,
    }


def resolved_inputs(physical: Mapping[str, Any] | None) -> dict[str, Any]:
    """The defaults overlaid with the plan's frozen inputs (the plan wins for every key it binds)."""

    return {**default_inputs(), **dict((physical or {}).get("inputs") or {})}


def resolved_settings(physical: Mapping[str, Any] | None) -> dict[str, int]:
    settings = dict((physical or {}).get("settings") or {})
    return {
        "width": int(settings.get("width", SIZE)),
        "height": int(settings.get("height", SIZE)),
        "steps": int(settings.get("steps", STEPS)),
        "seed": int(settings.get("seed", SEED)),
    }


def selected_steps(inputs: Mapping[str, Any]) -> tuple[str, ...]:
    chosen = inputs.get("optional_steps")
    chosen = list(chosen) if isinstance(chosen, (list, tuple)) else []
    return tuple(step for step in OPTIONAL_STEPS if step in chosen)


def expected_job_count(inputs: Mapping[str, Any]) -> int:
    """Source txt2img + masked edit + one job per selected optional step."""

    return 2 + len(selected_steps(inputs))


def outpaint_size(settings: Mapping[str, Any], inputs: Mapping[str, Any]) -> tuple[int, int]:
    extents = inputs.get("outpaint_extents") or {}
    return (
        int(settings.get("width", SIZE))
        + int(extents.get("left", 0))
        + int(extents.get("right", 0)),
        int(settings.get("height", SIZE))
        + int(extents.get("top", 0))
        + int(extents.get("bottom", 0)),
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def input_problems(target: Mapping[str, Any]) -> list[str]:
    """Malformed operator inputs of an ``image-edit`` target (presence is checked by ``frozen.input_problems``)."""

    inputs = target.get("inputs") or {}
    settings = target.get("settings") or {}
    problems: list[str] = []
    chosen = inputs.get("optional_steps")
    if not isinstance(chosen, (list, tuple)):
        problems.append("optional_steps must be a list")
    else:
        unknown = [s for s in chosen if s not in OPTIONAL_STEPS]
        if unknown:
            problems.append(
                f"optional_steps has unknown steps {unknown} (choose from {list(OPTIONAL_STEPS)})"
            )
        if len(set(map(str, chosen))) != len(chosen):
            problems.append("optional_steps lists a step twice")
    for name in ("prompt", "edit_prompt", "outpaint_prompt"):
        if not str(inputs.get(name) or "").strip():
            problems.append(f"{name} must be non-empty text")
    denoise = inputs.get("edit_denoise")
    if not (_is_number(denoise) and 0 < float(denoise) <= 1):
        problems.append(f"edit_denoise must be a number in (0, 1], not {denoise!r}")
    strokes = inputs.get("mask_strokes")
    if not (isinstance(strokes, (list, tuple)) and 1 <= len(strokes) <= 8):
        problems.append("mask_strokes must list 1 to 8 strokes")
    else:
        for index, stroke in enumerate(strokes):
            if not (
                isinstance(stroke, (list, tuple))
                and len(stroke) == 4
                and all(_is_number(v) and 0.0 <= float(v) <= 1.0 for v in stroke)
            ):
                problems.append(
                    f"mask_strokes[{index}] must be [x0, y0, x1, y1] fractions of the canvas in [0, 1]"
                )
            elif (stroke[0], stroke[1]) == (stroke[2], stroke[3]):
                problems.append(f"mask_strokes[{index}] has no length")
    extents = inputs.get("outpaint_extents")
    if not isinstance(extents, Mapping) or set(extents) != set(_SIDES):
        problems.append(f"outpaint_extents must name exactly {list(_SIDES)}")
    else:
        for side in _SIDES:
            value = extents[side]
            if not (_is_int(value) and value >= 0 and value % _ALIGNMENT == 0):
                problems.append(
                    f"outpaint_extents.{side} must be a non-negative multiple of {_ALIGNMENT}, not {value!r}"
                )
        if isinstance(chosen, (list, tuple)) and "outpaint" in chosen:
            if not any(_is_int(extents[s]) and extents[s] > 0 for s in _SIDES):
                problems.append("outpaint is selected but outpaint_extents extend no side")
    regen_seed = inputs.get("regenerate_seed")
    if not (_is_int(regen_seed) and regen_seed >= 0):
        problems.append(f"regenerate_seed must be a non-negative whole number, not {regen_seed!r}")
    elif "seed" in settings and regen_seed == settings.get("seed"):
        problems.append(
            "regenerate_seed equals the source seed (Regenerate with Changes must change the recipe)"
        )
    if not str(inputs.get("regenerate_prompt_suffix") or "").strip():
        problems.append("regenerate_prompt_suffix must be non-empty text")
    return problems


def target_problems(target: Mapping[str, Any], limits: Mapping[str, Any]) -> list[str]:
    """Plan-level consistency of an ``image-edit`` target (runtime, frozen source settings, job budget, geometry)."""

    problems: list[str] = []
    runtime = target.get("runtime") or {}
    if runtime.get("kind") != "forge":
        problems.append(
            "image-edit: masked edits and outpainting run on Forge only (runtime.kind 'forge')"
        )
    settings = target.get("settings") or {}
    missing = [k for k in ("width", "height", "steps", "seed") if not _is_int(settings.get(k))]
    if missing:
        problems.append(f"image-edit: the frozen source job needs whole-number settings {missing}")
        return problems
    inputs = target.get("inputs") or {}
    if not isinstance(inputs.get("optional_steps"), (list, tuple)):
        return problems  # reported by input_problems
    expected = expected_job_count(inputs)
    for key in ("job_count", "expected_artifacts"):
        if int(target.get(key, 0) or 0) != expected:
            problems.append(
                f"image-edit: {key} {target.get(key)!r} != {expected} (source, masked edit and "
                f"{len(selected_steps(inputs))} optional step(s), one job and one image each)"
            )
    if "outpaint" in selected_steps(inputs) and isinstance(inputs.get("outpaint_extents"), Mapping):
        try:
            width, height = outpaint_size(settings, inputs)
        except (TypeError, ValueError):
            return problems  # reported by input_problems
        for value, limit in ((width, "max_width"), (height, "max_height")):
            if limits.get(limit) and value > limits[limit]:
                problems.append(
                    f"image-edit: outpaint canvas {width}x{height} exceeds {limit} {limits[limit]}"
                )
        if max(width, height) > _MAX_SIDE:
            problems.append(f"image-edit: outpaint canvas {width}x{height} exceeds {_MAX_SIDE} px")
    return problems


# --- the pre-dispatch comparison (``frozen.PlanGate`` may only decline) ------------------------------------------------


def _dig(blob: Any, *path: str) -> Any:
    for part in path:
        if not isinstance(blob, Mapping):
            return None
        blob = blob.get(part)
    return blob


def _same(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def classify(job: Mapping[str, Any]) -> str:
    """``masked_edit``, ``outpaint``, ``replay`` or ``txt2img`` (a source or a regeneration, told apart by seed)."""

    stage = _dig(job, "workload", "config", "img2img")
    edit = stage.get("image_edit_inputs") if isinstance(stage, Mapping) else None
    if isinstance(edit, Mapping):
        return (
            "outpaint"
            if ("outpaint" in edit or stage.get("edit_operation") == "outpaint")
            else "masked_edit"
        )
    if _dig(job, "provenance", "metadata", "replay") is True:
        return "replay"
    return "txt2img"


def njr_mismatches(target: Mapping[str, Any], job: Mapping[str, Any]) -> list[str]:
    """Every way one NJR about to be queued disagrees with the frozen ``image-edit`` target; empty when it agrees."""

    inputs = resolved_inputs(target)
    settings = target.get("settings") or {}
    chosen = selected_steps(inputs)
    config = _dig(job, "workload", "config") or {}
    problems: list[str] = []

    def expect(name: str, wanted: Any, seen: Any) -> None:
        if wanted is not None and not _same(wanted, seen):
            problems.append(f"{name}: plan {wanted!r} != NJR {seen!r}")

    wanted_model = str((target.get("model") or {}).get("name") or "")
    seen_model = str(config.get("model") or "")
    if wanted_model and Path(wanted_model).stem.lower() not in seen_model.lower():
        problems.append(f"model: plan {wanted_model!r} != NJR {seen_model!r}")
    prompt = str(_dig(job, "workload", "positive_prompt") or config.get("prompt") or "")
    parent = _dig(job, "source", "parent_job_id")
    kind = classify(job)
    if kind in ("masked_edit", "outpaint"):
        stage = config["img2img"]
        edit = stage["image_edit_inputs"]
        if not parent:
            problems.append(f"{kind}: the NJR records no parent job")
        if kind == "outpaint":
            if "outpaint" not in chosen:
                problems.append("outpaint: the plan does not select the outpaint step")
            if not prompt.startswith(str(inputs["outpaint_prompt"])):
                problems.append(
                    f"outpaint prompt: plan {inputs['outpaint_prompt']!r} != NJR {prompt!r}"
                )
            record = edit.get("outpaint") or {}
            if dict(record.get("extents") or {}) != dict(inputs["outpaint_extents"]):
                problems.append(
                    f"outpaint extents: plan {inputs['outpaint_extents']!r} != NJR {record.get('extents')!r}"
                )
            original = edit.get("original") or {}
            expect("outpaint original width", settings.get("width"), original.get("width"))
            expect("outpaint original height", settings.get("height"), original.get("height"))
        else:
            if not prompt.startswith(str(inputs["edit_prompt"])):
                problems.append(f"edit prompt: plan {inputs['edit_prompt']!r} != NJR {prompt!r}")
            expect("edit denoise", inputs.get("edit_denoise"), stage.get("denoising_strength"))
            mask = edit.get("mask") or {}
            if not mask.get("sha256"):
                problems.append("masked edit: the NJR freezes no mask identity")
            source = edit.get("source") or {}
            expect("edit source width", settings.get("width"), source.get("width"))
            expect("edit source height", settings.get("height"), source.get("height"))
        return problems
    for name in ("width", "height", "steps"):
        expect(name, settings.get(name), config.get(name))
    if inputs.get("prompt") and not prompt.startswith(str(inputs["prompt"])):
        problems.append(f"prompt: plan {inputs['prompt']!r} != NJR {prompt!r}")
    negative = str(_dig(job, "workload", "negative_prompt") or config.get("negative_prompt") or "")
    if inputs.get("negative_prompt") and str(inputs["negative_prompt"]) not in negative:
        problems.append("negative_prompt: the plan's negative prompt is not in the NJR")
    seed = config.get("seed")
    if kind == "replay":
        if "replay" not in chosen:
            problems.append("replay: the plan does not select the replay step")
        if not parent:
            problems.append("replay: the NJR records no parent job")
        expect("replay seed", settings.get("seed"), seed)
    elif _same(seed, settings.get("seed")) and not parent:
        pass  # the frozen source job
    elif _same(seed, inputs.get("regenerate_seed")):
        if "regenerate" not in chosen:
            problems.append("regenerate: the plan does not select the regenerate step")
        if not parent:
            problems.append("regenerate: the NJR records no parent job")
        if str(inputs["regenerate_prompt_suffix"]) not in prompt:
            problems.append("regenerate: the frozen prompt change is not in the NJR prompt")
    else:
        problems.append(
            f"seed: NJR {seed!r} is neither the frozen source seed {settings.get('seed')!r} (without a parent) nor "
            f"the frozen regenerate seed {inputs.get('regenerate_seed')!r}"
        )
    return problems


# --- pixel measures (read-only; the journey records them as evidence) --------------------------------------------------


def _changed(a: Any, b: Any) -> Any:
    """An ``L`` image that is 255 wherever any channel of two same-sized RGB images differs, else 0."""

    from PIL import ImageChops

    r, g, b_ = ImageChops.difference(a, b).split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b_).point(lambda v: 255 if v else 0)


def _count(binary: Any) -> int:
    return int(binary.histogram()[255])


def mask_bbox(mask_path: Path) -> tuple[int, int, int, int] | None:
    from PIL import Image

    with Image.open(mask_path) as mask:
        return mask.convert("L").point(lambda v: 255 if v else 0).getbbox()


def region_preservation(
    source_path: Path, result_path: Path, mask_path: Path, *, margin: int
) -> dict[str, Any]:
    """Compare a masked edit with its source: the protected region and the edited region.

    The protected region is every pixel outside the mask's bounding box grown by ``margin`` (the backend's blur can
    feather the composite just past the painted pixels).  ``protected_identical`` holds when no protected pixel changed;
    ``edited_changed_pixels`` counts the painted pixels whose value changed.
    """

    from PIL import Image

    with Image.open(source_path) as s, Image.open(result_path) as r, Image.open(mask_path) as m:
        source, result = s.convert("RGB"), r.convert("RGB")
        mask = m.convert("L").point(lambda v: 255 if v else 0)
    if source.size != result.size or mask.size != source.size:
        return {
            "comparable": False,
            "detail": f"sizes differ: source {source.size}, result {result.size}, mask {mask.size}",
        }
    changed = _changed(source, result)
    box = mask.getbbox()
    protected = Image.new("L", source.size, 255)
    if box is not None:
        width, height = source.size
        grown = (
            max(0, box[0] - margin),
            max(0, box[1] - margin),
            min(width, box[2] + margin),
            min(height, box[3] + margin),
        )
        protected.paste(0, grown)
    from PIL import ImageChops

    protected_changed = _count(ImageChops.darker(changed, protected))
    edited_changed = _count(ImageChops.darker(changed, mask))
    return {
        "comparable": True,
        "size": list(source.size),
        "mask_bbox": list(box) if box else None,
        "margin": margin,
        "protected_pixels": _count(protected),
        "protected_changed_pixels": protected_changed,
        "protected_identical": protected_changed == 0 and _count(protected) > 0,
        "edited_pixels": _count(mask),
        "edited_changed_pixels": edited_changed,
        "edited_region_changed": edited_changed > 0,
    }


def pixels_identical(a_path: Path, b_path: Path) -> bool:
    """Whether two images decode to the same size and RGB pixels (file metadata is ignored)."""

    from PIL import Image

    with Image.open(a_path) as a, Image.open(b_path) as b:
        first, second = a.convert("RGB"), b.convert("RGB")
    return first.size == second.size and _count(_changed(first, second)) == 0


def outpaint_preservation(
    original_path: Path, expanded_source_path: Path, result_path: Path, bbox: Mapping[str, int]
) -> dict[str, Any]:
    """The original's pixels at their frozen bounding box, and whether the generated exterior changed.

    The original is normalized exactly as the product normalizes it before building the canvas.
    """

    from PIL import Image, ImageChops

    from src.pipeline.outpaint_canvas import normalize_original

    original = normalize_original(Path(original_path).read_bytes())
    with Image.open(result_path) as r, Image.open(expanded_source_path) as e:
        result, expanded = r.convert("RGB"), e.convert("RGB")
    box = (int(bbox["left"]), int(bbox["top"]), int(bbox["right"]), int(bbox["bottom"]))
    if result.size != expanded.size:
        return {"comparable": False, "detail": f"result {result.size} != canvas {expanded.size}"}
    inner = result.crop(box)
    original_identical = inner.size == original.size and _count(_changed(inner, original)) == 0
    exterior = Image.new("L", result.size, 255)
    exterior.paste(0, box)
    exterior_changed = _count(ImageChops.darker(_changed(result, expanded), exterior))
    return {
        "comparable": True,
        "size": list(result.size),
        "original_bbox": list(box),
        "original_identical": original_identical,
        "exterior_pixels": _count(exterior),
        "exterior_changed_pixels": exterior_changed,
    }


__all__ = [
    "OPTIONAL_STEPS",
    "classify",
    "default_inputs",
    "expected_job_count",
    "input_problems",
    "mask_bbox",
    "njr_mismatches",
    "outpaint_preservation",
    "pixels_identical",
    "region_preservation",
    "resolved_inputs",
    "resolved_settings",
    "selected_steps",
    "target_problems",
]
