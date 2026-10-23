"""PR-IMG-CNET-230: the worker's model glue against fake ``torch`` / ``transformers`` / ``onnxruntime`` modules.

These prove the loading contract (local files only, no remote code, safetensors only, CPU providers only) and the tensor
plumbing. They do not prove model quality: real weights are never loaded here.
"""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.conditioning.reference_map import pose, worker


def _module(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class _Tensor:
    def __init__(self, array: np.ndarray) -> None:
        self.array = array

    def __getitem__(self, index):
        return _Tensor(self.array[index])

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


def test_depth_backend_loads_locally_without_remote_code_or_pickles(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeModel:
        def eval(self):
            return self

        def __call__(self, **inputs):
            seen["inputs"] = inputs
            return SimpleNamespace(
                predicted_depth=_Tensor(np.arange(2 * 5 * 7, dtype=np.float32).reshape(2, 5, 7))
            )

    class FakeProcessor:
        @staticmethod
        def from_pretrained(directory, **kwargs):
            seen["processor"] = (directory, kwargs)
            return lambda images, return_tensors: {"pixel_values": "x", "size": images.size}

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(directory, **kwargs):
            seen["model"] = (directory, kwargs)
            return FakeModel()

    class NoGrad:
        def __enter__(self):
            seen["inference_mode"] = True

        def __exit__(self, *exc):
            return False

    torch = _module(
        "torch",
        __version__="9.9",
        set_num_threads=lambda n: seen.setdefault("threads", n),
        inference_mode=NoGrad,
    )
    transformers = _module(
        "transformers",
        __version__="8.8",
        AutoImageProcessor=FakeProcessor,
        AutoModelForDepthEstimation=FakeAutoModel,
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    rgb = np.zeros((64, 96, 3), dtype=np.uint8)
    result = worker.depth_backend({"staged_dir": str(tmp_path)}, rgb, tmp_path)

    assert seen["processor"] == (str(tmp_path), {"local_files_only": True})
    directory, kwargs = seen["model"]
    assert directory == str(tmp_path)
    assert kwargs == {"local_files_only": True, "trust_remote_code": False, "use_safetensors": True}
    assert seen["inference_mode"] and 1 <= seen["threads"] <= worker.MAX_THREADS
    assert seen["inputs"]["size"] == (96, 64)
    assert result["shape"] == [5, 7] and result["runtime"] == {
        "torch": "9.9",
        "transformers": "8.8",
    }
    data = (tmp_path / worker.DEPTH_FILE).read_bytes()
    values = np.frombuffer(data, dtype="<f4")
    assert len(values) == 5 * 7 and values[-1] == 34.0  # the first batch item only


def test_depth_backend_reports_missing_runtimes_precisely(tmp_path, monkeypatch) -> None:
    import importlib.util as util

    real = util.find_spec
    monkeypatch.setattr(
        util,
        "find_spec",
        lambda name, *a, **k: None if name in {"torch", "transformers"} else real(name, *a, **k),
    )
    with pytest.raises(worker.ProviderUnavailable) as caught:
        worker.depth_backend(
            {"staged_dir": str(tmp_path)}, np.zeros((64, 64, 3), dtype=np.uint8), tmp_path
        )
    assert caught.value.reasons == ("runtime_missing:torch", "runtime_missing:transformers")


def test_pose_backend_runs_detector_then_estimator_on_cpu_only(tmp_path, monkeypatch) -> None:
    pytest.importorskip("cv2")
    sessions: list[tuple[str, list[str]]] = []

    class FakeOptions:
        intra_op_num_threads = 0
        log_severity_level = 0

    class FakeSession:
        def __init__(self, path, sess_options=None, providers=None):
            self.name = Path(path).name
            sessions.append((self.name, list(providers or [])))

        def get_inputs(self):
            return [SimpleNamespace(name="images")]

        def run(self, names, feeds):
            tensor = feeds["images"]
            assert tensor.dtype == np.float32 and tensor.flags["C_CONTIGUOUS"]
            if self.name == "yolox_l.onnx":
                assert tensor.shape == (1, 3, 640, 640)
                raw = np.zeros((1, 80 * 80 + 40 * 40 + 20 * 20, 85), dtype=np.float32)
                raw[0, 25 * 80 + 40, 2] = np.log(320 / 8)
                raw[0, 25 * 80 + 40, 3] = np.log(400 / 8)
                raw[0, 25 * 80 + 40, 4] = raw[0, 25 * 80 + 40, 5] = 0.9
                return [raw]
            assert self.name == "dw-ll_ucoco_384.onnx" and tensor.shape == (1, 3, 384, 288)
            simcc_x = np.zeros((1, pose.KEYPOINTS, 576), dtype=np.float32)
            simcc_y = np.zeros((1, pose.KEYPOINTS, 768), dtype=np.float32)
            simcc_x[..., 288] = simcc_y[..., 384] = 0.9  # every keypoint at the middle of the crop
            return [simcc_x, simcc_y]

    ort = _module(
        "onnxruntime", __version__="1.2.3", SessionOptions=FakeOptions, InferenceSession=FakeSession
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    staged = {
        "person_detector": tmp_path / "yolox_l.onnx",
        "pose_estimator": tmp_path / "dw-ll_ucoco_384.onnx",
    }
    rgb = np.full((64, 96, 3), 120, dtype=np.uint8)
    result = worker.pose_backend({"staged": {k: str(v) for k, v in staged.items()}}, rgb, tmp_path)

    assert sessions == [
        ("yolox_l.onnx", ["CPUExecutionProvider"]),
        ("dw-ll_ucoco_384.onnx", ["CPUExecutionProvider"]),
    ]
    people = pose.people_from_payload({"people": result["people"]})
    assert len(people) == 1 and people[0].detection_score == pytest.approx(0.81, abs=1e-3)
    centre = people[0].points[0]
    assert (
        30 < centre[0] < 66 and 15 < centre[1] < 45
    )  # the middle of the detected box, in source pixels
    assert result["runtime"] == {"onnxruntime": "1.2.3"}


def test_pose_backend_reports_missing_onnxruntime(tmp_path, monkeypatch) -> None:
    import importlib.util as util

    real = util.find_spec
    monkeypatch.setattr(
        util,
        "find_spec",
        lambda name, *a, **k: None if name == "onnxruntime" else real(name, *a, **k),
    )
    with pytest.raises(worker.ProviderUnavailable) as caught:
        worker.pose_backend({"staged": {}}, np.zeros((64, 64, 3), dtype=np.uint8), tmp_path)
    assert caught.value.reasons == ("runtime_missing:onnxruntime",)


def test_run_job_writes_content_free_failures(tmp_path) -> None:
    (tmp_path / worker.REQUEST_FILE).write_text(
        json.dumps({"kind": "depth", "width": 2, "height": 2})
    )
    (tmp_path / worker.SOURCE_FILE).write_bytes(b"\0" * 12)

    def exploding(request, rgb, job_dir):
        raise RuntimeError(f"secret detail at {tmp_path}")

    assert worker.run_job(tmp_path, {"depth": exploding}) == 1
    document = json.loads((tmp_path / worker.RESULT_FILE).read_text())
    assert document == {"ok": False, "code": "inference_failed", "reasons": ["RuntimeError"]}
    assert str(tmp_path) not in json.dumps(document)
    # a source of the wrong size is refused before the backend runs
    (tmp_path / worker.SOURCE_FILE).write_bytes(b"\0" * 5)
    assert worker.run_job(tmp_path, {"depth": exploding}) == 2


def test_importing_the_worker_has_no_import_time_side_effects() -> None:
    assert (
        "torch" not in sys.modules or sys.modules["torch"] is not None
    )  # no assumption about the host
    assert callable(worker.main) and worker.main(["worker.py"]) == 64
