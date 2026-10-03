"""Optional restoration runtime: truthful readiness, import isolation, legacy retirement.

Pure Python (no torch/cv2/model libraries), so it also runs in the required GitHub gate.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.video.restoration import runtime
from src.video.svd_capabilities import get_svd_postprocess_capabilities
from src.video.svd_config import SVDConfig
from src.video.svd_postprocess import (
    get_codeformer_runtime_issues,
    get_realesrgan_runtime_issues,
    validate_svd_postprocess_config,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _assets(tmp_path: Path) -> dict[str, str]:
    weight = tmp_path / "codeformer.pth"
    esrgan = tmp_path / "RealESRGAN_x4plus.pth"
    facelib = tmp_path / "GFPGAN"
    facelib.mkdir()
    weight.write_bytes(b"w")
    esrgan.write_bytes(b"w")
    (facelib / "detection_Resnet50_Final.pth").write_bytes(b"d")
    (facelib / "parsing_parsenet.pth").write_bytes(b"p")
    return {"codeformer": str(weight), "esrgan": str(esrgan), "facelib": str(facelib)}


def _config(assets: dict[str, str], **enabled: bool) -> SVDConfig:
    return SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {
                    "enabled": enabled.get("face", False),
                    "method": "CodeFormer",
                    "codeformer_weight_path": assets["codeformer"],
                    "facelib_model_root": assets["facelib"],
                },
                "upscale": {"enabled": enabled.get("upscale", False), "model_path": assets["esrgan"]},
            }
        }
    )


def _present(monkeypatch: pytest.MonkeyPatch, names: set[str]) -> None:
    monkeypatch.setattr(runtime, "_module_available", lambda name: name in names)


def test_missing_packages_names_distributions_not_import_names(monkeypatch) -> None:
    _present(monkeypatch, {"spandrel"})

    assert runtime.missing_packages("upscale") == ["opencv-python package"]
    assert runtime.missing_packages("codeformer") == [
        "spandrel-extra-arches package",
        "codeformer package",  # provides the legacy `facelib` face helper
        "opencv-python package",
    ]


def test_readiness_is_ready_only_when_packages_weights_and_facelib_all_exist(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path)
    config = _config(assets, face=True, upscale=True)
    _present(monkeypatch, {"spandrel", "spandrel_extra_arches", "facelib", "cv2"})

    caps = get_svd_postprocess_capabilities(config)

    assert caps["codeformer"].available and caps["codeformer"].status == "ready"
    assert caps["realesrgan"].available
    assert get_codeformer_runtime_issues(config.postprocess) == []
    assert get_realesrgan_runtime_issues(config.postprocess) == []


def test_missing_optional_packages_block_admission_with_an_install_action(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path)
    _present(monkeypatch, set())

    for kwargs, label in (({"face": True}, "CodeFormer"), ({"upscale": True}, "RealESRGAN")):
        valid, reason = validate_svd_postprocess_config(_config(assets, **kwargs))
        assert valid is False and reason is not None
        assert f"{label} is enabled" in reason and "spandrel package" in reason
        assert "bootstrap_windows.ps1 -WithPostprocess" in reason

    caps = get_svd_postprocess_capabilities(_config(assets))
    assert not caps["codeformer"].available
    assert "-WithPostprocess" in caps["codeformer"].detail


def test_missing_weights_remain_actionable_without_an_install_hint(
    tmp_path: Path, monkeypatch
) -> None:
    assets = _assets(tmp_path)
    Path(assets["esrgan"]).unlink()
    _present(monkeypatch, {"spandrel", "cv2"})

    valid, reason = validate_svd_postprocess_config(_config(assets, upscale=True))

    assert valid is False and reason is not None
    assert "RealESRGAN weight" in reason and "-WithPostprocess" not in reason


def test_disabled_postprocessing_is_valid_without_any_optional_package(
    tmp_path: Path, monkeypatch
) -> None:
    _present(monkeypatch, set())

    assert validate_svd_postprocess_config(_config(_assets(tmp_path))) == (True, None)
    assert validate_svd_postprocess_config(SVDConfig()) == (True, None)


def test_gfpgan_is_a_named_method_that_is_never_reported_available(
    tmp_path: Path, monkeypatch
) -> None:
    _present(monkeypatch, {"spandrel", "spandrel_extra_arches", "facelib", "cv2", "gfpgan"})
    gfpgan = tmp_path / "GFPGANv1.4.pth"
    gfpgan.write_bytes(b"w")

    caps = get_svd_postprocess_capabilities(
        SVDConfig.from_dict({"postprocess": {"face_restore": {"gfpgan_weight_path": str(gfpgan)}}})
    )

    assert caps["gfpgan"].available is False
    assert runtime.GFPGAN_UNSUPPORTED_ISSUE in caps["gfpgan"].detail


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


_BLOCK_OPTIONAL = """
    import sys

    class _Block:
        blocked = {"basicsr", "facexlib", "facelib", "codeformer", "gfpgan", "spandrel",
                   "spandrel_extra_arches", "cv2", "torchvision", "torch", "numpy", "lpips"}

        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in self.blocked:
                raise ImportError("blocked " + name)

    sys.meta_path.insert(0, _Block())
