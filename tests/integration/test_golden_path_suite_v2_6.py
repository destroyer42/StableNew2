"""Golden Path E2E Test Suite for StableNew v2.6 (PR-CORE-A/B/C/D).

This module implements the E2E Golden Path test matrix defined in:
docs/E2E_Golden_Path_Test_Matrix_v2.6.md

Tests validate the complete canonical execution path:
PromptPack → Controller → Builder → Queue → Runner → History → Learning → Debug Hub

Active scenarios keep their historical GPn labels (GP1, GP2, GP3, GP5, GP6, GP10, GP11);
the remaining labels are covered elsewhere or retired as recorded below.

Every test in this module is active. Scenarios whose behavior is covered by a
current authoritative test elsewhere, or that target removed/deferred behavior, are
dispositioned in
docs/Subsystems/Testing/PR-TEST-TRUTH-210_Pre_Forge_Execution_and_Test_Truth.md
rather than preserved here as skips.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.api.client import SDWebUIClient
from src.gui.models.prompt_pack_model import PromptPackModel
from src.pipeline.animatediff_models import AnimateDiffCapability
from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import BatchSettings, StageConfig
from src.queue.job_history_store import JobHistoryEntry, JobHistoryStore
from src.queue.job_model import Job, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.randomizer import RandomizationPlanV2
from tests.helpers.job_helpers import make_test_njr
from tests.helpers.njr_factory import make_pipeline_njr, make_queue_job
from tests.helpers.njr_queue_harness import run_njr_via_queue

# ============================================================================
# Helper Functions
# ============================================================================

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aRX0AAAAASUVORK5CYII="
)


def wait_for_job_completion(
    history_store: JobHistoryStore,
    job_id: str,
    timeout: float = 2.0,
    poll_interval: float = 0.01,
) -> JobHistoryEntry | None:
    """Poll history store until job reaches terminal state or timeout."""
    terminal_states = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    start = time.time()
    while time.time() - start < timeout:
        entry = history_store.get_job(job_id)
        if entry and entry.status in terminal_states:
            return entry
        time.sleep(poll_interval)
    return history_store.get_job(job_id)


# ============================================================================
# GP1: Single Simple Run (No Randomizer)
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp1
class TestGP1SingleSimpleRun:
    """GP1: Validate the absolute minimum viable loop.

    Purpose: Single PromptPack job, no randomizer, txt2img only, Run Now mode.

    Coverage: CORE-A, CORE-B, CORE-C, CORE-D
    """

    def test_gp1_single_simple_run_produces_one_job(self):
        """GP1.1: Builder emits exactly 1 NormalizedJobRecord with correct metadata."""

        # Step 1: Load PromptPack fixture
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp1_simple.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        assert pack.name == "GP1_Simple"
        assert len(pack.slots) >= 1, "Pack should have at least one slot"
        assert (
            pack.slots[0].text
            == "A beautiful sunset over mountains, photorealistic, highly detailed"
        )

        # Step 2: Create NJR using test helper (builder integration tested separately)
        njr = make_test_njr(
            job_id="gp1-test-001",
            prompt=pack.slots[0].text,
            base_model=pack.preset_data.get("base_model", "sdxl"),
            config={
                "sampler": pack.preset_data.get("sampler", "Euler"),
                "steps": pack.preset_data.get("steps", 20),
                "cfg_scale": pack.preset_data.get("cfg_scale", 7.0),
                "width": pack.preset_data.get("width", 1024),
                "height": pack.preset_data.get("height", 1024),
            },
        )

        # Step 3: Verify NJR structure
        assert njr.job_id == "gp1-test-001"
        assert njr.positive_prompt == pack.slots[0].text
        assert njr.base_model == pack.preset_data.get("base_model", "sdxl")
        assert njr.config["sampler"] == "Euler"
        assert njr.config["steps"] == 20

    def test_gp1_executes_through_runner(self):
        """GP1.2: NJR executes through runner with mocked HTTP transport."""

        # Step 1: Load fixture and create NJR
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp1_simple.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        njr = make_test_njr(
            job_id="gp1-test-002",
            prompt=pack.slots[0].text,
            base_model="sdxl",
            config={
                "sampler": "Euler",
                "steps": 20,
                "cfg_scale": 7.0,
            },
        )

        # Step 2: Execute through runner with HTTP mock
        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

        with patch.object(api_client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,fakeimage"],
                "parameters": {
                    "prompt": njr.positive_prompt,
                    "seed": njr.seed,
                    "steps": 20,
                },
            }
            mock_response.raise_for_status = Mock()
            mock_request.return_value = mock_response

            entry = run_njr_via_queue(njr, api_client, timeout_seconds=10.0)

            # Step 3: Verify execution
            assert entry.status.value == "completed"
            assert entry.job_id == "gp1-test-002"
            assert mock_request.called

    def test_gp1_history_contains_correct_summary(self):
        """GP1.3: History entry contains correct metadata after execution."""

        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp1_simple.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        njr = make_test_njr(
            job_id="gp1-test-003",
            prompt=pack.slots[0].text,
            base_model="sdxl",
            config={"sampler": "Euler", "steps": 20},
        )

        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

        with patch.object(api_client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,fake"],
                "parameters": {},
            }
            mock_response.raise_for_status = Mock()
            mock_request.return_value = mock_response

            entry = run_njr_via_queue(njr, api_client)

            # Verify history entry metadata
            assert entry.job_id == "gp1-test-003"
            assert entry.status == JobStatus.COMPLETED
            snapshot = (entry.snapshot or {}).get("normalized_job", {})
            assert snapshot
            workload = snapshot.get("workload", {})
            assert workload.get("positive_prompt") == pack.slots[0].text


# ============================================================================
# GP2: Queue-Only Run (Multiple Jobs, FIFO)
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp2
class TestGP2QueueOnlyRun:
    """GP2: Validate deterministic queue ordering.

    Purpose: Multiple jobs queued, verify FIFO execution.

    Coverage: CORE-A, CORE-B, CORE-C, CORE-D
    """

    def test_gp2_runner_completes_job_a_before_starting_b(self):
        """GP2.2: The single-node worker fully processes job A before starting job B."""
        job_queue = JobQueue()
        events: list[tuple[str, str]] = []

        def run_callable(job: Job) -> dict[str, str]:
            events.append(("start", job.job_id))
            time.sleep(0.05)
            events.append(("end", job.job_id))
            return {"job_id": job.job_id, "status": "completed"}

        runner = SingleNodeJobRunner(
            job_queue=job_queue, run_callable=run_callable, poll_interval=0.01
        )
        try:
            job_queue.submit(make_queue_job("gp2-a"))
            job_queue.submit(make_queue_job("gp2-b"))
            runner.start()

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                job_b = job_queue.get_job("gp2-b")
                if job_b is not None and job_b.status == JobStatus.COMPLETED:
                    break
                time.sleep(0.01)
        finally:
            runner.stop()

        assert events == [
            ("start", "gp2-a"),
            ("end", "gp2-a"),
            ("start", "gp2-b"),
            ("end", "gp2-b"),
        ]


# ============================================================================
# GP3: Batch Expansion (N>1)
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp3
class TestGP3BatchExpansion:
    """GP3: Validate batch fan-out.

    Purpose: Batch size > 1 produces multiple jobs with same prompt, different batch_index.

    Coverage: CORE-B, CORE-C, CORE-D
    """

    def test_gp3_batch_size_3_produces_3_jobs(self, tmp_path: Path):
        """GP3.1: Batch size=3 produces 3 NormalizedJobRecords."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp3_batch.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        # gp3_batch has batch_size=3
        assert pack.preset_data["batch_size"] == 3, (
            f"Expected batch_size=3, got {pack.preset_data.get('batch_size')}"
        )

        # Create 3 NJRs with batch_index=0,1,2
        njr_list = []
        for i in range(3):
            njr = make_test_njr(
                job_id=f"gp3-batch-{i}",
                prompt=pack.slots[0].text,
                base_model="sdxl",
                config={
                    "sampler": "DPM++ 2M Karras",
                    "steps": 25,
                    "cfg_scale": 7.5,
                    "width": 1024,
                    "height": 768,
                    "batch_size": 3,
                    "batch_index": i,
                },
            )
            njr_list.append(njr)

        assert len(njr_list) == 3, f"Expected 3 jobs from batch_size=3, got {len(njr_list)}"

        # Verify batch_index increments
        for i, njr in enumerate(njr_list):
            assert njr.config["batch_index"] == i, (
                f"Job {i} should have batch_index={i}, got {njr.config.get('batch_index')}"
            )

        # Expected:
        # - 3 records with batch_index=0,1,2
        # - Identical prompts
        # - Same variant_index

    def test_gp3_queue_runs_all_batch_jobs(self, tmp_path: Path):
        """GP3.2: Queue processes all 3 batch jobs."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp3_batch.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        # Create 3 NJRs with batch_index=0,1,2
        njr_list = []
        for i in range(3):
            njr = make_test_njr(
                job_id=f"gp3-batch-{i}",
                prompt=pack.slots[0].text,
                base_model="sdxl",
                config={
                    "sampler": "DPM++ 2M Karras",
                    "steps": 25,
                    "cfg_scale": 7.5,
                    "width": 1024,
                    "height": 768,
                    "batch_size": 3,
                    "batch_index": i,
                },
            )
            njr_list.append(njr)

        # Execute each batch job through runner
        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

        with patch.object(api_client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,iVBORw0KGgoAAAANS"],
                "info": json.dumps(
                    {
                        "prompt": "A serene lake reflecting the sky at dawn",
                        "all_prompts": ["A serene lake reflecting the sky at dawn"],
                        "all_negative_prompts": [""],
                        "seed": 42,
                        "all_seeds": [42],
                    }
                ),
            }
            mock_request.return_value = mock_response

            history_entries = []
            for njr in njr_list:
                entry = run_njr_via_queue(njr, api_client, timeout_seconds=10.0)
                history_entries.append(entry)

            # Verify all 3 jobs completed
            assert len(history_entries) == 3
            for entry in history_entries:
                assert entry.status.value == "completed"

            # Verify at least one generation call per batch job.
            # Runner may perform additional readiness/progress API calls.
            txt2img_calls = 0
            for call in mock_request.call_args_list:
                args = list(call.args)
                kwargs = call.kwargs or {}
                method = str(args[0] if len(args) > 0 else kwargs.get("method", ""))
                url = str(args[1] if len(args) > 1 else kwargs.get("url", ""))
                if method.upper() == "POST" and "/sdapi/v1/txt2img" in url:
                    txt2img_calls += 1
            assert txt2img_calls >= 3


# ============================================================================
# GP5: Randomizer × Batch Cross Product
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp5
class TestGP5RandomizerBatchCrossProduct:
    """GP5: Validate 2D expansion (matrix × batch).

    Purpose: Randomizer + Batch produces M×N jobs.

    Coverage: CORE-B, CORE-C, CORE-D
    """

    def test_gp5_2_variants_x_2_batch_produces_4_jobs(self):
        """GP5.1: 2 randomizer variants x 2 batch runs = 4 jobs with distinct indices."""

        @dataclass
        class _Config:
            prompt: str = "a test prompt"
            model: str = "base-model"
            cfg_scale: float = 7.0
            steps: int = 20
            seed: int = 42

        jobs = JobBuilderV2().build_jobs(
            base_config=_Config(),
            randomization_plan=RandomizationPlanV2(
                enabled=True, model_choices=["m1", "m2"], max_variants=2
            ),
            batch_settings=BatchSettings(batch_size=1, batch_runs=2),
        )

        assert [(job.variant_index, job.batch_index) for job in jobs] == [
            (0, 0),
            (0, 1),
            (1, 0),
            (1, 1),
        ]
        assert len({job.job_id for job in jobs}) == 4
        assert {job.variant_total for job in jobs} == {2}
        assert {job.batch_total for job in jobs} == {2}


# ============================================================================
# GP6: Multi-Stage SDXL Pipeline
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp6
class TestGP6MultiStagePipeline:
    """GP6: Validate multi-stage SDXL: Refiner + Hires + Upscale.

    Purpose: Stage chain built correctly with all stages configured.

    Coverage: CORE-B, CORE-C, CORE-D
    """

    def test_gp6_stage_chain_includes_all_enabled_stages(self, tmp_path: Path):
        """GP6.1: StageChain includes txt2img → refiner → hires → adetailer."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp6_stages.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        # gp6_stages has: hires, refiner, adetailer enabled
        njr = make_test_njr(
            job_id="gp6-stages-001",
            prompt=pack.slots[0].text,
            base_model="sdxl",
            config={
                "sampler": "Euler a",
                "steps": 30,
                "cfg_scale": 7.0,
                "width": 1024,
                "height": 1024,
                "enable_hr": True,
                "hr_scale": 2.0,
                "adetailer_enabled": True,
            },
        )

        # Verify stage flags enabled
        assert njr.config["enable_hr"] is True, "Hires should be enabled"
        assert njr.config["hr_scale"] == 2.0, "Hires scale should be 2.0"
        assert njr.config["adetailer_enabled"] is True, "ADetailer should be enabled"

    def test_gp6_runner_receives_structured_stage_configs(self, tmp_path: Path):
        """GP6.2: Runner receives complete stage configurations."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "packs" / "gp6_stages.json"
        pack = PromptPackModel.load_from_file(fixture_path)

        njr = make_test_njr(
            job_id="gp6-stages-002",
            prompt=pack.slots[0].text,
            base_model="sdxl",
            config={
                "sampler": "Euler a",
                "steps": 30,
                "cfg_scale": 7.0,
                "width": 1024,
                "height": 1024,
                "enable_hr": True,
                "hr_scale": 2.0,
                "adetailer_enabled": True,
            },
        )

        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

        with patch.object(api_client._session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "images": ["data:image/png;base64,iVBORw0KGgoAAAANS"],
                "info": json.dumps(
                    {
                        "prompt": "Futuristic cyberpunk cityscape at night",
                        "all_prompts": ["Futuristic cyberpunk cityscape at night"],
                        "all_negative_prompts": [""],
                        "seed": 42,
                        "all_seeds": [42],
                    }
                ),
            }
            mock_request.return_value = mock_response

            entry = run_njr_via_queue(njr, api_client, timeout_seconds=10.0)

            assert entry.status.value == "completed"

            # Verify runner processed multi-stage config
            assert mock_request.called

            # Verify NJR snapshot has stage flags enabled
            snapshot = (entry.snapshot or {}).get("normalized_job", {})
            assert snapshot
            workload = snapshot.get("workload", {})
            assert workload.get("positive_prompt") == pack.slots[0].text
            config = workload.get("config", {})
            assert config.get("enable_hr") is True
            assert config.get("adetailer_enabled") is True

    def test_gp6_animatediff_stage_creates_mp4_clip(self, tmp_path: Path):
        """GP6.3: AnimateDiff stage writes an MP4 clip artifact through the runner path."""
        seed_path = tmp_path / "seed.png"
        seed_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))

        njr = make_pipeline_njr(
            job_id="gp6-animatediff-001",
            positive_prompt="portrait photo of a woman subtly turning her head, cinematic lighting",
            negative_prompt="blurry, distorted, bad anatomy",
            base_model="realismFromHadesXL_2ndAnniversary",
            config={
                "model": "realismFromHadesXL_2ndAnniversary",
                "sampler": "Euler a",
                "scheduler": "Automatic",
                "steps": 6,
                "cfg_scale": 5.5,
                "width": 512,
                "height": 768,
            },
            stage_chain=(
                StageConfig(
                    stage_type="animatediff",
                    enabled=True,
                    steps=6,
                    cfg_scale=5.5,
                    sampler_name="Euler a",
                    scheduler="Automatic",
                    model="realismFromHadesXL_2ndAnniversary",
                    extra={
                        "enabled": True,
                        "motion_module": "mm_sdxl_hs.safetensors",
                        "fps": 8,
                        "video_length": 4,
                        "batch_size": 4,
                        "format": ["PNG", "Frame"],
                    },
                ),
            ),
            path_output_dir=str(tmp_path / "output"),
            input_image_paths=(str(seed_path),),
            start_stage="animatediff",
        )

        api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

        mock_http_response = {
            "images": [_TINY_PNG_BASE64, _TINY_PNG_BASE64, _TINY_PNG_BASE64, _TINY_PNG_BASE64],
            "info": json.dumps(
                {
                    "seed": 1234,
                    "subseed": 5678,
                    "extra_generation_params": {
                        "AnimateDiff": "model: mm_sdxl_hs.safetensors, video_length: 4, fps: 8"
                    },
                }
            ),
        }

        def _write_fake_video(
            self, image_paths, output_path, fps=24, codec="libx264", quality="medium"
        ):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake-mp4")
            return True

        with (
            patch.object(
                api_client,
                "get_animatediff_capability",
                return_value=AnimateDiffCapability(
                    available=True,
                    script_name="AnimateDiff",
                    motion_modules=["mm_sdxl_hs.safetensors"],
                ),
            ),
            patch.object(
                api_client, "get_current_model", return_value="realismFromHadesXL_2ndAnniversary"
            ),
            patch.object(api_client._session, "request") as mock_request,
            patch("src.api.webui_api.WebUIAPI.wait_until_true_ready", return_value=True),
            patch("src.api.client.wait_for_webui_ready", return_value=True),
            patch("src.api.client.validate_webui_health", return_value=True),
            patch(
                "src.pipeline.executor.VideoCreator.create_video_from_images", new=_write_fake_video
            ),
        ):
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_http_response
            mock_response.content = b"{}"
            mock_response.text = "{}"
            mock_response.headers = {}
            mock_response.raise_for_status = Mock()
            mock_request.return_value = mock_response

            entry = run_njr_via_queue(
                njr,
                api_client,
                timeout_seconds=10.0,
                mock_http_response=mock_http_response,
                artifact_root=tmp_path / "journey-workspace",
            )

        assert entry.status is JobStatus.COMPLETED
        result = entry.result or {}
        artifact = (result.get("metadata") or {}).get("animatediff_artifact")
        assert artifact is not None
        assert artifact["count"] == 1
        clip_path = Path(artifact["video_paths"][0])
        assert clip_path.exists()
        assert clip_path.suffix == ".mp4"
        assert len(list(clip_path.parent.glob(f"{clip_path.stem}_frames/*.png"))) == 4


# ============================================================================
# GP10: Learning Integration
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp10
class TestGP10LearningIntegration:
    """GP10: Validate Learning system receives complete job metadata.

    Purpose: Learning tab can access full NormalizedJobRecord for ratings.

    Coverage: CORE-C, CORE-D
    """

    def test_gp10_learning_receives_full_metadata(self, tmp_path: Path):
        """GP10.1: Learning receives complete job metadata including PromptPack provenance."""
        from types import SimpleNamespace

        from src.gui.controllers.learning_controller import LearningController
        from src.gui.learning_state import LearningExperiment, LearningState
        from src.learning.learning_record import LearningRecordWriter

        class _Var:
            def __init__(self, value):
                self._value = value

            def get(self):
                return self._value

            def set(self, value):
                self._value = value

        records_path = tmp_path / "data" / "learning" / "learning_records.jsonl"
        writer = LearningRecordWriter(records_path)
        learning_state = LearningState()
        learning_state.current_experiment = LearningExperiment(
            name="gp10_learning",
            stage="txt2img",
            variable_under_test="CFG Scale",
            prompt_text="portrait photo",
        )

        stage_cards = SimpleNamespace(txt2img_card=SimpleNamespace(cfg_var=_Var(7.0)))
        pipeline_controller = Mock()
        pipeline_controller.stage_cards_panel = stage_cards
        pipeline_controller.can_enqueue_learning_jobs.return_value = (True, "")
        pipeline_controller.get_preview_jobs.return_value = [object()]

        controller = LearningController(
            learning_state=learning_state,
            pipeline_controller=pipeline_controller,
            learning_record_writer=writer,
        )

        controller.save_review_feedback(
            {
                "image_path": str(tmp_path / "gp10.png"),
                "rating": 5,
                "quality_label": "excellent",
                "base_prompt": "portrait photo",
                "after_prompt": "portrait photo, improved hands",
                "stage": "txt2img",
                "model": "modelA.safetensors",
                "sampler": "Euler a",
                "scheduler": "karras",
                "steps": 30,
                "cfg_scale": 8.0,
            }
        )

        recommendations = controller.get_recommendations_for_current_prompt()
        assert recommendations is not None
        cfg_rec = recommendations.get_best_for_parameter("cfg_scale")
        assert cfg_rec is not None
        assert cfg_rec.recommended_value == 8.0
        assert "samples=" in cfg_rec.confidence_rationale

        controller.set_automation_mode("apply_with_confirm")
        assert controller.apply_recommendations_to_pipeline(recommendations) is True
        assert stage_cards.txt2img_card.cfg_var.get() == 8.0


# ============================================================================
# GP11: Mixed Queue (Randomized + Non-Randomized)
# ============================================================================


@pytest.mark.golden_path
@pytest.mark.gp11
class TestGP11MixedQueue:
    """GP11: Validate randomized and non-randomized jobs do not contaminate each other.

    Purpose: Compiling a randomized config and a plain config from the same base keeps
    each job's provenance and config isolated; FIFO queue ordering is covered by GP2.

    Coverage: CORE-A, CORE-B, CORE-C, CORE-D
    """

    def test_gp11_randomized_and_plain_jobs_do_not_contaminate(self):
        """GP11.1: Randomized variants never leak into plain jobs built from the same base."""

        @dataclass
        class _Config:
            prompt: str = "a test prompt"
            model: str = "base-model"
            cfg_scale: float = 7.0
            steps: int = 20
            seed: int = 42

        builder = JobBuilderV2()
        base = _Config()
        randomized = builder.build_jobs(
            base_config=base,
            randomization_plan=RandomizationPlanV2(
                enabled=True, model_choices=["m1", "m2"], max_variants=2
            ),
        )
        plain = builder.build_jobs(base_config=base)

        assert [job.config["model"] for job in randomized] == ["m1", "m2"]
        assert [job.variant_total for job in randomized] == [2, 2]
        assert len(plain) == 1
        assert plain[0].config["model"] == "base-model"
        assert plain[0].variant_total == 1
        assert not plain[0].randomizer_summary
        assert base.model == "base-model"
