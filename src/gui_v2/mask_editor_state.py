"""Original-pixel mask editing and viewport transforms; no Tk, files or backend state."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw


@dataclass
class MaskViewport:
    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0

    def image_point(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x) / self.scale, (y - self.y) / self.scale

    def zoom(self, factor: float, x: float, y: float) -> None:
        ix, iy = self.image_point(x, y)
        self.scale = max(0.05, min(8.0, self.scale * factor))
        self.x, self.y = x - ix * self.scale, y - iy * self.scale

    def fit(self, size: tuple[int, int], view: tuple[int, int]) -> None:
        self.scale = min(view[0] / size[0], view[1] / size[1])
        self.x = (view[0] - size[0] * self.scale) / 2
        self.y = (view[1] - size[1] * self.scale) / 2


class MaskDocument:
    """White changes, black preserves. One undo entry per gesture, bounded to 64 MiB."""

    def __init__(self, size: tuple[int, int]) -> None:
        self.mask = Image.new("L", size, 0)
        self.revision = 0
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._limit = max(1, min(20, 64 * 1024 * 1024 // (size[0] * size[1])))

    def checkpoint(self) -> None:
        self._undo.append(self.mask.tobytes())
        self._undo = self._undo[-self._limit :]
        self._redo.clear()

    def paint(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        size: int,
        *,
        erase: bool = False,
    ) -> None:
        if not 1 <= size <= 512:
            raise ValueError("Brush size must be 1 through 512 original-image pixels")
        draw = ImageDraw.Draw(self.mask)
        value = 0 if erase else 255
        draw.line([start, end], fill=value, width=size)
        radius = (size - 1) / 2
        for x, y in (start, end):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=value)
        self.revision += 1

    def clear(self) -> None:
        self.checkpoint()
        self.mask.paste(0, (0, 0, *self.mask.size))
        self.revision += 1

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.mask.tobytes())
            self.mask = Image.frombytes("L", self.mask.size, self._undo.pop())
            self.revision += 1

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.mask.tobytes())
            self.mask = Image.frombytes("L", self.mask.size, self._redo.pop())
            self.revision += 1

    def render(
        self, image: Image.Image, viewport: MaskViewport, size: tuple[int, int]
    ) -> Image.Image:
        """Render only the visible canvas, so zoom never allocates a giant scaled source."""
        transform = (
            1 / viewport.scale,
            0,
            -viewport.x / viewport.scale,
            0,
            1 / viewport.scale,
            -viewport.y / viewport.scale,
        )
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        background = rgb.transform(
            size,
            Image.Transform.AFFINE,
            transform,
            resample=Image.Resampling.BILINEAR,
            fillcolor=(35, 35, 35),
        )
        mask = self.mask.transform(
            size, Image.Transform.AFFINE, transform, resample=Image.Resampling.NEAREST
        )
        alpha = mask.point(lambda value: value * 110 // 255)
        return Image.composite(Image.new("RGB", size, (255, 45, 45)), background, alpha)