"""


def test_core_modules_import_with_every_restoration_and_ml_package_blocked() -> None:
    result = _run_isolated(
        _BLOCK_OPTIONAL
        + """
    import src.video.svd_postprocess_worker
    import src.video.svd_postprocess
    import src.video.svd_capabilities
    from src.video.svd_config import SVDConfig
    from src.video.svd_postprocess import validate_svd_postprocess_config

    assert validate_svd_postprocess_config(SVDConfig()) == (True, None)
    """
    )

    assert result.returncode == 0, result.stderr


def test_capability_probe_never_imports_a_model_library() -> None:
    result = _run_isolated(
        """
    import sys
    from src.video.svd_capabilities import get_svd_postprocess_capabilities
    from src.video.svd_config import SVDConfig

    get_svd_postprocess_capabilities(SVDConfig())
    loaded = [m for m in ("spandrel", "spandrel_extra_arches", "facexlib", "torchvision", "cv2")
              if m in sys.modules]
    assert not loaded, loaded
    """
    )

    assert result.returncode == 0, result.stderr


# --- Legacy retirement guards ---------------------------------------------------------------

_BANNED_IMPORTS = {"basicsr", "facexlib", "codeformer", "gfpgan", "realesrgan"}
# The legacy face helper is retained, isolated in exactly one module (see its docstring).
_FACELIB_ALLOWED = {Path("src/video/restoration/legacy_face_helper.py")}


def _production_sources() -> list[Path]:
    return [path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts]


def test_only_the_isolated_legacy_helper_module_imports_facelib() -> None:
    importers = set()
    for path in _production_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(name.split(".")[0] == "facelib" for name in names):
                importers.add(path.relative_to(ROOT))

    assert importers == _FACELIB_ALLOWED


def test_no_production_module_imports_the_legacy_restoration_stack() -> None:
    offenders = []
    for path in _production_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name.split(".")[0] in _BANNED_IMPORTS for name in names):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_torchvision_compat_shim_and_package_root_mutation_are_gone() -> None:
    worker_and_adapters = [
        SRC / "video" / "svd_postprocess_worker.py",
        *(SRC / "video" / "restoration").glob("*.py"),
    ]
    for path in worker_and_adapters:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        assert "functional_tensor" not in text, path.name
        assert "_install_torchvision_compat_shims" not in text, path.name
        calls = {
            ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        assert "os.chdir" not in calls, path.name
        assert "sys.path.insert" not in calls, path.name
        assert "site.getsitepackages" not in calls, path.name
        assert "shutil.copy2" not in calls, path.name  # no copying weights into site-packages
    assert "functional_tensor" not in "\n".join(
        path.read_text(encoding="utf-8") for path in _production_sources()
    )
