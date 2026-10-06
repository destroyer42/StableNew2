"""PR-IMG-117 acceptance driver: fakes only (no process, GPU or WebUI). The physical acceptance is separate.

The driver is a thin observer: it freezes three intents through the production compiler, selects profile v2 for its
own process only, and submits through the production queue stack. It never owns a runner, queue or compiler.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import src.image_backends.forge_klein_profile as profile_module
import tools.acceptance.img_117_klein_lora_acceptance as driver
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.image_backends.forge_webui_backend import ForgeWebUIImageBackend
from tools.acceptance.img_forge_100_acceptance import EXIT_DRY


@pytest.fixture(autouse=True)
def _forge_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.image_backends.image_backend_types.configured_image_backend_id", lambda: "forge_webui")
    monkeypatch.setattr(driver, "_fault_events", lambda _start: [])


def _args(tmp_path: Path, tag: str = "0", **extra) -> argparse.Namespace:
    return argparse.Namespace(
        reports_dir=tmp_path / f"rep-{tag}", approved_intent_sha256=extra.pop("approved", ""), timeout_seconds=60.0,
        dry=True, forge_data_dir=tmp_path / "data", lora_file=None, endpoint="http://127.0.0.1:7871", **extra,
    )


def _frozen(tmp_path: Path) -> dict:
    with driver.forge_selected_in_memory(), driver.klein_v2_selected_in_memory():
        return {
            spec["label"]: driver.freeze_job(spec, job_id=f"j-{spec['label']}", output_dir=tmp_path / "out")
            for spec in driver.job_specs()
        }


def test_three_jobs_share_prompt_seed_and_geometry_and_differ_only_by_the_lora_tag(tmp_path: Path) -> None:
    njrs = _frozen(tmp_path)

    assert list(njrs) == ["baseline", "lora_a", "lora_b"]
    base = njrs["baseline"]
    for label, weight in (("lora_a", driver.WEIGHT_A), ("lora_b", driver.WEIGHT_B)):
        job = njrs[label]
        assert job.positive_prompt == f"{base.positive_prompt} <lora:{driver.LORA_NAME}:{weight:g}>"
        assert (job.seed, job.width, job.height, job.sampler_name, job.scheduler, job.steps, job.cfg_scale) == (
            base.seed, base.width, base.height, base.sampler_name, base.scheduler, base.steps, base.cfg_scale
        )
    assert base.seed == driver.SEED_A and (base.width, base.height) == (768, 1024)
    assert "<lora:" not in base.positive_prompt and all(n.negative_prompt == "" for n in njrs.values())
    assert {n.backend_options["image"]["model_profile"]["version"] for n in njrs.values()} == {2}


def test_the_frozen_lora_jobs_pass_production_admission_with_a_compatible_adapter(tmp_path: Path) -> None:
    backend = ForgeWebUIImageBackend(
        lora_resolver=lambda name: KleinLoraDecision(
            name, KleinLoraStatus.COMPATIBLE, "ok", "embedded_metadata:ss_base_model_version", "flux2_klein_4b", "ab" * 32
        )
    )
    for njr in _frozen(tmp_path).values():
        backend.validate_njr_intent(njr, ["txt2img"])


def test_profile_v2_selection_is_scoped_to_the_driver_process_and_is_restored() -> None:
    before = profile_module.latest_klein_profile()
    with driver.klein_v2_selected_in_memory():
        assert profile_module.latest_klein_profile() is profile_module.KLEIN_PROFILE_V2
    assert profile_module.latest_klein_profile() is before


def test_dry_run_freezes_and_prints_the_digest_without_any_runtime(tmp_path: Path, capsys) -> None:
    args = _args(tmp_path)

    assert driver.run(args, driver.InjectedRuntime()) == EXIT_DRY

    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    intent = json.loads((Path(args.reports_dir) / "intent.json").read_text(encoding="utf-8"))
    assert printed["dry"] is True and printed["intent_sha256"] == intent["intent_sha256"]
    assert set(intent["jobs"]) == set() and set(intent["njrs"]) == {"baseline", "lora_a", "lora_b"}
    # the digest is deterministic for fixed inputs apart from the stamped job ids
    again = _args(tmp_path, "1")
    driver.run(again, driver.InjectedRuntime())
    assert len(json.loads((Path(again.reports_dir) / "intent.json").read_text(encoding="utf-8"))["intent_sha256"]) == 64


def test_physical_execution_requires_the_approved_digest(tmp_path: Path) -> None:
    args = _args(tmp_path, approved="not-the-digest")
    args.dry = False

    with pytest.raises(PermissionError, match="approved intent digest"):
        driver.run(args, driver.InjectedRuntime())


def test_the_driver_owns_no_runner_queue_or_compiler() -> None:
    source = Path(driver.__file__).read_text(encoding="utf-8")

    for owned in ("class PipelineRunner", "class JobService", "class JobQueue", "def compile_", "subprocess", "taskkill"):
        assert owned not in source
    assert "build_stack" in source and "build_cli_njr" in source  # the production stack and compiler
    assert "monkeypatch" not in source  # the driver patches nothing in the production backend
