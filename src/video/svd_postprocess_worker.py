"""Helper process for SVD frame enhancement stages.

The worker parses the stage payload, selects the requested product method, calls the
StableNew-owned restoration adapters in ``src.video.restoration``, writes outputs and releases
memory. Model libraries are imported lazily by those adapters, so importing this module needs
no optional restoration package.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from src.video.motion.secondary_motion_worker import run_secondary_motion_worker


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-json", required=True)
    return parser.parse_args()


def _load_payload(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("worker config payload must be an object")
    return payload


def _iter_frame_paths(directory: Path) -> list[Path]:
    return sorted(
        candidate
        for candidate in directory.iterdir()
        if candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )


def _load_rgb_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def _save_rgb_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.mode == "RGB":
        image.save(path, format="PNG")
        return
    image.convert("RGB").save(path, format="PNG")


def _build_codeformer(payload: dict[str, Any]):
    from src.video.restoration.codeformer import CodeFormerRestorer

    weight_path = Path(str(payload.get("codeformer_weight_path") or "")).expanduser()
    if not weight_path.exists():
        raise RuntimeError(f"CodeFormer weight file not found: {weight_path}")
    return CodeFormerRestorer(
        weight_path=str(weight_path),
        facelib_model_root=str(payload.get("facelib_model_root") or ""),
    )


def _apply_codeformer(image: Image.Image, *, restorer, fidelity_weight: float) -> Image.Image:
    return restorer.restore(image, fidelity=fidelity_weight)


def _build_realesrgan(payload: dict[str, Any]):
    from src.video.restoration.upscaler import RRDBUpscaler

    model_path = Path(str(payload.get("model_path") or "")).expanduser()
    if not model_path.exists():
        raise RuntimeError(f"RealESRGAN model file not found: {model_path}")
    return RRDBUpscaler(str(model_path), tile=int(payload.get("tile", 0)))


def _apply_realesrgan(image: Image.Image, *, upsampler, scale: float) -> Image.Image:
    import cv2
    import numpy as np

    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    enhanced = upsampler.enhance(bgr, outscale=scale)
    return Image.fromarray(cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)).convert("RGB")


def _run_face_restore(input_dir: Path, output_dir: Path, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "CodeFormer")
    fidelity = float(payload.get("fidelity_weight", 0.7))
    if method != "CodeFormer":
        # GFPGAN remains a named product method, but its legacy loader was retired without a
        # qualified replacement; admission rejects it before this point.
        raise RuntimeError(f"Face restore method '{method}' is not available in this environment")
    restorer = _build_codeformer(payload)

    for input_path in _iter_frame_paths(input_dir):
        source = _load_rgb_image(input_path)
        restored = _apply_codeformer(source, restorer=restorer, fidelity_weight=fidelity)
        try:
            _save_rgb_image(restored, output_dir / input_path.name)
        finally:
            source.close()
            if restored is not source:
                restored.close()
            _release_worker_memory()


def _run_upscale(input_dir: Path, output_dir: Path, payload: dict[str, Any]) -> None:
    scale = float(payload.get("scale", 2.0))
    upsampler = _build_realesrgan(payload)
    for input_path in _iter_frame_paths(input_dir):
        source = _load_rgb_image(input_path)
        enhanced = _apply_realesrgan(source, upsampler=upsampler, scale=scale)
        try:
            _save_rgb_image(enhanced, output_dir / input_path.name)
        finally:
            source.close()
            if enhanced is not source:
                enhanced.close()
            _release_worker_memory()


def _run_secondary_motion(
    input_dir: Path, output_dir: Path, payload: dict[str, Any]
) -> dict[str, Any]:
    intent_payload = (
        dict(payload.get("intent") or {}) if isinstance(payload.get("intent"), dict) else {}
    )
    policy_payload = (
        dict(payload.get("policy") or {}) if isinstance(payload.get("policy"), dict) else {}
    )
    worker_payload = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "intent": intent_payload,
        "policy": policy_payload,
        "seed": payload.get("seed"),
    }
    return run_secondary_motion_worker(worker_payload)


def _release_worker_memory() -> None:
    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.empty_cache()
    except Exception:
        pass
    try:
        torch.cuda.ipc_collect()
    except Exception:
        pass


def main() -> int:
    args = _parse_args()
    config = _load_payload(args.config_json)
    action = str(config.get("action") or "")
    input_dir = Path(str(config.get("input_dir") or "")).expanduser()
    output_dir = Path(str(config.get("output_dir") or "")).expanduser()
    payload = config.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("worker payload is missing")
    if not input_dir.exists():
        raise RuntimeError(f"Input frame directory does not exist: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if action == "face_restore":
        _run_face_restore(input_dir, output_dir, payload)
    elif action == "upscale":
        _run_upscale(input_dir, output_dir, payload)
    elif action == "secondary_motion":
        result = _run_secondary_motion(input_dir, output_dir, payload)
        sys.stdout.write(json.dumps(result))
    else:
        raise RuntimeError(f"Unsupported worker action: {action}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1) from exc
