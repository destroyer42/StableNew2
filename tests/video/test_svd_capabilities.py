from __future__ import annotations

from pathlib import Path

from src.video.svd_capabilities import apply_recommended_svd_defaults, get_svd_postprocess_capabilities
from src.video.svd_config import SVDConfig


def test_get_svd_postprocess_capabilities_contains_expected_keys() -> None:
    result = get_svd_postprocess_capabilities(SVDConfig())

    assert set(result.keys()) == {"codeformer", "realesrgan", "rife", "gfpgan"}
    assert result["gfpgan"].status == "missing"


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


def test_apply_recommended_svd_defaults_enables_available_postprocess(tmp_path: Path, monkeypatch) -> None:
    codeformer_weight = tmp_path / "codeformer.pth"
    facelib_root = tmp_path / "GFPGAN"
    package_root = tmp_path / "site-packages" / "codeformer"
    realesrgan_weight = tmp_path / "realesrgan.pth"
    rife_executable = tmp_path / "rife-ncnn-vulkan.exe"
    codeformer_weight.write_bytes(b"weights")
    realesrgan_weight.write_bytes(b"weights")
    rife_executable.write_bytes(b"exe")
    facelib_root.mkdir()
    package_root.mkdir(parents=True)
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")

    monkeypatch.setattr("src.video.svd_capabilities._find_site_package_dir", lambda _name: package_root)
    monkeypatch.setenv("STABLENEW_RIFE_EXE", str(rife_executable))

    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "codeformer_weight_path": str(codeformer_weight),
                    "facelib_model_root": str(facelib_root),
                },
                "upscale": {
                    "model_path": str(realesrgan_weight),
                },
            }
        }
    )

    result = apply_recommended_svd_defaults(config)

    assert result.postprocess.face_restore.enabled is True
    assert result.postprocess.face_restore.method == "CodeFormer"
    assert result.postprocess.interpolation.enabled is True
    assert result.postprocess.interpolation.executable_path == str(rife_executable)
    assert result.postprocess.upscale.enabled is True


def test_apply_recommended_svd_defaults_falls_back_to_gfpgan_when_codeformer_missing(tmp_path: Path, monkeypatch) -> None:
    facelib_root = tmp_path / "GFPGAN"
    gfpgan_weight = tmp_path / "GFPGANv1.4.pth"
    package_root = tmp_path / "site-packages" / "gfpgan"
    facelib_root.mkdir()
    package_root.mkdir(parents=True)
    gfpgan_weight.write_bytes(b"weights")
    (facelib_root / "detection_Resnet50_Final.pth").write_bytes(b"det")
    (facelib_root / "parsing_parsenet.pth").write_bytes(b"parse")

    def _fake_find_site_package_dir(name: str):
        if name == "gfpgan":
            return package_root
        return None

    monkeypatch.setattr("src.video.svd_capabilities._find_site_package_dir", _fake_find_site_package_dir)
    monkeypatch.setattr("src.video.svd_postprocess.importlib.util.find_spec", lambda name: object() if name == "gfpgan" else None)

    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "gfpgan_weight_path": str(gfpgan_weight),
                    "facelib_model_root": str(facelib_root),
                }
            }
        }
    )

    result = apply_recommended_svd_defaults(config)

    assert result.postprocess.face_restore.enabled is True
    assert result.postprocess.face_restore.method == "GFPGAN"
