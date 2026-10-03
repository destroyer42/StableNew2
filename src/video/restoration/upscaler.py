"""RealESRGAN-style RRDB upscaling with StableNew-owned padding, tiling and resizing.

Spandrel supplies the network; the tiling/padding/resize semantics below intentionally mirror
the behaviour StableNew has always had so the product output does not change.
"""

from __future__ import annotations

import math
from typing import Any

from src.video.restoration.model_loader import load_image_model, select_device

_TILE_PAD = 40
_PRE_PAD = 0


class RRDBUpscaler:
    """Upscale 8-bit BGR frames with an RRDB/RealESRGAN checkpoint."""

    def __init__(
        self,
        model_path: str,
        *,
        tile: int = 0,
        tile_pad: int = _TILE_PAD,
        pre_pad: int = _PRE_PAD,
        device: Any = None,
        half: bool | None = None,
    ) -> None:
        import torch

        self._torch = torch
        self.device = device if device is not None else select_device()
        self.half = bool(torch.cuda.is_available()) if half is None else half
        self.tile = int(tile)
        self.tile_pad = int(tile_pad)
        self.pre_pad = int(pre_pad)
        descriptor = load_image_model(
            model_path, expected_architecture="ESRGAN", device=self.device, half=self.half
        )
        self.model = descriptor.model
        self.scale = int(descriptor.scale)

    def enhance(self, bgr: Any, *, outscale: float | None = None) -> Any:
        """Return the upscaled BGR uint8 image, resized to ``outscale`` when it differs."""

        import cv2
        import numpy as np

        torch = self._torch
        if bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError("RRDBUpscaler expects an 8-bit 3-channel BGR image")
        height, width = bgr.shape[0:2]
        rgb = cv2.cvtColor(bgr.astype(np.float32) / 255, cv2.COLOR_BGR2RGB)

        with torch.no_grad():
            tensor = torch.from_numpy(np.transpose(rgb, (2, 0, 1))).float().unsqueeze(0)
            tensor = tensor.to(self.device)
            if self.half:
                tensor = tensor.half()
            tensor, pad_h, pad_w = self._pre_process(tensor)
            output = self._tiled(tensor) if self.tile > 0 else self.model(tensor)
            output = self._post_process(output, pad_h, pad_w)
            result = output.data.squeeze().float().cpu().clamp_(0, 1).numpy()
        result = np.transpose(result[[2, 1, 0], :, :], (1, 2, 0))
        upscaled = (result * 255.0).round().astype(np.uint8)

        if outscale is not None and outscale != float(self.scale):
            upscaled = cv2.resize(
                upscaled,
                (int(width * outscale), int(height * outscale)),
                interpolation=cv2.INTER_LANCZOS4,
            )
        return upscaled

    def _mod_scale(self) -> int | None:
        if self.scale == 2:
            return 2
        if self.scale == 1:
            return 4
        return None

    def _pre_process(self, tensor: Any) -> tuple[Any, int, int]:
        functional = self._torch.nn.functional
        if self.pre_pad != 0:
            tensor = functional.pad(tensor, (0, self.pre_pad, 0, self.pre_pad), "reflect")
        pad_h = pad_w = 0
        mod_scale = self._mod_scale()
        if mod_scale is not None:
            _, _, h, w = tensor.size()
            if h % mod_scale != 0:
                pad_h = mod_scale - h % mod_scale
            if w % mod_scale != 0:
                pad_w = mod_scale - w % mod_scale
            tensor = functional.pad(tensor, (0, pad_w, 0, pad_h), "reflect")
        return tensor, pad_h, pad_w

    def _post_process(self, output: Any, pad_h: int, pad_w: int) -> Any:
        if self._mod_scale() is not None:
            _, _, h, w = output.size()
            output = output[:, :, 0 : h - pad_h * self.scale, 0 : w - pad_w * self.scale]
        if self.pre_pad != 0:
            _, _, h, w = output.size()
            output = output[:, :, 0 : h - self.pre_pad * self.scale, 0 : w - self.pre_pad * self.scale]
        return output

    def _tiled(self, tensor: Any) -> Any:
        """Process padded tiles and stitch them; a tile failure propagates (never zero-filled)."""

        batch, channel, height, width = tensor.shape
        output = tensor.new_zeros((batch, channel, height * self.scale, width * self.scale))
        tiles_x = math.ceil(width / self.tile)
        tiles_y = math.ceil(height / self.tile)
        for y in range(tiles_y):
            for x in range(tiles_x):
                start_x = x * self.tile
                end_x = min(start_x + self.tile, width)
                start_y = y * self.tile
                end_y = min(start_y + self.tile, height)
                pad_start_x = max(start_x - self.tile_pad, 0)
                pad_end_x = min(end_x + self.tile_pad, width)
                pad_start_y = max(start_y - self.tile_pad, 0)
                pad_end_y = min(end_y + self.tile_pad, height)

                tile_out = self.model(tensor[:, :, pad_start_y:pad_end_y, pad_start_x:pad_end_x])

                out_start_x = start_x * self.scale
                out_end_x = end_x * self.scale
                out_start_y = start_y * self.scale
                out_end_y = end_y * self.scale
                crop_start_x = (start_x - pad_start_x) * self.scale
                crop_end_x = crop_start_x + (end_x - start_x) * self.scale
                crop_start_y = (start_y - pad_start_y) * self.scale
                crop_end_y = crop_start_y + (end_y - start_y) * self.scale
                output[:, :, out_start_y:out_end_y, out_start_x:out_end_x] = tile_out[
                    :, :, crop_start_y:crop_end_y, crop_start_x:crop_end_x
                ]
        return output
