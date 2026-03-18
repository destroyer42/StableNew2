"""Helper process for SVD frame enhancement stages."""

from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import site
import sys
import types
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image


def _find_site_package_dir(name: str) -> Path | None:
    candidates: list[Path] = []
    for root in site.getsitepackages():
        candidates.append(Path(root) / name)
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(Path(user_site) / name)
    except Exception:
        pass
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _prepend_site_package_dir(name: str) -> Path:
    candidate = _find_site_package_dir(name)
    if candidate is None:
        raise RuntimeError(f"{name} package directory was not found in the active Python environment")
    sys.path.insert(0, str(candidate.parent))
    return candidate


def _install_torchvision_compat_shims() -> None:
    if "torchvision.transforms.functional_tensor" in sys.modules:
        return
    try:
        import torchvision.transforms.functional as functional
    except Exception:
        return
    shim = types.ModuleType("torchvision.transforms.functional_tensor")
    for name in dir(functional):
        if name.startswith("__"):
            continue
        setattr(shim, name, getattr(functional, name))
    sys.modules["torchvision.transforms.functional_tensor"] = shim


def _import_basicsr_runtime():
    _install_torchvision_compat_shims()
    _prepend_site_package_dir("basicsr")
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from basicsr.utils.misc import get_device
    from basicsr.utils.realesrgan_utils import RealESRGANer

    return RRDBNet, RealESRGANer, get_device


def _import_codeformer_runtime():
    _install_torchvision_compat_shims()
    codeformer_root = _prepend_site_package_dir("codeformer")
    sys.path.insert(0, str(codeformer_root))
    os.chdir(codeformer_root)
    from basicsr.archs.codeformer_arch import CodeFormer as CodeFormerArch
    from basicsr.utils.img_util import img2tensor, tensor2img
    from basicsr.utils.misc import get_device
    from facelib.utils.face_restoration_helper import FaceRestoreHelper
    from torchvision.transforms.functional import normalize

    return codeformer_root, CodeFormerArch, FaceRestoreHelper, get_device, img2tensor, tensor2img, normalize


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
    codeformer_root, CodeFormerArch, FaceRestoreHelper, get_device, _img2tensor, _tensor2img, _normalize = _import_codeformer_runtime()
    weight_path = Path(str(payload.get("codeformer_weight_path") or "")).expanduser()
    if not weight_path.exists():
        raise RuntimeError(f"CodeFormer weight file not found: {weight_path}")

    model_root = Path(str(payload.get("facelib_model_root") or "")).expanduser()
    if not model_root.exists():
        raise RuntimeError(f"Face model root not found: {model_root}")
    _ensure_facelib_weights(model_root, target_dir=codeformer_root / "weights" / "facelib")

    device = get_device()
    model = CodeFormerArch(
        dim_embd=512,
        codebook_size=1024,
        n_head=8,
        n_layers=9,
        connect_list=["32", "64", "128", "256"],
    ).to(device)
    checkpoint = torch.load(weight_path, map_location="cpu")
    state_dict = checkpoint.get("params_ema") or checkpoint.get("params")
    if not isinstance(state_dict, dict):
        raise RuntimeError(f"Unexpected CodeFormer checkpoint structure: {weight_path}")
    model.load_state_dict(state_dict)
    model.eval()
    helper = FaceRestoreHelper(
        1,
        face_size=512,
        crop_ratio=(1, 1),
        det_model="retinaface_resnet50",
        save_ext="png",
        use_parse=True,
        device=device,
    )
    return model, helper, device, _img2tensor, _tensor2img, _normalize


def _ensure_facelib_weights(model_root: Path, *, target_dir: Path) -> None:
    candidates = {
        "detection_Resnet50_Final.pth": model_root / "detection_Resnet50_Final.pth",
        "parsing_parsenet.pth": model_root / "parsing_parsenet.pth",
    }
    for name, source in candidates.items():
        if not source.exists():
            raise RuntimeError(f"Required facelib model not found: {source}")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / name
        if not target_path.exists():
            shutil.copy2(source, target_path)


