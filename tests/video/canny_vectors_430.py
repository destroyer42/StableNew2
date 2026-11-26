"""Deterministic synthetic grayscale images for the Canny parity vectors (PR-VID-MOTION-430); no RNG, integer arithmetic."""

from __future__ import annotations

import numpy as np


def shapes(h: int = 40, w: int = 32) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = 0.15 + 0.2 * (x / w)
    img[8:24, 6:20] = 0.9
    img[(y - 28) ** 2 + (x - 22) ** 2 <= 25] = 0.05
    img[abs((y - x * 1.1) - 2) < 0.8] = 0.6
    return np.clip(img, 0, 1).astype(np.float32)


def textured(h: int = 48, w: int = 64) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.int64)
    noise = ((x * 73856093) ^ (y * 19349663) ^ 0x5BD1E995) % 61  # 0..60
    img = 0.35 + noise.astype(np.float32) / 400.0
    img[10:40, 20:44] = 0.85 - noise[10:40, 20:44].astype(np.float32) / 500.0
    img[:, 52:] = 0.1
    return np.clip(img, 0, 1).astype(np.float32)


def thin_line(h: int = 32, w: int = 32) -> np.ndarray:
    img = np.full((h, w), 0.08, dtype=np.float32)
    img[:, 15] = 0.95
    img[5, :] = 0.7
    return img


def step(h: int = 24, w: int = 40) -> np.ndarray:
    img = np.full((h, w), 0.2, dtype=np.float32)
    img[:, 17:] = 0.75
    return img


VECTORS = {"shapes": shapes, "textured": textured, "thin_line": thin_line, "step": step}


def pack(bits: np.ndarray) -> str:
    return np.packbits(bits.astype(np.uint8).ravel()).tobytes().hex()
