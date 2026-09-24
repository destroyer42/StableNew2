"""PR-VID-181 preprocessing-gate provenance: pinned upstream identity, frozen model names,
production-environment rejection, hashing, and the deterministic final pose-control adaptation.

Pure/stdlib+numpy+cv2 only: importable from the StableNew ``.venv`` for tests. The upstream
detector/pose stack itself runs only in the disposable CPU-only environment (see
``preprocess_launcher``), never in a StableNew/Comfy/A1111 environment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

UPSTREAM_REPO = "https://github.com/Wan-Video/Wan2.2.git"
UPSTREAM_SHA = "1ea34ff48f87168174e12956e200b1d908b1c5ff"
CHECKPOINT_REPO = "Wan-AI/Wan2.2-Animate-14B"
CHECKPOINT_REVISION = "cb93a225fbaf1ca100f54e79da8f994995b689b3"
DET_MODEL = "det/yolov10m.onnx"
POSE_MODEL = "pose2d/vitpose_h_wholebody.onnx"  # a directory: end2end.onnx + external weights
PROVIDER = "CPUExecutionProvider"

WIDTH = 480
HEIGHT = 832
FRAMES = 13
FPS = 8.0
UPSTREAM_DIVISOR = 16  # upstream replacement-mode divisor; default 64 would give 448x832 here

# Path fragments that identify runtimes the preprocessing environment must never be.
PRODUCTION_ENV_MARKERS = (
    "stablenew\\.venv",
    "stablenew/.venv",
    "comfyui",
    "comfy",
    "stable-diffusion-webui",
    "automatic1111",
    "a1111",
    ".venv-explicit",
)

__all__ = [
    "UPSTREAM_SHA",
    "CHECKPOINT_REVISION",
    "DET_MODEL",
    "POSE_MODEL",
    "PROVIDER",
    "WIDTH",
    "HEIGHT",
    "FRAMES",
    "FPS",
    "assert_isolated_env",
    "sha256_of",
    "tree_sha256",
    "select_indices",
    "adapt_pose_to_frozen",
]


def assert_isolated_env(prefix: str | Path) -> None:
    """Reject any interpreter prefix that looks like a production runtime environment."""

    lowered = str(prefix).replace("/", "\\").lower()
    for marker in PRODUCTION_ENV_MARKERS:
        if marker.replace("/", "\\").lower() in lowered:
            raise RuntimeError(
                f"refusing to run preprocessing in a production-looking environment: {prefix}"
            )


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> dict[str, object]:
    """Deterministic manifest hash of a directory of files (relative path + per-file SHA-256)."""

    root = Path(root)
    entries = []
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total += size
        entries.append(f"{rel}\t{size}\t{sha256_of(path)}")
    manifest = "\n".join(entries).encode("utf-8")
    return {
        "files": len(entries),
        "bytes": total,
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }


def select_indices(total: int, count: int = FRAMES) -> list[int]:
    """Evenly spaced frame indices over ``[0, total-1]`` (same convention as PR-VID-160C)."""

    import numpy as np

    if total < 1 or count < 1:
        raise ValueError("total and count must be positive")
    return [int(i) for i in np.linspace(0, total - 1, num=min(count, total))]


def adapt_pose_to_frozen(
    source: Path, target: Path, *, indices: list[int] | None = None
) -> tuple[Path, list[int], dict[str, object]]:
    """Select ``FRAMES`` frames from the full upstream ``src_pose.mp4`` and write them at the
    frozen ``WIDTH x HEIGHT`` / ``FPS``. No stretching: a frame already at the frozen geometry is
    written unchanged; any other geometry is letterboxed (aspect-preserving, black padding) and
    the operation is recorded."""

    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(source))
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if len(frames) < 2:
        raise ValueError(f"{source} has fewer than 2 decodable frames")
    chosen = indices if indices is not None else select_indices(len(frames), FRAMES)
    height, width = frames[0].shape[:2]
    operation: dict[str, object] = {"source_size": [width, height], "operation": "none"}
    if (width, height) != (WIDTH, HEIGHT):
        scale = min(WIDTH / width, HEIGHT / height)
        new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
        operation = {
            "source_size": [width, height],
            "operation": "aspect_preserving_letterbox",
            "scaled_size": [new_w, new_h],
            "canvas": [WIDTH, HEIGHT],
            "pad_color": [0, 0, 0],
        }

    def fit(frame: np.ndarray) -> np.ndarray:
        if operation["operation"] == "none":
            return frame
        new_w, new_h = operation["scaled_size"]  # type: ignore[misc]
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        top, left = (HEIGHT - new_h) // 2, (WIDTH - new_w) // 2
        canvas[top : top + new_h, left : left + new_w] = resized
        return canvas

    target.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    try:
        for index in chosen:
            writer.write(fit(frames[index]))
    finally:
        writer.release()
    operation["source_frame_count"] = len(frames)
    return target, chosen, operation
