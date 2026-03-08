from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PIL import Image

from src.utils.diagnostics_bundle_v2 import build_crash_bundle
from src.utils.image_metadata import build_contract_kv, write_image_metadata


def _write_png(path: Path) -> None:
    image = Image.new("RGB", (6, 6), color=(120, 130, 140))
    image.save(path)


def test_debughub_bundle_includes_image_metadata(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    image_dir = output_root / "run-1" / "txt2img"
    image_dir.mkdir(parents=True)

    image_with_meta = image_dir / "with_meta.png"
    _write_png(image_with_meta)
    payload = {
        "job_id": "job-1",
        "run_id": "run-1",
        "stage": "txt2img",
        "image": {"path": "with_meta.png", "width": 6, "height": 6, "format": "png"},
        "seeds": {"requested_seed": -1, "actual_seed": 1, "actual_subseed": 2},
        "njr": {"snapshot_version": "2.6", "sha256": ""},
        "stage_manifest": {"name": "with_meta", "timestamp": "", "config_hash": ""},
    }
    kv = build_contract_kv(payload, job_id="job-1", run_id="run-1", stage="txt2img")
    assert write_image_metadata(image_with_meta, kv) is True

    image_missing = image_dir / "missing_meta.png"
    _write_png(image_missing)

    bundle = build_crash_bundle(
        reason="debughub-meta",
        output_dir=tmp_path,
        image_roots=[output_root],
    )

    assert bundle is not None
    assert bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "artifacts/image_metadata/with_meta.png.meta.json" in names
        assert "artifacts/image_metadata/missing_meta.png.meta.missing.txt" in names
        meta = json.loads(zf.read("artifacts/image_metadata/with_meta.png.meta.json"))
        assert meta["payload"]["job_id"] == "job-1"
