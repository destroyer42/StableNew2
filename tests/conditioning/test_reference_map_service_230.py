"""PR-IMG-CNET-230: preparation service, contained worker protocol, auxiliary identity and library publication.

Fake providers and an in-process stand-in for the worker child; a temporary WebUI root with tiny synthetic auxiliary files.
No GPU, Forge, socket, real weights or display.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from src.conditioning.openpose import normalize_asset_identity
from src.conditioning.openpose_catalog import refresh_listing
from src.conditioning.reference_map import auxiliary, library, pose, providers, worker
from src.conditioning.reference_map.contracts import (
    MapRequest,
    ProviderUnavailable,
    ReferenceMapError,
)
from src.conditioning.reference_map.service import ReferenceMapService
from src.utils.managed_process import ProcessOutcome
from tests.assets.readiness_fixtures_130 import (
    aux_dir,
    file_spec,
    make_catalog,
    make_registry,
    resource,
    sha256_of,
    variant,
    write_safetensors,
    write_text,
)
from tests.conditioning.reference_map_fixtures_230 import PureCannyProvider, pure_service

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------------------------- fixtures


def _png(width: int = 96, height: int = 64) -> bytes:
    array = np.zeros((height, width, 3), dtype=np.uint8)
    array[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    array[20:40, 30:60] = (250, 250, 20)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "pictures" / "source.png"
    path.parent.mkdir()
    path.write_bytes(_png())
    return path


def _depth_files(registry: Any) -> dict[str, Path]:
    base = aux_dir(registry) / "depth-anything-v2-small-hf"
    return {
        "weights": write_safetensors(base / "model.safetensors"),
        "model_config": write_text(base / "config.json", '{"model_type": "depth_anything"}'),
        "image_processor_config": write_text(base / "preprocessor_config.json", "{}"),
    }


def _depth_catalog(files: dict[str, Path]):
    return make_catalog(
        resource(
            "depth-anything-v2-small-hf",
            [
                file_spec("weights", [variant("model.safetensors", sha256_of(files["weights"]))]),
                file_spec("model_config", [variant("config.json", None)]),
                file_spec("image_processor_config", [variant("preprocessor_config.json", None)]),
            ],
        )
    )


def _pose_files(registry: Any) -> dict[str, Path]:
    base = aux_dir(registry) / "dwpose-onnx"
    base.mkdir(parents=True, exist_ok=True)
    (base / "dw-ll_ucoco_384.onnx").write_bytes(b"estimator-bytes")
    (base / "yolox_l.onnx").write_bytes(b"detector-bytes")
    return {
        "pose_estimator": base / "dw-ll_ucoco_384.onnx",
        "person_detector": base / "yolox_l.onnx",
    }


def _pose_catalog(files: dict[str, Path]):
    return make_catalog(
        resource(
            "dwpose-onnx",
            [
                file_spec(
                    "pose_estimator",
                    [variant("dw-ll_ucoco_384.onnx", sha256_of(files["pose_estimator"]))],
                ),
                file_spec(
                    "person_detector",
                    [variant("yolox_l.onnx", sha256_of(files["person_detector"]))],
                ),
            ],
        )
    )


class InProcessRunner:
    """Runs the worker's real ``run_job`` in this process with injected fake backends (no subprocess, no model)."""

    def __init__(self, backends: dict[str, Any] | None = None, **outcome: Any) -> None:
        self.backends = backends or {}
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, command, *, timeout_seconds, max_stdout_bytes, cancel, env
    ) -> ProcessOutcome:
        self.calls.append(
            {
                "command": list(command),
                "timeout": timeout_seconds,
                "cap": max_stdout_bytes,
                "env": dict(env),
            }
        )
        if self.outcome:
            return ProcessOutcome(
                returncode=self.outcome.get("returncode"),
                **{k: v for k, v in self.outcome.items() if k != "returncode"},
            )
        job = Path(command[-1])
        return ProcessOutcome(returncode=worker.run_job(job, self.backends), contained=True)


