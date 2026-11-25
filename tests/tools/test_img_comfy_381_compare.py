"""IMG-COMFY-381 PR B: the Forge-vs-ComfyUI comparison harness, proven with fake backends only.

The real JobService, SQLite repository, worker bridge, ``PipelineRunner.run_njr`` and registry dispatch run; only the two image
backends are fakes registered as ``forge_webui`` and ``comfyui``. No process, network, model or GPU.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.assets.compatibility import CompatibilityProfile, CompatibilityStatus, ModelFamily
from src.image_backends import (
    ImageBackendCapabilities,
    ImageBackendRegistry,
    ImageExecutionResult,
    model_policy,
)
from tools.acceptance import img_comfy_381_compare as driver
from tools.acceptance.img_forge_100_acceptance import InjectedRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]
QUAL_100 = (
    REPO_ROOT
    / "docs"
    / "Subsystems"
    / "Image"
    / "PR-IMG-BACKEND-QUAL-100_Forge_vs_Comfy_Still_Image_Qualification.md"
)
SDXL_LOOKUP = Mock(
    return_value=CompatibilityProfile(CompatibilityStatus.RESOLVED, ModelFamily.SDXL, ())
)


class FakeBackend:
    """Writes a deterministic PNG and manifest; carries the backend id in the pixels so arms differ."""

    def __init__(self, backend_id: str, fail_on: str = "") -> None:
        self.backend_id = backend_id
        self.fail_on = fail_on
        self.capabilities = ImageBackendCapabilities(
            backend_id=backend_id, stage_types=("txt2img",)
        )
        self.calls: list[str] = []

    def execute(self, pipeline: Any, request: Any) -> ImageExecutionResult:
        from PIL import Image

        from src.pipeline.artifact_contract import artifact_manifest_payload
        from src.utils.atomic_io import atomic_write_json

        self.calls.append(str(request.job_id))
        if self.fail_on and self.fail_on in str(request.job_id):
            raise RuntimeError("fake backend failure")
        out = Path(request.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        shade = (sum(map(ord, self.backend_id)) + int(request.seed or 0)) % 200 + 20
        target = out / f"{request.job_id}.png"
        Image.new("RGB", (64, 48), (shade, 90, 150)).save(target)
        manifest = out / "manifests" / f"{target.stem}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] = {
            "image_backend_id": self.backend_id, "model": request.selected_model, "seed": request.seed, "name": target.stem,
            "all_paths": [str(target)], "manifest_path": str(manifest), "path": str(target), "output_path": str(target),
            "comfy_sdxl": {"approximations": ["scheduler Automatic -> normal"]} if self.backend_id == "comfyui" else None,
        }  # fmt: skip
        metadata["artifact"] = artifact_manifest_payload(
            stage="txt2img",
            image_or_output_path=target,
            manifest_path=manifest,
            output_paths=[str(target)],
            job_id=request.job_id,
        )
        atomic_write_json(manifest, metadata, indent=2, ensure_ascii=False)
        return ImageExecutionResult.from_stage_result(
            backend_id=self.backend_id,
            stage_name="txt2img",
            result=metadata,
            backend_metadata={"backend_id": self.backend_id},
        )


class _NoWebUIPipeline:
    client = None

    def _begin_run_metrics(self) -> None:
        return None

    def get_run_efficiency_metrics(self, _variant_count: int) -> dict[str, object]:
        return {}


@pytest.fixture(autouse=True)
def _comfy_compiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_policy, "RegistryFamilyLookup", lambda *a, **k: SDXL_LOOKUP)


def _contexts(backends: dict[str, FakeBackend]) -> dict[str, driver.ArmRuntime]:
    registry = ImageBackendRegistry()
    for backend in backends.values():
        registry.register(backend)

    def prepare(runner: Any) -> None:
        runner._pipeline = _NoWebUIPipeline()

    return {
        arm: driver.ArmRuntime(InjectedRuntime(), client=Mock(), registry=registry, prepare=prepare)
        for arm in backends
    }


def _args(reports: Path, **overrides: Any) -> argparse.Namespace:
    values = {
        "reports_dir": reports, "intent": driver.DEFAULT_INTENT, "workloads": ["S1", "S3"], "shuffle_seed": 7,
        "approved_plan_sha256": "", "timeout_seconds": 60.0, "dry": False,
    }  # fmt: skip
    values.update(overrides)
    return argparse.Namespace(**values)


def _backends(**kwargs: Any) -> dict[str, FakeBackend]:
    return {arm: FakeBackend(arm, **kwargs) for arm in driver.ARMS}


# -- the plan -----------------------------------------------------------------------------------------------------------


def test_the_plan_has_six_prompts_by_two_seeds_for_s1_and_a_lora_subset_for_s3() -> None:
    pairs = driver.build_pairs(driver.load_settings(driver.DEFAULT_INTENT))
    s1 = [p for p in pairs if p.workload == "S1"]
    s3 = [p for p in pairs if p.workload == "S3"]
    assert len({p.prompt_id for p in s1}) == 6 and len({p.seed for p in s1}) == 2 and len(s1) == 12
    assert len(s3) == 4 and all(p.lora for p in s3) and not any(p.lora for p in s1)


def test_a_pair_differs_only_in_backend_id_and_a_tampered_pair_is_refused(tmp_path: Path) -> None:
    settings = driver.load_settings(driver.DEFAULT_INTENT)
    spec = driver.build_pairs(settings)[0]
    njrs = driver.freeze_pair(settings, spec, tmp_path)
    assert njrs[driver.FORGE].backend_options["image"]["backend_id"] == "forge_webui"
    assert njrs[driver.COMFY].backend_options["image"]["backend_id"] == "comfyui"
    other = driver.freeze_pair(settings, driver.build_pairs(settings)[1], tmp_path)
    with pytest.raises(driver.PairMismatch, match="differ beyond backend_id"):
        driver.assert_matched(njrs[driver.FORGE], other[driver.COMFY])


def test_a_dry_run_writes_only_the_plan_and_its_digest_is_stable(tmp_path: Path) -> None:
    code = driver.run(_args(tmp_path / "a", dry=True), None, physical=False)
    assert code == driver.EXIT_DRY
    plan = json.loads((tmp_path / "a" / "plan.json").read_text(encoding="utf-8"))
    assert sorted(path.name for path in (tmp_path / "a").iterdir()) == ["plan.json"]
    driver.run(_args(tmp_path / "b", dry=True), None, physical=False)
    assert (
        json.loads((tmp_path / "b" / "plan.json").read_text(encoding="utf-8"))["plan_sha256"]
        == plan["plan_sha256"]
    )
    assert len(plan["pairs"]) == 16


# -- authorization ------------------------------------------------------------------------------------------------------


def test_a_physical_run_is_refused_without_the_approved_plan_digest(tmp_path: Path) -> None:
    backends = _backends()
    with pytest.raises(PermissionError, match="approved plan digest"):
        driver.run(_args(tmp_path / "r"), _contexts(backends), physical=True)
    assert all(not backend.calls for backend in backends.values())
    with pytest.raises(PermissionError):
        driver.run(
            _args(tmp_path / "r2", approved_plan_sha256="0" * 64),
            _contexts(backends),
            physical=True,
        )
    assert all(not backend.calls for backend in backends.values())


def test_main_refuses_a_physical_run_without_a_digest_before_starting_anything(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        driver.main(
            ["--reports-dir", str(tmp_path / "x"), "--runtime-profile", str(tmp_path / "p.json")]
        )


# -- the run and its evidence -------------------------------------------------------------------------------------------


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, FakeBackend]]:
    backends = _backends()
    reports = tmp_path / "reports"
    code = driver.run(_args(reports), _contexts(backends), physical=False)
    assert code == driver.EXIT_COMPLETED
    return reports, json.loads((reports / "compare.json").read_text(encoding="utf-8")), backends


def test_every_pair_runs_on_both_backends_through_the_canonical_path(evidence) -> None:
    _, compare, backends = evidence
    assert len(backends["forge_webui"].calls) == len(backends["comfyui"].calls) == 16
    assert len(compare["pairs"]) == 16
    first = compare["pairs"][0]
    assert first["forge_webui"]["status"] == first["comfyui"]["status"] == "completed"
    assert first["forge_webui"]["output_sha256"] != first["comfyui"]["output_sha256"]
    assert first["comfyui"]["approximations"] == ["scheduler Automatic -> normal"]
    assert first["seed_equality"] == "unverified"


def test_timing_is_labelled_cold_for_the_first_job_of_each_arm_and_warm_after(evidence) -> None:
    _, compare, _ = evidence
    for arm in driver.ARMS:
        phases = [pair[arm]["phase"] for pair in compare["pairs"]]
        assert phases[0] == "cold" and set(phases[1:]) == {"warm"}
    assert "held warm" in compare["timing_note"]
    assert all(
        "warm_hold_end" in record and record["warm_hold_end"] is None
        for record in compare["arms"].values()
    )  # the arm ended the (absent) hold through the warm-hold owner


def test_the_verdict_is_owner_pending_with_no_numeric_threshold_and_the_fairness_text_is_verbatim(
    evidence,
) -> None:
    _, compare, _ = evidence
    assert compare["verdict"] == "OWNER_REVIEW_PENDING" and compare["perceptual_threshold"] is None
    assert set(compare["not_comparable"]) == {"flux", "qwen_image"}
    source = re.sub(r"\s+", " ", QUAL_100.read_text(encoding="utf-8"))
    assert compare["fairness_caveats"] in source


def test_the_blind_review_hides_the_arm_and_the_key_is_separate_and_reproducible(
    evidence, tmp_path: Path
) -> None:
    reports, compare, _ = evidence
    review = reports / "review"
    rows = list(csv.DictReader((review / "review.csv").read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 16 and (review / "contact_sheet.png").is_file()
    assert (review / "rater.html").is_file()
    assert "forge" not in (review / "review.csv").read_text(encoding="utf-8").lower()
    key = json.loads((reports / "review_key.json").read_text(encoding="utf-8"))
    assert key["shuffle_seed"] == 7 == compare["shuffle_seed"]
    assert {entry["A"] for entry in key["pairs"].values()} == {
        "forge_webui",
        "comfyui",
    }  # the order really shuffles
    # The reviewer-facing images carry no embedded text (no backend id or prompt).
    from PIL import Image

    with Image.open(review / rows[0]["image_a"]) as image:
        assert not image.info
    # The same seed gives the same order.
    runs = [tmp_path / "again1", tmp_path / "again2"]
    for run_dir in runs:
        driver.run(_args(run_dir, workloads=["S3"]), _contexts(_backends()), physical=False)
    keys = [
        json.loads((run_dir / "review_key.json").read_text(encoding="utf-8"))["pairs"]
        for run_dir in runs
    ]
    assert keys[0] == keys[1]


def test_a_failed_job_stops_the_run_without_retry_or_substitution(tmp_path: Path) -> None:
    backends = {
        "forge_webui": FakeBackend("forge_webui"),
        "comfyui": FakeBackend("comfyui", fail_on="S3-p0-s424243"),
    }
    reports = tmp_path / "r"
    code = driver.run(_args(reports, workloads=["S3"]), _contexts(backends), physical=False)
    assert code == driver.EXIT_FAILED
    assert (
        len(backends["comfyui"].calls) == 2 and len(backends["forge_webui"].calls) == 4
    )  # stops; never replays or falls back
    compare = json.loads((reports / "compare.json").read_text(encoding="utf-8"))
    assert (
        compare["exit_code"] == driver.EXIT_FAILED and compare["verdict"] == "OWNER_REVIEW_PENDING"
    )


def test_evidence_is_never_overwritten(tmp_path: Path) -> None:
    reports = tmp_path / "r"
    reports.mkdir()
    (reports / "old.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        driver.run(_args(reports, dry=True), None, physical=False)


def test_the_contact_sheet_labels_default_to_the_original_columns(tmp_path: Path) -> None:
    from PIL import Image

    from tools.qualification.img_forge_100.contact_sheet import create_contact_sheet

    one, two = tmp_path / "1.png", tmp_path / "2.png"
    Image.new("RGB", (16, 16), "red").save(one)
    Image.new("RGB", (16, 16), "blue").save(two)
    create_contact_sheet([("c", one, two)], tmp_path / "default.png", tile=64)
    create_contact_sheet([("c", one, two)], tmp_path / "blind.png", tile=64, labels=("A", "B"))
    assert (tmp_path / "default.png").stat().st_size > 0 and (
        tmp_path / "blind.png"
    ).stat().st_size > 0
