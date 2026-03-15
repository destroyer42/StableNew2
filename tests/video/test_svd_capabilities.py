from __future__ import annotations

from pathlib import Path

from src.video.svd_capabilities import get_svd_postprocess_capabilities
from src.video.svd_config import SVDConfig


def test_get_svd_postprocess_capabilities_contains_expected_keys() -> None:
    result = get_svd_postprocess_capabilities(SVDConfig())

    assert set(result.keys()) == {"codeformer", "realesrgan", "rife", "gfpgan"}
    assert result["gfpgan"].status == "blocked"


def test_get_svd_postprocess_capabilities_marks_codeformer_ready_when_assets_exist(tmp_path: Path, monkeypatch) -> None:
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    package_root = tmp_path / "site-packages" / "codeformer"
    codeformer_weight.write_bytes(b"weights")
    facelib_root.mkdir()
    package_root.mkdir(parents=True)
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")
    monkeypatch.setattr("src.video.svd_capabilities._find_site_package_dir", lambda _name: package_root)
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": True,
                    "codeformer_weight_path": str(codeformer_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )

    result = get_svd_postprocess_capabilities(config)

    assert result["codeformer"].status == "ready"
    assert result["codeformer"].available is True
