"""PR-IMG-120: the contained child's job contract, run in-process with hermetic fakes (no torch, no GPU, no model)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from src.image_backends.diffusers_ideogram4_profile import IDEOGRAM4_PROFILE_V1 as P
from src.image_backends.diffusers_ideogram4_worker import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    PROGRESS_FILE,
    REQUEST_FILE,
    REQUEST_SCHEMA,
    RESULT_FILE,
    run_job,
)
from src.image_backends.ideogram4_caption import resolve_caption
from tests.helpers.ideogram4_fakes import FakeCuda, FakeTorch, FakeWorld, fake_loader

MIB = 1024 * 1024


def request(**changes) -> dict:
    caption = resolve_caption("A teapot on a table.")
    preset = P.preset_for_steps(changes.pop("steps", 12))
    document = {
        "schema": REQUEST_SCHEMA,
        "repo_id": P.repo_id,
        "revision": P.revision,
        "caption_json": caption.caption_json,
        "caption_sha256": caption.sha256,
        "width": 512,
        "height": 512,
        "steps": preset.steps,
        "guidance_schedule": list(preset.diffusers_guidance()),
        "mu": preset.mu,
        "std": preset.std,
        "seeds": [11, 12],
    }
    document.update(changes)
    return document


def run(
    tmp_path: Path, document: dict, world: FakeWorld | None = None, cuda: FakeCuda | None = None
) -> tuple[int, dict]:
    (tmp_path / REQUEST_FILE).write_text(json.dumps(document), encoding="utf-8")
    code = run_job(tmp_path, loader=fake_loader(world, FakeTorch(cuda)), missing_runtime=lambda: [])
    return code, json.loads((tmp_path / RESULT_FILE).read_text(encoding="utf-8"))


def test_successful_job_writes_images_result_and_progress(tmp_path: Path) -> None:
    code, result = run(tmp_path, request())
    assert code == EXIT_OK and result["ok"] is True and result["code"] == "ok"
    assert [entry["file"] for entry in result["images"]] == ["image_00.png", "image_01.png"]
    for entry, seed in zip(result["images"], (11, 12), strict=True):
        path = tmp_path / entry["file"]
        assert entry["seed"] == seed and (entry["width"], entry["height"]) == (512, 512)
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            assert image.getpixel((0, 0))[0] == seed
    assert result["token_count"] == 287 and result["max_resident_transformers"] == 1
    assert result["allocator_cap"]["cap_mib"] == 11_200 and result["swaps"] == 2 * 2 * 12
    assert set(result["timings"]) == {"load_s", "text_encode_s", "generate_s"}
    assert result["runtime"]["python"] == sys.version.split()[0]
    progress = json.loads((tmp_path / PROGRESS_FILE).read_text(encoding="utf-8"))
    assert progress == {"phase": "denoising", "image": 2, "images": 2, "step": 12, "steps": 12}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"schema": "other"}, "request_invalid"),
        ({"revision": "main"}, "request_invalid"),
        ({"repo_id": "someone/else"}, "request_invalid"),
        ({"caption_json": '{"high_level_description": "x"}'}, "caption_invalid"),
        ({"caption_sha256": "0" * 64}, "request_invalid"),
        ({"width": 1536, "height": 1536}, "request_invalid"),
        ({"guidance_schedule": [7.0] * 12}, "request_invalid"),
        ({"mu": 0.0}, "request_invalid"),
        ({"seeds": []}, "request_invalid"),
        ({"seeds": [1, 2, 3, 4, 5]}, "request_invalid"),
        ({"seeds": [-1]}, "request_invalid"),
        ({"steps": 13}, "request_invalid"),
    ],
)
def test_the_child_revalidates_the_request_and_loads_nothing(
    tmp_path: Path, change: dict, code: str
) -> None:
    world = FakeWorld()
    document = request()
    document.update(change)
    exit_code, result = run(tmp_path, document, world=world)
    assert exit_code == EXIT_REFUSED and result == {
        "ok": False,
        "code": code,
        "message": result["message"],
    }
    assert world.loads == []


def test_missing_request_and_missing_runtime_are_typed_refusals(tmp_path: Path) -> None:
    assert run_job(tmp_path, loader=fake_loader(), missing_runtime=lambda: []) == EXIT_REFUSED
    assert (
        json.loads((tmp_path / RESULT_FILE).read_text(encoding="utf-8"))["code"]
        == "request_invalid"
    )
    (tmp_path / REQUEST_FILE).write_text(json.dumps(request()), encoding="utf-8")
    assert (
        run_job(tmp_path, loader=fake_loader(), missing_runtime=lambda: ["bitsandbytes"])
        == EXIT_REFUSED
    )
    result = json.loads((tmp_path / RESULT_FILE).read_text(encoding="utf-8"))
    assert result["code"] == "runtime_missing" and "bitsandbytes" in result["message"]


def test_residency_refusals_oom_and_failures_have_distinct_codes(tmp_path: Path) -> None:
    code, result = run(tmp_path, request(), cuda=FakeCuda(free_bytes=10_000 * MIB))
    assert (code, result["code"]) == (EXIT_REFUSED, "vram_insufficient")
    code, result = run(tmp_path, request(), world=FakeWorld(token_count=4000))
    assert (code, result["code"]) == (EXIT_REFUSED, "caption_too_long")
    code, result = run(tmp_path, request(), world=FakeWorld(oom_on_step=2))
    assert (code, result["code"]) == (
        EXIT_FAILED,
        "out_of_memory",
    ) and "torch_reserved_peak_mib" in result["memory"]
    code, result = run(tmp_path, request(), world=FakeWorld(fail_on_step=1))
    assert (code, result["code"]) == (EXIT_FAILED, "failed") and "fake failure" in result["message"]


def test_the_worker_module_imports_nothing_heavy() -> None:
    probe = (
        "import sys; import src.image_backends.diffusers_ideogram4_worker, src.image_backends.diffusers_backend; "
        "heavy = [m for m in ('torch', 'diffusers', 'transformers', 'bitsandbytes') if m in sys.modules]; "
        "print(','.join(heavy))"
    )
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert completed.stdout.strip() == ""
