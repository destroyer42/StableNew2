from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.utils.file_io import save_image_from_base64
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    build_contract_kv,
    decode_payload,
    read_image_metadata,
)


def _png_base64(size: tuple[int, int] = (8, 8)) -> str:
    image = Image.new("RGB", size, color=(10, 20, 30))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_save_image_from_base64_embeds_png_metadata_inline(tmp_path: Path) -> None:
    output_path = tmp_path / "inline-meta.png"
    payload = {
        "job_id": "job-inline",
        "run_id": "run-inline",
        "stage": "txt2img",
        "image": {"path": str(output_path), "width": 8, "height": 8, "format": "png"},
        "generation": {"prompt": "inline metadata prompt"},
    }

    def _build_metadata(_image: Image.Image) -> dict[str, str]:
        return build_contract_kv(
            payload,
            job_id="job-inline",
            run_id="run-inline",
            stage="txt2img",
        )

    with patch("src.utils.image_metadata.write_image_metadata") as write_spy:
        saved_path = save_image_from_base64(
            _png_base64(),
            output_path,
            metadata_builder=_build_metadata,
        )

    assert saved_path == output_path.resolve()
    assert write_spy.called is False

    stored = read_image_metadata(saved_path)
    assert stored[ImageMetadataContractV26.KEY_SCHEMA] == ImageMetadataContractV26.SCHEMA
    decoded = decode_payload(stored)
    assert decoded.status == "ok"
    assert decoded.payload == payload