def _fake_depth(request, rgb, job_dir):
    staged = Path(request["staged_dir"])
    assert sorted(item.name for item in staged.iterdir()) == [
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
    ]
    prediction = np.linspace(0.0, 1.0, 7 * 9, dtype="<f4").reshape(7, 9)
    (job_dir / worker.DEPTH_FILE).write_bytes(prediction.tobytes())
    return {"shape": [7, 9], "runtime": {"torch": "fake", "transformers": "fake"}}


def _fake_pose(request, rgb, job_dir):
    staged = {role: Path(path) for role, path in request["staged"].items()}
    assert staged["pose_estimator"].read_bytes() == b"estimator-bytes"
    points = np.zeros((pose.KEYPOINTS, 2))
    scores = np.zeros(pose.KEYPOINTS)
    for index, point in {
        0: (40, 8), 5: (30, 20), 6: (50, 20), 7: (25, 35), 8: (55, 35),
        9: (22, 50), 10: (58, 50), 11: (33, 45), 12: (47, 45),
    }.items():  # fmt: skip
        points[index], scores[index] = point, 0.9
    payload = pose.people_to_payload(
        [pose.PosePerson(points, scores, 0.95)], rgb.shape[1], rgb.shape[0]
    )
    return {"people": payload["people"], "runtime": {"onnxruntime": "fake"}}


def _service(
    registry, runner, *, catalog=None, tmp_path: Path | None = None
) -> ReferenceMapService:
    chosen = providers.default_providers()
    if catalog is not None:
        chosen["depth"] = _CatalogProvider(providers.DepthProvider(), catalog)
        chosen["openpose"] = _CatalogProvider(providers.PoseProvider(), catalog)
    return ReferenceMapService(
        lambda: registry,
        providers=chosen,
        runner=runner,
        temp_root=str(tmp_path) if tmp_path else None,
    )


class _CatalogProvider:
    """A real auxiliary provider that skips only the host-runtime probe and uses a test catalog."""

    def __init__(self, inner: Any, catalog: Any) -> None:
        self.inner, self.catalog, self.modality = inner, catalog, inner.modality
        inner.availability = (
            lambda: ()
        )  # the worker is faked, so the host's real runtimes are irrelevant

    def availability(self) -> tuple[str, ...]:
        return ()

    def produce(self, source, context):
        original = auxiliary.verify_resource

        def with_catalog(registry, modality, *, catalog=None, cancelled=None):
            return original(registry, modality, catalog=self.catalog, cancelled=cancelled)

        auxiliary.verify_resource, previous = with_catalog, auxiliary.verify_resource
        try:
            return self.inner.produce(source, context)
        finally:
            auxiliary.verify_resource = previous


# ---------------------------------------------------------------------------------------------- auxiliary identity


def test_verified_resource_comes_from_catalog_and_registry_and_flags_unpinned_configs(
    tmp_path,
) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    verified = auxiliary.verify_resource(registry, "depth", catalog=_depth_catalog(files))
    assert verified.resource_id == "depth-anything-v2-small-hf"
    by_role = verified.by_role()
    assert by_role["weights"].pinned and by_role["weights"].sha256 == sha256_of(files["weights"])
    assert by_role["weights"].relative == "depth-anything-v2-small-hf/model.safetensors"
    assert not by_role["model_config"].pinned
    assert verified.warnings == ("auxiliary_config_unpinned",)


