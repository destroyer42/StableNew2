"""CPU-only paired presentation; source images are opened read-only and never saved over."""

from __future__ import annotations

from pathlib import Path


def create_contact_sheet(pairs: list[tuple[str, Path, Path]], output: Path, tile: int = 512) -> None:
    from PIL import Image, ImageDraw, ImageOps

    if not pairs or tile <= 0:
        raise ValueError("Require pairs and positive tile dimensions")
    sheet = Image.new("RGB", (tile * 2, (tile + 40) * len(pairs)), "white")
    draw = ImageDraw.Draw(sheet)
    for row, (case, a1111, forge) in enumerate(pairs):
        for col, (label, path) in enumerate((("A1111", a1111), ("Forge", forge))):
            with Image.open(path) as source:
                presented = ImageOps.contain(source.convert("RGB"), (tile, tile))
            x, y = col * tile, row * (tile + 40)
            draw.text((x + 8, y + 8), f"{case}: {label}", fill="black")
            sheet.paste(presented, (x + (tile - presented.width) // 2, y + 40))
    with output.open("xb") as stream:
        sheet.save(stream, format="PNG")
