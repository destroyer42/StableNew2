"""StableNew-owned restoration adapters, exercised with fake models/helpers (no weights)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from PIL import Image  # noqa: E402

from src.video.restoration import codeformer as codeformer_module  # noqa: E402
from src.video.restoration import model_loader, upscaler  # noqa: E402
from src.video.restoration.runtime import WORKER_WARNING_PREFIX  # noqa: E402

CPU = torch.device("cpu")


# --- RRDB upscaler -------------------------------------------------------------------------


class _CountingNearest(torch.nn.Module):
    """A deterministic 'network': nearest-neighbour upsampling that counts invocations."""

    def __init__(self, scale: int) -> None:
        super().__init__()
        self.scale = scale
        self.calls = 0

    def forward(self, tensor):
        self.calls += 1
        return torch.nn.functional.interpolate(tensor, scale_factor=self.scale, mode="nearest")


def _upscaler(monkeypatch, *, scale: int, tile: int = 0, tile_pad: int = 40):
    network = _CountingNearest(scale)
    monkeypatch.setattr(
        upscaler,
        "load_image_model",
        lambda *args, **kwargs: SimpleNamespace(model=network, scale=scale),
    )
    instance = upscaler.RRDBUpscaler(
        "weights.pth", tile=tile, tile_pad=tile_pad, device=CPU, half=False
    )
    return instance, network


def _bgr(height: int = 13, width: int = 17):
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def test_untiled_upscale_keeps_geometry_and_colour_order(monkeypatch) -> None:
    instance, network = _upscaler(monkeypatch, scale=4)
    image = _bgr()

    result = instance.enhance(image)

    assert result.dtype == np.uint8 and result.shape == (52, 68, 3)
    assert np.array_equal(result, np.repeat(np.repeat(image, 4, axis=0), 4, axis=1))
    assert network.calls == 1


def test_outscale_resizes_to_the_requested_scale_without_changing_channel_order(
    monkeypatch,
) -> None:
    instance, _network = _upscaler(monkeypatch, scale=4)

    result = instance.enhance(_bgr(), outscale=2.0)

    assert result.shape == (26, 34, 3)


def test_tile_is_forwarded_and_stitching_matches_the_untiled_result(monkeypatch) -> None:
    untiled, untiled_net = _upscaler(monkeypatch, scale=4, tile=0)
    tiled, tiled_net = _upscaler(monkeypatch, scale=4, tile=6, tile_pad=3)
    image = _bgr()

    assert np.array_equal(tiled.enhance(image), untiled.enhance(image))
    assert untiled_net.calls == 1
    assert tiled_net.calls == 3 * 3  # ceil(13/6) rows x ceil(17/6) columns


def test_two_times_network_pads_odd_borders_and_crops_back(monkeypatch) -> None:
    instance, _network = _upscaler(monkeypatch, scale=2)
    image = _bgr(13, 17)

    result = instance.enhance(image)

    assert result.shape == (26, 34, 3)
    assert np.array_equal(result, np.repeat(np.repeat(image, 2, axis=0), 2, axis=1))


def test_only_three_channel_8bit_frames_are_accepted(monkeypatch) -> None:
    instance, _network = _upscaler(monkeypatch, scale=4)

    with pytest.raises(ValueError, match="3-channel"):
        instance.enhance(np.zeros((8, 8), dtype=np.uint8))


def test_tile_failures_propagate_instead_of_producing_a_black_tile(monkeypatch) -> None:
    instance, network = _upscaler(monkeypatch, scale=4, tile=6)

    def _fail(_tensor):
        raise RuntimeError("CUDA out of memory")

    instance.model = _fail
    with pytest.raises(RuntimeError, match="out of memory"):
        instance.enhance(_bgr())
    assert network.calls == 0


# --- CodeFormer restorer -------------------------------------------------------------------


class _Helper:
    def __init__(self, faces: int, size: int = 32) -> None:
        self._faces = faces
        self._size = size
        self.cropped_faces: list = []
        self.restored: list = []
        self.landmarks_kwargs: dict | None = None
        self.paste_kwargs: dict | None = None
        self.read: object = None
        self.inverse_called = False

    def clean_all(self) -> None:
        self.cropped_faces = []
        self.restored = []

    def read_image(self, bgr) -> None:
        self.read = bgr

    def get_face_landmarks_5(self, **kwargs) -> None:
        self.landmarks_kwargs = kwargs

    def align_warp_face(self) -> None:
        rng = np.random.default_rng(3)
        self.cropped_faces = [
            rng.integers(0, 256, size=(self._size, self._size, 3), dtype=np.uint8)
            for _ in range(self._faces)
        ]

    def add_restored_face(self, restored, cropped) -> None:
        self.restored.append((restored, cropped))

    def get_inverse_affine(self, _path) -> None:
        self.inverse_called = True

    def paste_faces_to_input_image(self, **kwargs):
        self.paste_kwargs = kwargs
        return self.read


class _Model:
    """Identity 'network' that records the fidelity `weight` it was given (Spandrel's kwarg)."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def __call__(self, tensor, weight):
        self.calls.append({"weight": weight})
        if self.fail:
            raise RuntimeError("boom")
        return (tensor,)


def _restorer(helper, model):
    return codeformer_module.CodeFormerRestorer(
        weight_path="unused", facelib_model_root="unused", device=CPU, helper=helper, model=model
    )


def test_frames_without_faces_pass_through_untouched() -> None:
    helper, model = _Helper(faces=0), _Model()
    image = Image.new("RGB", (40, 24), (10, 20, 30))

    result = _restorer(helper, model).restore(image, fidelity=0.7)

    assert result.size == (40, 24) and result.getpixel((5, 5)) == (10, 20, 30)
    assert model.calls == [] and helper.restored == [] and helper.paste_kwargs is None


def test_every_detected_face_is_restored_with_the_requested_fidelity() -> None:
    helper, model = _Helper(faces=2), _Model()
    image = Image.new("RGB", (40, 24), (10, 20, 30))

    result = _restorer(helper, model).restore(image, fidelity=0.3)

    assert result.size == (40, 24) and result.mode == "RGB"
    assert model.calls == [{"weight": 0.3}] * 2
    assert len(helper.restored) == 2
    for restored, cropped in helper.restored:  # identity network: tensor round trip is lossless
        assert restored.dtype == np.uint8 and np.abs(restored.astype(int) - cropped).max() <= 1
    assert helper.landmarks_kwargs == {
        "only_center_face": False,
        "resize": 640,
        "eye_dist_threshold": 5,
    }
    assert helper.paste_kwargs == {"upsample_img": None, "draw_box": False}
    assert helper.inverse_called


def test_frame_is_handed_to_the_helper_as_bgr_and_returned_as_rgb() -> None:
    helper = _Helper(faces=0)
    image = Image.new("RGB", (8, 8), (10, 20, 30))

    _restorer(helper, _Model()).restore(image, fidelity=0.7)

    assert tuple(int(v) for v in helper.read[0, 0]) == (30, 20, 10)


def test_a_face_that_cannot_be_restored_is_reported_and_left_unrestored(capsys) -> None:
    helper, model = _Helper(faces=1), _Model(fail=True)

    result = _restorer(helper, model).restore(Image.new("RGB", (40, 24), "white"), fidelity=0.7)

    assert result.size == (40, 24)
    stderr = capsys.readouterr().err
    # Tagged so the runner can log it and record it in stage metadata (a successful worker exit
    # would otherwise discard stderr).
    assert stderr.startswith(WORKER_WARNING_PREFIX) and "left unrestored" in stderr
    restored, cropped = helper.restored[0]
    assert np.abs(restored.astype(int) - cropped).max() <= 1


def test_missing_facelib_files_fail_before_facelib_could_download_anything(
    tmp_path: Path,
) -> None:
    (tmp_path / "detection_Resnet50_Final.pth").write_bytes(b"d")  # parsing model absent

    with pytest.raises(model_loader.RestorationRuntimeError, match="parsing_parsenet.pth"):
        codeformer_module.CodeFormerRestorer(
            weight_path="unused", facelib_model_root=str(tmp_path), device=CPU, model=_Model()
        )
    with pytest.raises(model_loader.RestorationRuntimeError, match="Face model root not found"):
        codeformer_module.CodeFormerRestorer(
            weight_path="unused",
            facelib_model_root=str(tmp_path / "missing"),
            device=CPU,
            model=_Model(),
        )


def test_legacy_helper_gets_the_explicit_model_root_without_process_or_path_side_effects(
    tmp_path: Path, monkeypatch
) -> None:
    for name in ("detection_Resnet50_Final.pth", "parsing_parsenet.pth"):
        (tmp_path / name).write_bytes(b"x")
    captured: dict = {}
    detection = types.ModuleType("facelib.detection")
    parsing = types.ModuleType("facelib.parsing")
    detection.WEIGHTS_DIR = parsing.WEIGHTS_DIR = "site-packages/codeformer/weights/facelib"

    class _FakeHelper:
        def __init__(self, *args, **kwargs) -> None:
            # Weights are looked up while the helper is built, so the override must be active.
            captured.update(args=args, kwargs=kwargs, dirs=(detection.WEIGHTS_DIR, parsing.WEIGHTS_DIR))

    helper_module = types.ModuleType("facelib.utils.face_restoration_helper")
    helper_module.FaceRestoreHelper = _FakeHelper
    for name, module in (
        ("facelib", types.ModuleType("facelib")),
        ("facelib.detection", detection),
        ("facelib.parsing", parsing),
        ("facelib.utils", types.ModuleType("facelib.utils")),
        ("facelib.utils.face_restoration_helper", helper_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    cwd, path = os.getcwd(), list(sys.path)

    restorer = codeformer_module.CodeFormerRestorer(
        weight_path="unused", facelib_model_root=str(tmp_path), device=CPU, model=_Model()
    )

    assert isinstance(restorer.helper, _FakeHelper)
    assert captured["args"] == (1,)
    assert captured["kwargs"] == {
        "face_size": 512,
        "crop_ratio": (1, 1),
        "det_model": "retinaface_resnet50",
        "save_ext": "png",
        "use_parse": True,
        "device": CPU,
    }
    assert captured["dirs"] == (str(tmp_path), str(tmp_path))
    # The override is scoped to construction: facelib's own defaults are restored afterwards.
    assert detection.WEIGHTS_DIR == parsing.WEIGHTS_DIR == "site-packages/codeformer/weights/facelib"
    assert os.getcwd() == cwd and sys.path == path


# --- Spandrel loader seam ------------------------------------------------------------------


def _fake_spandrel(monkeypatch, arch_id: str):
    events: list[str] = []

    class _Descriptor:
        scale = 4
        architecture = SimpleNamespace(id=arch_id)
        model = object()

        def to(self, device):
            events.append(f"to:{device}")

        def eval(self):
            events.append("eval")

        def half(self):
            events.append("half")

    class _Loader:
        def load_from_file(self, path):
            events.append(f"load:{Path(path).name}")
            return _Descriptor()

    spandrel = types.ModuleType("spandrel")
    spandrel.ModelLoader = _Loader
    extra = types.ModuleType("spandrel_extra_arches")
    extra.install = lambda: events.append("install_extra_arches")
    monkeypatch.setitem(sys.modules, "spandrel", spandrel)
    monkeypatch.setitem(sys.modules, "spandrel_extra_arches", extra)
    return events


def test_loader_builds_the_expected_architecture_on_the_requested_device(
    tmp_path: Path, monkeypatch
) -> None:
    weight = tmp_path / "RealESRGAN_x4plus.pth"
    weight.write_bytes(b"w")
    events = _fake_spandrel(monkeypatch, "ESRGAN")

    descriptor = model_loader.load_image_model(
        weight, expected_architecture="ESRGAN", device=CPU, half=True
    )

    assert descriptor.scale == 4
    assert events == ["load:RealESRGAN_x4plus.pth", "to:cpu", "eval", "half"]


def test_loader_rejects_a_checkpoint_of_a_different_architecture(
    tmp_path: Path, monkeypatch
) -> None:
    weight = tmp_path / "other.pth"
    weight.write_bytes(b"w")
    _fake_spandrel(monkeypatch, "SwinIR")

    with pytest.raises(model_loader.RestorationRuntimeError, match="SwinIR checkpoint; ESRGAN"):
        model_loader.load_image_model(weight, expected_architecture="ESRGAN", device=CPU)


def test_loader_rejects_a_missing_weight_file_and_registers_codeformer_arches(
    tmp_path: Path, monkeypatch
) -> None:
    with pytest.raises(model_loader.RestorationRuntimeError, match="not found"):
        model_loader.load_image_model(
            tmp_path / "missing.pth", expected_architecture="CodeFormer", device=CPU
        )
    weight = tmp_path / "codeformer.pth"
    weight.write_bytes(b"w")
    events = _fake_spandrel(monkeypatch, "CodeFormer")

    model_loader.load_image_model(weight, expected_architecture="CodeFormer", device=CPU)

    assert events[0] == "install_extra_arches"