def test_wrong_hash_auxiliary_file_is_refused_before_any_inference(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    catalog = _depth_catalog(files)
    files["weights"].write_bytes(files["weights"].read_bytes() + b"tampered")
    runner = InProcessRunner({"depth": _fake_depth})
    with pytest.raises(ProviderUnavailable) as caught:
        _service(registry, runner, catalog=catalog).prepare(MapRequest(source, "depth"))
    assert "hash_mismatch:weights" in caught.value.reasons
    assert runner.calls == []  # the child was never started


def test_missing_auxiliary_file_and_missing_webui_root_are_actionable(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    catalog = _depth_catalog(files)
    files["model_config"].unlink()
    with pytest.raises(ProviderUnavailable) as missing:
        auxiliary.verify_resource(registry, "depth", catalog=catalog)
    assert missing.value.reasons == ("resource_missing:model_config",)
    assert "Model Resources" in missing.value.message

    class NoRoot:
        webui_root = None

    with pytest.raises(ProviderUnavailable) as none:
        auxiliary.verify_resource(NoRoot(), "depth")
    assert none.value.reasons == ("no_webui_root",)


def test_staging_copies_only_verified_files_and_detects_a_swap_after_verification(tmp_path) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    (files["weights"].parent / "pytorch_model.bin").write_bytes(b"operator pickle")
    verified = auxiliary.verify_resource(registry, "depth", catalog=_depth_catalog(files))
    staged = auxiliary.stage_resource(verified, registry.webui_root, tmp_path / "stage")
    assert sorted(p.name for p in (tmp_path / "stage").iterdir()) == [
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
    ]
    assert hashlib.sha256(staged["weights"].read_bytes()).hexdigest() == sha256_of(files["weights"])
    files["weights"].write_bytes(
        files["weights"].read_bytes() + b"x"
    )  # swapped between check and use
    with pytest.raises(ProviderUnavailable) as caught:
        auxiliary.stage_resource(verified, registry.webui_root, tmp_path / "stage2")
    assert caught.value.reasons == ("hash_mismatch:weights",)
    assert not (tmp_path / "stage2").exists()


def test_staging_refuses_a_path_that_escapes_the_auxiliary_folder(tmp_path) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    outside = tmp_path / "webui" / "models" / "outside.safetensors"
    write_safetensors(outside)
    resource_ = auxiliary.VerifiedResource(
        "depth-anything-v2-small-hf",
        (
            auxiliary.AuxiliaryFileIdentity(
                "weights",
                "../outside.safetensors",
                sha256_of(outside),
                outside.stat().st_size,
                True,
            ),
        ),
    )
    with pytest.raises(ProviderUnavailable) as caught:
        auxiliary.stage_resource(resource_, registry.webui_root, tmp_path / "stage")
    assert caught.value.reasons == ("escape:weights",)
    assert files["weights"].exists()


# ---------------------------------------------------------------------------------------------- providers / worker protocol


def test_depth_through_the_worker_protocol_records_identity_and_cleans_up(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    runner = InProcessRunner({"depth": _fake_depth})
    prepared = _service(registry, runner, catalog=_depth_catalog(files), tmp_path=jobs).prepare(
        MapRequest(source, "depth")
    )
    assert (prepared.width, prepared.height) == (96, 64)
    assert prepared.method.method_id == "depth-anything-v2-small-hf"
    assert prepared.auxiliary_resource == "depth-anything-v2-small-hf"
    assert {item.role for item in prepared.auxiliary} == {
        "weights",
        "model_config",
        "image_processor_config",
    }
    assert prepared.runtime == {"torch": "fake", "transformers": "fake"}
    assert prepared.warnings == ("auxiliary_config_unpinned",)
    assert list(jobs.iterdir()) == []  # the private job directory is gone
    call = runner.calls[0]
    assert call["command"][1:3] == ["-I", str(providers.WORKER_PATH)]
    env = call["env"]
    assert env["CUDA_VISIBLE_DEVICES"] == "-1" and env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"


def test_worker_environment_is_an_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    env = providers.worker_environment()
    assert "HF_TOKEN" not in env and "OPENAI_API_KEY" not in env
    assert env["CUDA_VISIBLE_DEVICES"] == "-1"


def test_openpose_through_the_worker_protocol(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _pose_files(registry)
    runner = InProcessRunner({"pose": _fake_pose})
    prepared = _service(registry, runner, catalog=_pose_catalog(files)).prepare(
        MapRequest(source, "openpose")
    )
    assert (prepared.width, prepared.height) == (96, 64)
    assert prepared.method.method_id == "dwpose-onnx"
    assert {item.role for item in prepared.auxiliary} == {"pose_estimator", "person_detector"}
    assert "pose_no_hands" in prepared.warnings and "pose_no_face" in prepared.warnings
    assert all(item.pinned for item in prepared.auxiliary)


def test_openpose_without_people_returns_no_map(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _pose_files(registry)

    def nobody(request, rgb, job_dir):
        return {"people": [], "runtime": {}}

    with pytest.raises(ReferenceMapError) as caught:
        _service(registry, InProcessRunner({"pose": nobody}), catalog=_pose_catalog(files)).prepare(
            MapRequest(source, "openpose")
        )
    assert caught.value.code == "no_people"


def test_unavailable_provider_is_reported_and_never_falls_back_to_canny(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    produced: list[str] = []

    class Down:
        modality = "openpose"

        def availability(self) -> tuple[str, ...]:
            return ("runtime_missing:onnxruntime",)

        def produce(self, source, context):
            produced.append("openpose")
            raise ProviderUnavailable("down", reasons=("runtime_missing:onnxruntime",))

    class Spy(providers.CannyProvider):
        def produce(self, source, context):
            produced.append("canny")
            return super().produce(source, context)

    service = ReferenceMapService(lambda: registry, providers={"openpose": Down(), "canny": Spy()})
    assert service.availability("openpose") == ("runtime_missing:onnxruntime",)
    with pytest.raises(ProviderUnavailable) as caught:
        service.prepare(MapRequest(source, "openpose"))
    assert caught.value.code == "provider_unavailable"
    assert caught.value.reasons == ("runtime_missing:onnxruntime",)
    assert produced == ["openpose"]  # nothing else ran


def test_real_runtime_probes_name_exact_missing_modules(monkeypatch) -> None:
    import importlib.machinery as machinery
    import importlib.util as util

    # Only onnxruntime is absent: OpenCV is treated as present so the answer does not depend on the host (hosted runners lack it).
    monkeypatch.setattr(
        util,
        "find_spec",
        lambda name, *a, **k: None if name == "onnxruntime" else machinery.ModuleSpec(name, None),
    )
    assert providers.PoseProvider().availability() == ("runtime_missing:onnxruntime",)
    monkeypatch.setattr(util, "find_spec", lambda name, *a, **k: None)
    assert providers.PoseProvider().availability() == (
        "runtime_missing:onnxruntime",
        "runtime_missing:cv2",
    )


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ({"returncode": None, "cancelled": True}, "cancelled"),
        ({"returncode": None, "timed_out": True}, "timeout"),
        ({"returncode": None, "launch_error": "boom"}, "inference_failed"),
        ({"returncode": 0}, "inference_failed"),  # exit 0 but no result.json
    ],
)
def test_worker_outcomes_map_to_stable_codes(tmp_path, source, outcome, code) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    with pytest.raises(ReferenceMapError) as caught:
        _service(registry, InProcessRunner(**outcome), catalog=_depth_catalog(files)).prepare(
            MapRequest(source, "depth")
        )
    assert caught.value.code == code


def test_worker_runtime_missing_is_reported_as_provider_unavailable(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)

    def missing(request, rgb, job_dir):
        raise ProviderUnavailable("x", reasons=("runtime_missing:torch",))

    with pytest.raises(ProviderUnavailable) as caught:
        _service(
            registry, InProcessRunner({"depth": missing}), catalog=_depth_catalog(files)
        ).prepare(MapRequest(source, "depth"))
    assert caught.value.reasons == ("runtime_missing:torch",)


@pytest.mark.parametrize("damage", ["shape", "truncated", "nan", "flat"])
def test_depth_results_off_contract_are_refused(tmp_path, source, damage) -> None:
    registry = make_registry(tmp_path)
    files = _depth_files(registry)

    def damaged(request, rgb, job_dir):
        values = np.linspace(0, 1, 12, dtype="<f4")
        if damage == "nan":
            values[3] = np.nan
        if damage == "flat":
            values[:] = 2.0
        data = values.tobytes()[:-4] if damage == "truncated" else values.tobytes()
        (job_dir / worker.DEPTH_FILE).write_bytes(data)
        return {"shape": [0, 12] if damage == "shape" else [3, 4], "runtime": {}}

    with pytest.raises(ReferenceMapError) as caught:
        _service(
            registry, InProcessRunner({"depth": damaged}), catalog=_depth_catalog(files)
        ).prepare(MapRequest(source, "depth"))
    assert caught.value.code in {"inference_failed", "depth_non_finite", "depth_flat"}


def test_cancel_during_preparation_leaves_nothing_in_the_library(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    service = ReferenceMapService(lambda: registry)
    with pytest.raises(ReferenceMapError) as caught:
        service.prepare(MapRequest(source, "canny"), cancel=lambda: True)
    assert caught.value.code == "cancelled"
    assert not (tmp_path / "webui" / "models" / "OpenPose").exists()


def test_service_requires_a_supported_modality_and_stays_off_the_wire(tmp_path, source) -> None:
    with pytest.raises(ReferenceMapError):
        MapRequest(source, "segmentation")
    registry = make_registry(tmp_path)
    assert ReferenceMapService(lambda: registry).availability("segmentation") == (
        "unsupported_modality",
    )


def test_the_real_worker_script_bootstraps_in_isolated_mode(tmp_path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    (job / "request.json").write_text(json.dumps({"kind": "nope", "width": 1, "height": 1}))
    (job / "source.rgb").write_bytes(b"\0\0\0")
    # This test is about the script bootstrapping in isolated mode. The memory ceiling that ``bounded_runner`` adds needs a
    # container that can enforce it (a Windows job object, or a Linux cgroup the host has delegated); where there is none the
    # runner correctly starts nothing (see test_managed_process_memory_limit_330), so only Windows exercises the capped path.
    runner = providers.bounded_runner if os.name == "nt" else providers.run_bounded
    outcome = runner(
        [sys.executable, "-I", str(providers.WORKER_PATH), str(job)],
        timeout_seconds=60,
        max_stdout_bytes=4096,
        cancel=None,
        env=providers.worker_environment(),
    )
    assert outcome.returncode == 2 and not outcome.timed_out
    document = json.loads((job / "result.json").read_text())
    assert document["ok"] is False and document["code"] == "inference_failed"


# ---------------------------------------------------------------------------------------------- library publication


def _prepared(registry, source, modality: str = "canny"):
    return pure_service(registry).prepare(MapRequest(source, modality))


def test_save_publishes_an_atomic_library_map_with_sanitized_deterministic_provenance(
    tmp_path, source
) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    saved = library.save_map(prepared, registry.webui_root)
    assert saved.identity == f"created/canny-{prepared.sha256[:16]}.png"
    assert normalize_asset_identity(saved.identity) == saved.identity
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    assert (folder / f"canny-{prepared.sha256[:16]}.png").read_bytes() == prepared.png
    assert sorted(p.suffix for p in folder.iterdir()) == [
        ".json",
        ".png",
    ]  # no temporary file remains
    sidecar = (folder / f"canny-{prepared.sha256[:16]}.stablenew-map.json").read_bytes()
    text = sidecar.decode("ascii")
    for forbidden in (str(tmp_path), "pictures", "webui", "source.png", os.sep + "Users"):
        assert forbidden not in text
    assert json.loads(text)["source"]["file_sha256"] == prepared.source.file_sha256
    assert sidecar == library.provenance_bytes(prepared)  # deterministic
    # the same map in a different temp root yields byte-identical provenance
    other = tmp_path / "other"
    other.mkdir()
    again = _prepared(make_registry(other), source)
    assert library.provenance_bytes(again) == sidecar
    # and the registry lists it as an ordinary library image
    listing = refresh_listing(registry)
    assert saved.identity in listing.identities


def test_saving_the_same_map_twice_reuses_it(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    first = library.save_map(prepared, registry.webui_root)
    second = library.save_map(prepared, registry.webui_root)
    assert (first.identity, second.reused) == (second.identity, True)


def test_an_operator_file_with_the_same_name_is_never_overwritten(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    folder.mkdir(parents=True)
    operator = folder / f"canny-{prepared.sha256[:16]}.png"
    operator.write_bytes(b"operator's own file")
    saved = library.save_map(prepared, registry.webui_root)
    assert saved.identity.endswith("-2.png")
    assert operator.read_bytes() == b"operator's own file"
    assert (folder / Path(saved.identity).name).read_bytes() == prepared.png


def test_losing_a_race_for_the_name_never_replaces_the_winner(
    tmp_path, source, monkeypatch
) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    winner = folder / f"canny-{prepared.sha256[:16]}.png"
    real_link = os.link
    calls = {"n": 0}

    def racing_link(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            Path(dst).write_bytes(b"won the race")
            raise FileExistsError(dst)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    saved = library.save_map(prepared, registry.webui_root)
    assert winner.read_bytes() == b"won the race"
    assert saved.identity.endswith("-2.png")


def test_a_write_exception_leaves_nothing_behind(tmp_path, source, monkeypatch) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)

    def broken(fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(ReferenceMapError) as caught:
        library.save_map(prepared, registry.webui_root)
    assert caught.value.code == "library_write_failed"
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    assert list(folder.iterdir()) == []


def test_publication_failure_leaves_no_image_or_partial_file(tmp_path, source, monkeypatch) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)

    def refuse(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "link", refuse)
    monkeypatch.setattr(os, "rename", refuse)
    with pytest.raises(ReferenceMapError) as caught:
        library.save_map(prepared, registry.webui_root)
    assert caught.value.code == "library_write_failed"
    assert list((tmp_path / "webui" / "models" / "OpenPose" / "created").iterdir()) == []


def test_a_sidecar_failure_keeps_the_image_and_says_so(tmp_path, source, monkeypatch) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    saved = library.save_map(prepared, registry.webui_root)
    assert saved.provenance_saved is False
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    assert [p.suffix for p in folder.iterdir()] == [".png"]


def test_source_drift_refuses_save_and_writes_nothing(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    source.write_bytes(_png(96, 65))
    with pytest.raises(ReferenceMapError) as caught:
        library.save_map(prepared, registry.webui_root)
    assert caught.value.code == "source_changed"
    assert not (tmp_path / "webui" / "models" / "OpenPose").exists()


def test_save_requires_a_configured_library_and_a_prepared_source(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    with pytest.raises(ReferenceMapError) as none:
        library.save_map(prepared, None)
    assert none.value.code == "library_no_library"
    from dataclasses import replace

    with pytest.raises(ReferenceMapError) as unprepared:
        library.save_map(replace(prepared, source_path=None), registry.webui_root)
    assert unprepared.value.code == "not_prepared"


@pytest.mark.parametrize("damage", ["junk", "tiny", "hash"])
def test_a_bad_prepared_image_is_refused_before_publication(tmp_path, source, damage) -> None:
    from dataclasses import replace

    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    if damage == "junk":
        bad = replace(prepared, png=b"nope", sha256=hashlib.sha256(b"nope").hexdigest())
    elif damage == "tiny":
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, format="PNG")
        bad = replace(
            prepared, png=buffer.getvalue(), sha256=hashlib.sha256(buffer.getvalue()).hexdigest()
        )
    else:
        bad = replace(prepared, sha256="0" * 64)
    with pytest.raises(ReferenceMapError) as caught:
        library.save_map(bad, registry.webui_root)
    assert caught.value.code.startswith("library_")
    assert not (tmp_path / "webui" / "models" / "OpenPose" / "created").exists()


def test_the_created_folder_must_be_a_real_directory_inside_the_library(
    tmp_path, source, monkeypatch
) -> None:
    registry = make_registry(tmp_path)
    prepared = _prepared(registry, source)
    root = tmp_path / "webui" / "models" / "OpenPose"
    (root / "created").mkdir(parents=True)
    monkeypatch.setattr(
        library, "is_link", lambda path: path.name == "created"
    )  # a symlink or junction
    with pytest.raises(ReferenceMapError) as link:
        library.save_map(prepared, registry.webui_root)
    assert link.value.code == "library_escape"
    monkeypatch.undo()
    real_resolve = Path.resolve

    def redirected(self, *args, **kwargs):
        resolved = real_resolve(self, *args, **kwargs)
        return (
            real_resolve(tmp_path / "elsewhere", strict=False)
            if self.name == "created"
            else resolved
        )

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ReferenceMapError) as escaped:
        library.contained_folder(root)
    assert escaped.value.code == "library_escape"


def test_junction_detection_uses_the_platform_primitive(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "d"
    folder.mkdir()
    assert library.is_link(folder) is False
    monkeypatch.setattr(os.path, "isjunction", lambda path: True, raising=False)
    assert library.is_link(folder) is True


def test_a_corrupt_sidecar_does_not_hide_unrelated_maps(tmp_path, source) -> None:
    registry = make_registry(tmp_path)
    first = library.save_map(_prepared(registry, source), registry.webui_root)
    second_source = tmp_path / "pictures" / "other.png"
    second_source.write_bytes(_png(80, 80))
    second = library.save_map(_prepared(registry, second_source), registry.webui_root)
    folder = tmp_path / "webui" / "models" / "OpenPose" / "created"
    sidecar = folder / (Path(first.identity).stem + library.SIDECAR_SUFFIX)
    sidecar.write_bytes(b"{ not json")
    assert library.read_provenance(registry.webui_root, first.identity) is None
    assert library.read_provenance(registry.webui_root, second.identity)["modality"] == "canny"
    assert {first.identity, second.identity} <= refresh_listing(registry).identities
    sidecar.write_bytes(b" " * (library.MAX_PROVENANCE_BYTES + 10))
    assert library.read_provenance(registry.webui_root, first.identity) is None
    sidecar.write_text(json.dumps({"contract": "other/1"}))
    assert library.read_provenance(registry.webui_root, first.identity) is None
    assert library.read_provenance(None, first.identity) is None
    assert library.read_provenance(registry.webui_root, "../escape.png") is None


# ---------------------------------------------------------------------------------------------- authority boundaries


def test_preparation_and_save_never_submit_run_or_touch_the_network(
    tmp_path, source, monkeypatch
) -> None:
    import socket

    import requests

    from src.controller.job_service import JobService
    from src.pipeline.pipeline_runner import PipelineRunner

    def forbidden(*args, **kwargs):
        raise AssertionError("reference-map preparation reached a forbidden authority")

    monkeypatch.setattr(JobService, "submit_njrs", forbidden)
    monkeypatch.setattr(PipelineRunner, "run_njr", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    registry = make_registry(tmp_path)
    files = _depth_files(registry)
    service = _service(
        registry, InProcessRunner({"depth": _fake_depth}), catalog=_depth_catalog(files)
    )
    service._providers["canny"] = (
        PureCannyProvider()
    )  # the real Canny needs OpenCV, absent on hosted runners
    for modality in ("canny", "depth"):
        service.save(service.prepare(MapRequest(source, modality)))


def test_reference_map_modules_do_not_import_execution_authorities() -> None:
    forbidden = (
        "src.controller",
        "src.queue",
        "src.api",
        "src.pipeline",
        "src.image_backends",
        "src.gui",
        "src.history",
    )
    for path in sorted((REPO / "src" / "conditioning" / "reference_map").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_importing_the_service_loads_no_model_runtime() -> None:
    code = (
        "import sys; import src.conditioning.reference_map.service as s; "
        "print(sorted(m for m in ('torch','transformers','onnxruntime','cv2') if m in sys.modules))"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert result.stdout.strip() == "[]"
