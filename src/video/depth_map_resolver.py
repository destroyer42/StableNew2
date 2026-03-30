from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PIL import Image


DEFAULT_DEPTH_ESTIMATOR_MODEL_ID = "Intel/dpt-hybrid-midas"
VALID_DEPTH_INPUT_MODES = {"auto", "upload"}


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_path_text(value: Any) -> str:
    return str(value or "").strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class DepthResolutionResult:
    mode: str
    source_image_path: str
    resolved_path: str
    requested_path: str | None = None
    cache_path: str | None = None
    cache_hit: bool = False
    model_id: str = DEFAULT_DEPTH_ESTIMATOR_MODEL_ID

    def to_stage_config(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_image_path": self.source_image_path,
            "requested_path": self.requested_path,
            "resolved_path": self.resolved_path,
            "cache_path": self.cache_path,
            "cache_hit": bool(self.cache_hit),
            "model_id": self.model_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_stage_config()


class DepthMapResolver:
    """Resolves uploaded or auto-generated depth maps for conditioned video workflows."""

    def __init__(
        self,
        *,
        cache_dir: str | Path = Path("data") / "video_depth_cache",
        model_id: str = DEFAULT_DEPTH_ESTIMATOR_MODEL_ID,
        local_files_only: bool = False,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._model_id = str(model_id or DEFAULT_DEPTH_ESTIMATOR_MODEL_ID).strip()
        self._local_files_only = bool(local_files_only)
        self._estimator: Any = None

    def resolve(
        self,
        *,
        source_image_path: Path | None,
        depth_input: Mapping[str, Any] | None,
        output_dir: Path,
    ) -> DepthResolutionResult:
        if source_image_path is None:
            raise ValueError("Depth-conditioned workflows require an input source image.")
        source_path = Path(source_image_path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"Depth source image does not exist: {source_path}")

        payload = _mapping_dict(depth_input)
        mode = str(payload.get("mode") or "").strip().lower()
        if mode == "upload":
            return self._resolve_uploaded_depth(
                source_image_path=source_path,
                depth_input=payload,
                output_dir=Path(output_dir),
            )
        if mode == "auto":
            return self._resolve_auto_depth(
                source_image_path=source_path,
                output_dir=Path(output_dir),
            )
        allowed = ", ".join(sorted(VALID_DEPTH_INPUT_MODES))
        raise ValueError(f"depth_input.mode must be one of: {allowed}")

    def _resolve_uploaded_depth(
        self,
        *,
        source_image_path: Path,
        depth_input: Mapping[str, Any],
        output_dir: Path,
    ) -> DepthResolutionResult:
        requested_text = _normalize_path_text(
            depth_input.get("path") or depth_input.get("upload_path")
        )
        if not requested_text:
            raise ValueError("depth_input.path is required when depth_input.mode='upload'")

        requested_path = Path(requested_text).expanduser()
        if not requested_path.exists() or not requested_path.is_file():
            raise ValueError(f"Uploaded depth image does not exist: {requested_path}")
        self._validate_image(requested_path)

        resolved_path = self._materialize_output_copy(
            source_path=requested_path,
            output_dir=output_dir,
            filename=f"depth_upload_{requested_path.stem}.png",
        )
        return DepthResolutionResult(
            mode="upload",
            source_image_path=str(source_image_path.resolve()),
            requested_path=str(requested_path.resolve()),
            resolved_path=str(resolved_path),
            cache_path=None,
            cache_hit=False,
            model_id=self._model_id,
        )

    def _resolve_auto_depth(
        self,
        *,
        source_image_path: Path,
        output_dir: Path,
    ) -> DepthResolutionResult:
        digest = self._build_cache_key(source_image_path)
        cache_path = self._cache_dir / f"{digest}.png"
        cache_hit = cache_path.exists()
        if not cache_hit:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            depth_image = self._generate_depth_image(source_image_path)
            depth_image.save(cache_path, format="PNG")

        resolved_path = self._materialize_output_copy(
            source_path=cache_path,
            output_dir=output_dir,
            filename=f"depth_auto_{digest[:12]}.png",
        )
        return DepthResolutionResult(
            mode="auto",
            source_image_path=str(source_image_path.resolve()),
            requested_path=None,
            resolved_path=str(resolved_path),
            cache_path=str(cache_path.resolve()),
            cache_hit=cache_hit,
            model_id=self._model_id,
        )

    def _build_cache_key(self, source_image_path: Path) -> str:
        source_digest = _sha256_file(source_image_path)
        return hashlib.sha256(
            f"{source_digest}:{self._model_id}".encode("utf-8")
        ).hexdigest()

    def _materialize_output_copy(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        filename: str,
    ) -> Path:
        conditioning_dir = output_dir / "conditioning"
        conditioning_dir.mkdir(parents=True, exist_ok=True)
        destination = (conditioning_dir / filename).resolve()
        source_resolved = source_path.resolve()
        if destination != source_resolved:
            shutil.copy2(source_resolved, destination)
        return destination

    def _generate_depth_image(self, source_image_path: Path) -> Image.Image:
        estimator = self._load_estimator()
        with Image.open(source_image_path) as source_image:
            source_rgb = source_image.convert("RGB")
            source_size = source_rgb.size
        prediction = estimator(source_rgb)
        depth_image = self._coerce_depth_image(prediction)
        if depth_image.size != source_size:
            depth_image = depth_image.resize(source_size)
        return depth_image.convert("L")

    def _load_estimator(self) -> Any:
        if self._estimator is not None:
            return self._estimator
        try:
            from transformers import pipeline
        except Exception as exc:
            raise RuntimeError(
                "Auto depth generation requires transformers depth-estimation support."
            ) from exc
        try:
            self._estimator = pipeline(
                "depth-estimation",
                model=self._model_id,
                local_files_only=self._local_files_only,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize depth estimator '{self._model_id}': {exc}"
            ) from exc
        return self._estimator

    @staticmethod
    def _coerce_depth_image(prediction: Any) -> Image.Image:
        if isinstance(prediction, Mapping):
            if isinstance(prediction.get("depth"), Image.Image):
                return prediction["depth"].convert("L")
            candidate = prediction.get("predicted_depth")
        else:
            candidate = prediction

        if isinstance(candidate, Image.Image):
            return candidate.convert("L")

        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError("Auto depth generation requires numpy to normalize tensor output.") from exc

        if hasattr(candidate, "detach"):
            array = candidate.detach().cpu().numpy()
        else:
            array = np.asarray(candidate)
        if array.ndim > 2:
            array = array.squeeze()
        array = array.astype("float32")
        if array.size == 0:
            raise RuntimeError("Depth estimator returned an empty prediction.")
        min_value = float(array.min())
        max_value = float(array.max())
        if max_value <= min_value:
            normalized = np.zeros_like(array, dtype="uint8")
        else:
            normalized = ((array - min_value) / (max_value - min_value) * 255.0).clip(0, 255).astype("uint8")
        return Image.fromarray(normalized, mode="L")

    @staticmethod
    def _validate_image(path: Path) -> None:
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"Depth input is not a valid image: {path}") from exc


__all__ = [
    "DEFAULT_DEPTH_ESTIMATOR_MODEL_ID",
    "DepthMapResolver",
    "DepthResolutionResult",
    "VALID_DEPTH_INPUT_MODES",
]