def _apply_codeformer(
    image: Image.Image,
    *,
    model,
    helper,
    device,
    fidelity_weight: float,
    img2tensor,
    tensor2img,
    normalize,
) -> Image.Image:
    helper.clean_all()
    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    helper.read_image(bgr)
    helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
    helper.align_warp_face()

    if not helper.cropped_faces:
        return image.convert("RGB")

    for cropped_face in helper.cropped_faces:
        cropped_face_t = img2tensor(cropped_face / 255.0, bgr2rgb=True, float32=True)
        normalize(cropped_face_t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
        cropped_face_t = cropped_face_t.unsqueeze(0).to(device)
        try:
            with torch.no_grad():
                output = model(cropped_face_t, w=fidelity_weight, adain=True)[0]
                restored_face = tensor2img(output, rgb2bgr=True, min_max=(-1, 1))
        except Exception:
            restored_face = tensor2img(cropped_face_t, rgb2bgr=True, min_max=(-1, 1))
        helper.add_restored_face(restored_face.astype("uint8"), cropped_face)

    helper.get_inverse_affine(None)
    restored = helper.paste_faces_to_input_image(upsample_img=None, draw_box=False)
    return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB)).convert("RGB")


def _build_gfpgan(payload: dict[str, Any]):
    _install_torchvision_compat_shims()
    weight_path = Path(str(payload.get("gfpgan_weight_path") or "")).expanduser()
    if not weight_path.exists():
        raise RuntimeError(f"GFPGAN weight file not found: {weight_path}")

    model_root = Path(str(payload.get("facelib_model_root") or "")).expanduser()
    if not model_root.exists():
        raise RuntimeError(f"Face model root not found: {model_root}")

    gfpgan_root = _prepend_site_package_dir("gfpgan")
    os.chdir(gfpgan_root.parent)
    _ensure_facelib_weights(model_root, target_dir=gfpgan_root / "weights" / "facelib")

    from gfpgan import GFPGANer
    _RRDBNet, _RealESRGANer, get_device = _import_basicsr_runtime()
    device = get_device()
    return GFPGANer(
        model_path=str(weight_path),
        upscale=1,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )


def _apply_gfpgan(image: Image.Image, *, restorer, fidelity_weight: float) -> Image.Image:
    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    _cropped, _restored_faces, restored = restorer.enhance(
        bgr,
        has_aligned=False,
        only_center_face=False,
        paste_back=True,
        weight=fidelity_weight,
    )
    if restored is None:
        return image.convert("RGB")
    return Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB)).convert("RGB")


def _build_realesrgan(payload: dict[str, Any]):
    RRDBNet, RealESRGANer, _get_device = _import_basicsr_runtime()
    model_path = Path(str(payload.get("model_path") or "")).expanduser()
    if not model_path.exists():
        raise RuntimeError(f"RealESRGAN model file not found: {model_path}")

    lower_name = model_path.name.lower()
    network_scale = 2 if "x2" in lower_name else 4
    model = RRDBNet(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_block=23,
        num_grow_ch=32,
        scale=network_scale,
    )
    use_half = torch.cuda.is_available()
    return RealESRGANer(
        scale=network_scale,
        model_path=str(model_path),
        model=model,
        tile=int(payload.get("tile", 0)),
        tile_pad=40,
        pre_pad=0,
        half=use_half,
    )


def _apply_realesrgan(image: Image.Image, *, upsampler, scale: float) -> Image.Image:
    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    enhanced, _ = upsampler.enhance(bgr, outscale=scale)
    return Image.fromarray(cv2.cvtColor(enhanced, cv2.COLOR_BGR2RGB)).convert("RGB")


def _run_face_restore(input_dir: Path, output_dir: Path, payload: dict[str, Any]) -> None:
    method = str(payload.get("method") or "CodeFormer")
    fidelity = float(payload.get("fidelity_weight", 0.7))
    if method == "CodeFormer":
        runtime = _build_codeformer(payload)
    elif method == "GFPGAN":
        runtime = _build_gfpgan(payload)
    else:
        raise RuntimeError(f"Face restore method '{method}' is not available in this environment")

    for input_path in _iter_frame_paths(input_dir):
        source = _load_rgb_image(input_path)
        if method == "CodeFormer":
            restored = _apply_codeformer(
                source,
                model=runtime[0],
                helper=runtime[1],
                device=runtime[2],
                fidelity_weight=fidelity,
                img2tensor=runtime[3],
                tensor2img=runtime[4],
                normalize=runtime[5],
            )
        else:
            restored = _apply_gfpgan(
                source,
                restorer=runtime,
                fidelity_weight=fidelity,
            )
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


def _release_worker_memory() -> None:
    gc.collect()
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
    else:
        raise RuntimeError(f"Unsupported worker action: {action}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1)
