"""Contained child process that runs one model for a reference map (PR-IMG-CNET-230).

Started only by ``providers.run_worker`` through the repository's bounded-process helper: ``python -I worker.py <job dir>``.
The job directory holds ``request.json`` and the oriented source pixels (``source.rgb``) and receives ``result.json``
(plus ``depth.f32`` for depth). The child runs on CPU only (the parent hides every GPU), never reaches the network, loads
only the staged, hash-verified files named in the request, never enables ``trust_remote_code`` and never deserializes a
pickle. It owns no queue, backend or GUI state and exits when its single job is done.

Importing this module imports nothing heavy: the model libraries load inside the backend functions.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

if (
    __name__ == "__main__"
):  # isolated mode (-I) puts neither the script directory nor the repository on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np  # noqa: E402

from src.conditioning.reference_map import pose  # noqa: E402
from src.conditioning.reference_map.contracts import (  # noqa: E402
    CODE_INFERENCE,
    ProviderUnavailable,
    ReferenceMapError,
)

REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"
SOURCE_FILE = "source.rgb"
DEPTH_FILE = "depth.f32"
MAX_THREADS = 4

Backend = Callable[[Mapping[str, Any], np.ndarray, Path], dict[str, Any]]


def _missing(*modules: str) -> list[str]:
    return [f"runtime_missing:{name}" for name in modules if importlib.util.find_spec(name) is None]


def _threads() -> int:
    return max(1, min(MAX_THREADS, os.cpu_count() or 1))


def depth_backend(request: Mapping[str, Any], rgb: np.ndarray, job_dir: Path) -> dict[str, Any]:
    missing = _missing("torch", "transformers")
    if missing:
        raise ProviderUnavailable("Depth needs PyTorch and Transformers.", reasons=tuple(missing))
    import torch
    import transformers
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    torch.set_num_threads(_threads())
    directory = str(request["staged_dir"])
    processor = AutoImageProcessor.from_pretrained(directory, local_files_only=True)
    model = AutoModelForDepthEstimation.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False, use_safetensors=True
    ).eval()
    inputs = processor(images=Image.fromarray(rgb), return_tensors="pt")
    with torch.inference_mode():
        predicted = model(**inputs).predicted_depth
    prediction = predicted[0].detach().float().cpu().numpy().astype("<f4")
    (job_dir / DEPTH_FILE).write_bytes(prediction.tobytes())
    return {
        "shape": [int(prediction.shape[0]), int(prediction.shape[1])],
        "runtime": {"torch": str(torch.__version__), "transformers": str(transformers.__version__)},
    }


def _onnx_session(path: str) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = _threads()
    options.log_severity_level = 3
    return ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])


def pose_backend(request: Mapping[str, Any], rgb: np.ndarray, job_dir: Path) -> dict[str, Any]:
    missing = _missing("onnxruntime", "cv2")
    if missing:
        raise ProviderUnavailable("OpenPose needs ONNX Runtime and OpenCV.", reasons=tuple(missing))
    import cv2
    import onnxruntime as ort

    staged = request["staged"]
    detector = _onnx_session(str(staged["person_detector"]))
    estimator = _onnx_session(str(staged["pose_estimator"]))
    bgr = np.ascontiguousarray(rgb[..., ::-1])
    height, width = bgr.shape[:2]
    side_h, side_w = pose.DETECTOR_INPUT
    ratio = min(side_h / height, side_w / width)
    resized = cv2.resize(
        bgr, (int(width * ratio), int(height * ratio)), interpolation=cv2.INTER_LINEAR
    )
    padded = np.full((side_h, side_w, 3), 114, dtype=np.uint8)
    padded[: resized.shape[0], : resized.shape[1]] = resized
    blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None].astype(np.float32))
    raw = detector.run(None, {detector.get_inputs()[0].name: blob})[0]
    boxes = pose.person_boxes(pose.yolox_decode(raw), ratio)[: pose.MAX_PEOPLE + 1]
    mean = np.array(pose.POSE_MEAN, dtype=np.float32)
    std = np.array(pose.POSE_STD, dtype=np.float32)
    people = []
    for box, score in boxes:
        center, scale = pose.box_center_scale(box)
        crop = cv2.warpAffine(
            bgr, pose.warp_matrix(center, scale), pose.POSE_INPUT, flags=cv2.INTER_LINEAR
        )
        tensor = np.ascontiguousarray(
            ((crop.astype(np.float32) - mean) / std).transpose(2, 0, 1)[None]
        )
        outputs = estimator.run(None, {estimator.get_inputs()[0].name: tensor})
        points, scores = pose.simcc_keypoints(outputs[0][0], outputs[1][0], center, scale)
        people.append(pose.PosePerson(points, scores, score))
    payload = pose.people_to_payload(people, width, height)
    return {"people": payload["people"], "runtime": {"onnxruntime": str(ort.__version__)}}


BACKENDS: dict[str, Backend] = {"depth": depth_backend, "pose": pose_backend}


def _write_result(job_dir: Path, document: dict[str, Any]) -> None:
    (job_dir / RESULT_FILE).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def run_job(job_dir: Path, backends: Mapping[str, Backend] | None = None) -> int:
    """Execute the single job in ``job_dir``; returns the process exit code (0 only when a result was written)."""

    table = backends if backends is not None else BACKENDS
    try:
        request = json.loads((job_dir / REQUEST_FILE).read_text(encoding="utf-8"))
        kind = str(request["kind"])
        width, height = int(request["width"]), int(request["height"])
        data = (job_dir / SOURCE_FILE).read_bytes()
        if kind not in table or len(data) != width * height * 3:
            raise ReferenceMapError(CODE_INFERENCE, "Invalid job.")
        rgb = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        result = table[kind](request, rgb, job_dir)
    except ProviderUnavailable as exc:
        _write_result(job_dir, {"ok": False, "code": exc.code, "reasons": list(exc.reasons)})
        return 3
    except ReferenceMapError as exc:
        _write_result(job_dir, {"ok": False, "code": exc.code, "reasons": list(exc.reasons)})
        return 2
    except Exception as exc:  # noqa: BLE001 - the parent reports a content-free failure; only the type name is kept
        _write_result(
            job_dir, {"ok": False, "code": CODE_INFERENCE, "reasons": [type(exc).__name__]}
        )
        return 1
    _write_result(job_dir, {"ok": True, **result})
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 64
    return run_job(Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
