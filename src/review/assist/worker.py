"""Contained child process that runs one Smart Review model once (PR-IMG-REVIEW-320).

Started only by ``providers`` through the repository's bounded-process helper: ``python -I worker.py <job dir>``. The job
directory holds ``request.json`` and the stored image pixels (``source.rgb``) and receives ``result.json`` (plus ``logits.f32``
for a mask). The child runs on CPU only (the parent hides every GPU and sets the offline flags), never reaches the network,
loads only the staged, hash-verified files named in the request, never enables ``trust_remote_code``, never deserializes a
pickle, and exits when its single job is done. It owns no queue, backend or GUI state.

Both models are loaded with ``load_state_dict(strict=True)`` after the key accounting in ``loading``: a missing or unexplained
tensor stops the job instead of being initialized with random numbers. Importing this module imports nothing heavy.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if (
    __name__ == "__main__"
):  # isolated mode (-I) puts neither the script directory nor the repository on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np  # noqa: E402

from src.conditioning.reference_map.contracts import (  # noqa: E402
    CODE_INFERENCE,
    ProviderUnavailable,
    ReferenceMapError,
)
from src.conditioning.reference_map.worker import Backend, run_job  # noqa: E402
from src.review.assist.loading import (  # noqa: E402
    plan_tied_aliases,
    split_unexpected,
    transformers_reason,
)

LOGITS_FILE = "logits.f32"
WEIGHTS_FILE = "model.safetensors"
MAX_THREADS = 4
CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
OBJECT_TASK = "<OD>"
MAX_NEW_TOKENS = 160
MAX_CAPTION_CHARS = 4000
MAX_OBJECTS = 16


def _missing(*modules: str) -> list[str]:
    return [f"runtime_missing:{name}" for name in modules if importlib.util.find_spec(name) is None]


def _threads() -> int:
    return max(1, min(MAX_THREADS, os.cpu_count() or 1))


def _staged_dir(request: Mapping[str, Any], job_dir: Path) -> Path:
    staged = Path(str(request["staged_dir"])).resolve()
    if staged != (job_dir / "models").resolve():
        raise ReferenceMapError(CODE_INFERENCE, "Invalid job.")
    return staged


def _require_runtime(*modules: str) -> None:
    missing = _missing(*modules)
    if missing:
        raise ProviderUnavailable("The model runtime is not installed.", reasons=tuple(missing))


def _check_transformers(version: str) -> None:
    reason = transformers_reason(version)
    if reason is not None:
        raise ProviderUnavailable(
            "The installed Transformers is not the qualified line.", reasons=(reason,)
        )


def sam2_backend(request: Mapping[str, Any], rgb: np.ndarray, job_dir: Path) -> dict[str, Any]:
    """One point/box-prompted mask for one image: low-resolution logits of the highest-scoring candidate."""

    _require_runtime("torch", "transformers", "torchvision", "safetensors", "PIL")
    import torch
    import transformers
    from PIL import Image
    from safetensors.torch import load_file
    from transformers import AutoImageProcessor, Sam2Config, Sam2Model, Sam2Processor

    _check_transformers(str(transformers.__version__))
    torch.set_num_threads(_threads())
    directory = _staged_dir(request, job_dir)
    raw = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    # The pinned export is a Sam2Video checkpoint; single-image use takes its own image sub-configurations unchanged.
    config = Sam2Config(
        vision_config=copy.deepcopy(raw["vision_config"]),
        prompt_encoder_config=copy.deepcopy(raw["prompt_encoder_config"]),
        mask_decoder_config=copy.deepcopy(raw["mask_decoder_config"]),
        initializer_range=raw["initializer_range"],
    )
    model = Sam2Model(config)  # random values are overwritten by the strict load below
    file_state = load_file(str(directory / WEIGHTS_FILE), device="cpu")
    expected = {key: tuple(value.shape) for key, value in model.state_dict().items()}
    ignored = split_unexpected(
        {key: tuple(value.shape) for key, value in file_state.items()},
        expected,
        tuple(Sam2Model._keys_to_ignore_on_load_unexpected),
    )
    loaded = model.load_state_dict(
        {key: value for key, value in file_state.items() if key not in ignored}, strict=True
    )
    if loaded.missing_keys or loaded.unexpected_keys:
        raise ReferenceMapError(CODE_INFERENCE, "The mask model did not load completely.")
    model.eval()
    image_processor = AutoImageProcessor.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False
    )
    processor = Sam2Processor(image_processor, target_size=1024, point_pad_value=-10)
    points = [[int(x), int(y)] for x, y in request.get("points", [])]
    labels = [int(label) for label in request.get("labels", [])]
    box = request.get("box")
    arguments: dict[str, Any] = {}
    if points:
        arguments["input_points"] = [[points]]
        arguments["input_labels"] = [[labels]]
    if box:
        arguments["input_boxes"] = [[[int(value) for value in box]]]
    inputs = processor(images=Image.fromarray(rgb), return_tensors="pt", **arguments)
    # One ambiguous prompt (a single point or a lone box) gets the model's three candidates; richer prompts get one.
    multimask = (len(points) + (1 if box else 0)) == 1
    with torch.inference_mode():
        output = model(
            pixel_values=inputs["pixel_values"],
            input_points=inputs.get("input_points"),
            input_labels=inputs.get("input_labels"),
            input_boxes=inputs.get("input_boxes"),
            multimask_output=multimask,
        )
    scores = output.iou_scores[0, 0].detach().float().cpu()
    best = int(torch.argmax(scores))
    logits = output.pred_masks[0, 0, best].detach().float().cpu().numpy().astype("<f4")
    (job_dir / LOGITS_FILE).write_bytes(logits.tobytes())
    return {
        "shape": [int(logits.shape[0]), int(logits.shape[1])],
        "score": float(scores[best]),
        "candidates": int(scores.numel()),
        "ignored_tensors": len(ignored),
        "runtime": {"torch": str(torch.__version__), "transformers": str(transformers.__version__)},
    }


def florence2_backend(request: Mapping[str, Any], rgb: np.ndarray, job_dir: Path) -> dict[str, Any]:
    """A detailed caption and labelled boxes for one image, from the native converted Florence-2 checkpoint."""

    _require_runtime("torch", "transformers", "safetensors", "PIL")
    import torch
    import transformers
    from PIL import Image
    from safetensors.torch import load_file
    from transformers import AutoProcessor, Florence2Config, Florence2ForConditionalGeneration

    _check_transformers(str(transformers.__version__))
    torch.set_num_threads(_threads())
    directory = _staged_dir(request, job_dir)
    config = Florence2Config.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False
    )
    model = Florence2ForConditionalGeneration(
        config
    )  # random values are overwritten by the strict load below
    file_state = load_file(str(directory / WEIGHTS_FILE), device="cpu")
    expected = {key: tuple(value.shape) for key, value in model.state_dict().items()}
    plan = plan_tied_aliases(
        {key: tuple(value.shape) for key, value in file_state.items()},
        expected,
        dict(model.all_tied_weights_keys),
    )
    for alias, root in plan.items():
        file_state[alias] = file_state[root]
    loaded = model.load_state_dict(file_state, strict=True)
    if loaded.missing_keys or loaded.unexpected_keys:
        raise ReferenceMapError(CODE_INFERENCE, "The caption model did not load completely.")
    model.tie_weights()
    model.eval()
    processor = AutoProcessor.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False
    )
    image = Image.fromarray(rgb)
    height, width = int(rgb.shape[0]), int(rgb.shape[1])

    def generate(task: str) -> tuple[Any, Any]:
        inputs = processor(images=image, text=task, return_tensors="pt")
        with torch.inference_mode():
            ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=MAX_NEW_TOKENS,
                num_beams=3,
                do_sample=False,
            )
        return ids, inputs

    ids, _ = generate(CAPTION_TASK)
    caption = str(processor.batch_decode(ids, skip_special_tokens=True)[0])[:MAX_CAPTION_CHARS]
    ids, _ = generate(OBJECT_TASK)
    decoded = processor.batch_decode(ids, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(
        decoded, task=OBJECT_TASK, image_size=(width, height)
    )
    detected = parsed.get(OBJECT_TASK, {}) if isinstance(parsed, dict) else {}
    objects = [
        {"label": str(label)[:96], "box": [float(value) for value in box]}
        for label, box in zip(detected.get("labels", []), detected.get("bboxes", []), strict=False)
    ][:MAX_OBJECTS]
    return {
        "caption": caption,
        "objects": objects,
        "tied_aliases": len(plan),
        "runtime": {"torch": str(torch.__version__), "transformers": str(transformers.__version__)},
    }


BACKENDS: dict[str, Backend] = {"sam2": sam2_backend, "florence2": florence2_backend}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 64
    return run_job(Path(argv[1]), BACKENDS)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
