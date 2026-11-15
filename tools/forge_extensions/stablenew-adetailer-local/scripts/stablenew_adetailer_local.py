"""StableNew companion for the pinned ADetailer-Neo: localized face/hand refinement with mask evidence.

Installed by StableNew's managed Forge bootstrap into ``data/extensions/stablenew-adetailer-local`` and verified there
by content hash (``config/managed_forge_runtime.json``). It runs only inside the Forge process and adds two routes:

* ``GET  /stablenew/v1/adetailer/localized/version``
* ``POST /stablenew/v1/adetailer/localized``

The POST runs the pinned extension's own per-pass routine (detection, ratio/top-k filtering, sorting, dilation, offset,
merge, then one masked inpaint per mask) directly on the supplied image. There is no outer img2img generation: the
processing object built here only carries the settings that routine reads and is never sampled. Nothing in the pinned
extension is modified; its routine is called with a thin stand-in for ``self`` that records the masks it produced and
applies the request's settings overrides to each masked inpaint. When no mask survives, nothing is sampled and no image
is returned.

Contract: ``stablenew.adetailer-localized.v1`` (StableNew side: ``src/pipeline/adetailer_localized.py``).
"""

from __future__ import annotations

import base64
import hashlib
import io
from contextlib import closing
from typing import Any

from modules import script_callbacks

COMPANION_VERSION = "1.0.0"
SCHEMA = "stablenew.adetailer-localized.v1"
ROUTE = "/stablenew/v1/adetailer/localized"
MAX_PASSES = 2
_INVERTING_MERGE_MODE = "Merge and Invert"

_default_script_args: list[Any] | None = None


def _pixel_sha256(image: Any) -> str:
    digest = hashlib.sha256(f"RGB:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _encode_png(image: Any) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _find_adetailer(script_runner: Any) -> Any | None:
    for script in getattr(script_runner, "alwayson_scripts", None) or []:
        try:
            if script.title() == "ADetailer" and hasattr(script, "_postprocess_image_inner"):
                return script
        except Exception:  # noqa: BLE001, S112 - another extension's title() must not hide ADetailer
            continue
    return None


def _script_defaults(script_runner: Any) -> list[Any]:
    """Default arguments for every img2img script, built the way Forge's own API builds them."""

    global _default_script_args
    if _default_script_args is None:
        import gradio as gr

        last = 1
        for script in script_runner.scripts:
            last = max(last, script.args_to)
        defaults: list[Any] = [None] * last
        defaults[0] = 0
        with gr.Blocks():
            for script in script_runner.scripts:
                components = script.ui(script.is_img2img)
                if components:
                    defaults[script.args_from : script.args_to] = [c.value for c in components]
        _default_script_args = defaults
    return list(_default_script_args)


class _Capture:
    """Stand-in ``self`` for the pinned per-pass routine: everything is the real script except three seams."""

    def __init__(self, script: Any, overrides: dict[str, Any]) -> None:
        self._script = script
        self._overrides = overrides
        self.masks: list[Any] = []
        self.sampled_masks = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._script, name)

    def pred_preprocessing(self, p: Any, pred: Any, args: Any) -> list[Any]:
        masks = self._script.pred_preprocessing(p, pred, args)
        self.masks = [mask.convert("L") for mask in masks]
        return masks

    def fix_p2(self, p: Any, p2: Any, pp: Any, args: Any, pred: Any, j: int) -> None:
        # Called once per mask, immediately before that mask is inpainted. Each inpaint gets its own settings dict
        # (the request's overrides, then the pass's own) because Forge consumes entries from it while processing.
        self._script.fix_p2(p, p2, pp, args, pred, j)
        p2.override_settings = {**self._overrides, **self._script.get_override_settings(args)}
        self.sampled_masks += 1


def _reject(status: int, detail: str) -> Any:
    from fastapi import HTTPException

    return HTTPException(status_code=status, detail=f"[{SCHEMA}] {detail}")


def _versions() -> dict[str, Any]:
    from modules import scripts

    script = _find_adetailer(scripts.scripts_img2img)
    version = None
    if script is not None:
        version = type(script)._postprocess_image_inner.__globals__.get("__version__")
    return {"schema": SCHEMA, "companion_version": COMPANION_VERSION, "adetailer_version": version}


def _localized(body: dict[str, Any]) -> dict[str, Any]:
    from modules import scripts, shared
    from modules.call_queue import queue_lock
    from modules.processing import StableDiffusionProcessingImg2Img, get_fixed_seed
    from modules.shared import opts
    from PIL import Image

    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise _reject(422, "unsupported request schema")
    passes = body.get("passes")
    if not isinstance(passes, list) or not 1 <= len(passes) <= MAX_PASSES:
        raise _reject(422, f"passes must list 1 to {MAX_PASSES} entries")

    script_runner = scripts.scripts_img2img
    script = _find_adetailer(script_runner)
    if script is None:
        raise _reject(503, "the ADetailer script is not registered in this runtime")
    inner = type(script)._postprocess_image_inner
    args_model = inner.__globals__["ADetailerArgs"]

    parsed: list[tuple[str, Any]] = []
    for entry in passes:
        if not isinstance(entry, dict) or not isinstance(entry.get("args"), dict):
            raise _reject(422, "each pass needs a label and an args object")
        label = str(entry.get("label") or "")
        try:
            args = args_model(**entry["args"])
        except ValueError as exc:
            # The stock always-on path drops such a pass silently; here it is an error.
            raise _reject(422, f"{label} pass arguments were rejected: {exc}") from exc
        if args.need_skip():
            raise _reject(422, f"{label} pass is disabled or has no detector")
        if args.ad_mask_merge_invert == _INVERTING_MERGE_MODE:
            raise _reject(
                422,
                f"{label} pass inverts its mask; localized refinement never edits the background",
            )
        parsed.append((label, args))

    try:
        raw = base64.b64decode(str(body.get("image") or "").split(",", 1)[-1], validate=True)
        decoded = Image.open(io.BytesIO(raw))
        decoded.load()
    except Exception as exc:  # noqa: BLE001 - any undecodable input is the same refusal
        raise _reject(422, f"image is not decodable: {exc}") from exc
    image = decoded.convert("RGB")
    source = {"width": image.width, "height": image.height, "sha256": _pixel_sha256(image)}
    expected = body.get("source")
    if isinstance(expected, dict) and expected.get("sha256") not in (None, source["sha256"]):
        raise _reject(422, "the decoded image does not match the declared source identity")

    overrides = dict(body.get("override_settings") or {})
    p = StableDiffusionProcessingImg2Img(
        sd_model=shared.sd_model,
        init_images=[image],
        prompt=str(body.get("prompt") or ""),
        negative_prompt=str(body.get("negative_prompt") or ""),
        seed=int(body.get("seed", -1)),
        steps=int(body.get("steps", 20)),
        cfg_scale=float(body.get("cfg_scale", 7.0)),
        sampler_name=str(body.get("sampler_name") or "Euler"),
        width=image.width,
        height=image.height,
        do_not_save_samples=True,
        do_not_save_grid=True,
    )
    if body.get("scheduler"):
        p.scheduler = str(body["scheduler"])
    p.is_api = True
    p.scripts = script_runner
    p.script_args = tuple(_script_defaults(script_runner))
    p.outpath_grids = opts.outdir_img2img_grids
    p.outpath_samples = opts.outdir_img2img_samples
    p.batch_index = 0
    p.seed = get_fixed_seed(p.seed)
    p.subseed = get_fixed_seed(p.subseed)
    p.all_seeds = [p.seed]
    p.all_subseeds = [p.subseed]
    p.all_prompts = [p.prompt]
    p.all_negative_prompts = [p.negative_prompt]

    pp = scripts.PostprocessImageArgs(image, 0)
    results: list[dict[str, Any]] = []
    refined = False
    with queue_lock, closing(p):
        try:
            shared.state.begin(job="stablenew_adetailer_localized")
            p.extra_generation_params.update(script.extra_params([args for _, args in parsed]))
            for n, (label, args) in enumerate(parsed):
                capture = _Capture(script, overrides)
                refined |= bool(inner(capture, p, pp, args, n=n))
                results.append(
                    {
                        "label": label,
                        "model": args.ad_model,
                        "mask_count": len(capture.masks),
                        "sampled_masks": capture.sampled_masks,
                        "masks": [_encode_png(mask) for mask in capture.masks],
                    }
                )
        finally:
            shared.state.end()
            shared.total_tqdm.clear()

    return {
        **_versions(),
        "source": source,
        "seed": p.seed,
        "subseed": p.subseed,
        "sampled": any(entry["sampled_masks"] for entry in results),
        "image": _encode_png(pp.image.convert("RGB")) if refined else None,
        "passes": results,
    }


def _register(_: Any, app: Any) -> None:
    @app.get(ROUTE + "/version")
    def version() -> dict[str, Any]:
        return _versions()

    @app.post(ROUTE)
    def localized(body: dict[str, Any]) -> dict[str, Any]:
        return _localized(body)


script_callbacks.on_app_started(_register)
