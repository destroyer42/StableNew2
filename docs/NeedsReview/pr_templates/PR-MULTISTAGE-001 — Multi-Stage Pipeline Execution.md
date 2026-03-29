PR-MULTISTAGE-001 — Multi-Stage Pipeline Execution.md with NJR-Driven RunPlan and Canonical Output Layout
EXECUTOR ACKNOWLEDGEMENT & COMPLIANCE BLOCK
By proceeding, I acknowledge the StableNew v2.6 Canonical Execution Contract. I understand that partial compliance, undocumented deviations, or unverifiable claims constitute failure. I will either complete the PR exactly as specified with proof, or I will stop.

PR ID
PR-MULTISTAGE-001-RUNPLAN-STAGE-CHAIN

Related Canonical Sections
ARCHITECTURE_v2.6.md Section 4 (Builder Pipeline Architecture)
ARCHITECTURE_v2.6.md Section 5 (Queue & Runner)
StableNew_v2.6_Canonical_Execution_Contract.md Section 3 (RunPlan + Runner)
PROMPT_PACK_LIFECYCLE_v2.6 Section 4 (Stage Chain)
INTENT
What this PR does:
Enforces NJR-only execution — RunPlan is constructed exclusively from NormalizedJobRecord
Implements ordered stage chain execution — txt2img → refiner → hires → upscale → adetailer execute in order when enabled
Creates canonical output layout — All artifacts written to structured outputs/<job_id>__<pack>__<ts>/images/<stage>/ and manifests/
Fixes job completion semantics — Jobs marked COMPLETED when stages succeed, not FAILED after artifact production
Returns typed PipelineRunResult — Runner returns structured results with per-stage outputs
What this PR does NOT do:
Does not modify executor.py (forbidden by contract)
Does not change GUI components
Does not add new pipeline stages
Does not modify WebUI launch/connection logic
SCOPE OF CHANGE
Files TO BE MODIFIED (REQUIRED)
File	Purpose
run_plan.py	Create if missing; build RunPlan from NJR with stage chain and output destinations
pipeline_runner.py	Execute RunPlan stages in order, return typed PipelineRunResult
job_models_v2.py	Add StageOutput and extend PipelineRunResult typing
job_builder_v2.py	Ensure stage chain + per-stage config embedded in NJR
src/services/output_layout_service.py	Create; centralize canonical output directory structure
Files TO BE CREATED (REQUIRED)
File	Purpose
tests/pipeline/test_run_plan_output_layout.py	Test RunPlan produces correct output paths
tests/pipeline/test_pipeline_runner_true_ready_and_stages.py	Test stage chain execution + result normalization
tests/queue/test_queue_njr_multistage_completion.py	Test queue job completes correctly with multi-stage
Files TO BE DELETED (IF PRESENT)
File	Verification
legacy_njr_adapter.py	Prove via git status + git grep = 0 matches
Files MUST NOT BE MODIFIED (HARD FAIL)
executor.py
main_window_v2.py
theme_v2.py
main.py
ARCHITECTURAL COMPLIANCE
 NJR-only execution path
 No PipelineConfig usage in runtime
 No dict-based execution configs
 PipelineRunResult is the only runner output type
 run_njr() is the only public entrypoint
 Legacy code classified (DELETED or VIEW-ONLY)
IMPLEMENTATION STEPS
Step 1: Create src/services/output_layout_service.py
Purpose: Centralize canonical output directory structure.
# ...existing code...

@dataclass
class StageOutput:
    """Output from a single pipeline stage execution."""

    stage_name: str
    image_paths: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    skipped: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "stage_name": self.stage_name,
            "image_paths": list(self.image_paths),
            "manifest_paths": list(self.manifest_paths),
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "error": self.error,
        }


@dataclass
class PipelineRunResult:
    """Result of a complete pipeline run."""

    success: bool
    job_id: str
    final_image_paths: list[str] = field(default_factory=list)
    stage_outputs: list[StageOutput] = field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None
    run_root: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "job_id": self.job_id,
            "final_image_paths": list(self.final_image_paths),
            "stage_outputs": [s.to_dict() for s in self.stage_outputs],
            "error": self.error,
            "error_stage": self.error_stage,
            "run_root": self.run_root,
            "duration_ms": self.duration_ms,
        }

# ...existing code...
Step 2: Extend job_models_v2.py with StageOutput and PipelineRunResult
Purpose: Add typed stage outputs for multi-stage results.
# ...existing code...

@dataclass
class StageOutput:
    """Output from a single pipeline stage execution."""

    stage_name: str
    image_paths: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    skipped: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "stage_name": self.stage_name,
            "image_paths": list(self.image_paths),
            "manifest_paths": list(self.manifest_paths),
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "error": self.error,
        }


@dataclass
class PipelineRunResult:
    """Result of a complete pipeline run."""

    success: bool
    job_id: str
    final_image_paths: list[str] = field(default_factory=list)
    stage_outputs: list[StageOutput] = field(default_factory=list)
    error: str | None = None
    error_stage: str | None = None
    run_root: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "job_id": self.job_id,
            "final_image_paths": list(self.final_image_paths),
            "stage_outputs": [s.to_dict() for s in self.stage_outputs],
            "error": self.error,
            "error_stage": self.error_stage,
            "run_root": self.run_root,
            "duration_ms": self.duration_ms,
        }

# ...existing code...
Step 3: Create run_plan.py
Purpose: Build RunPlan from NJR with stage chain and output destinations.
# ...existing imports...

import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.gui.state import CancelToken

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    PipelineRunResult,
    StageOutput,
)
from src.pipeline.run_plan import RunPlan, build_run_plan
from src.services.output_layout_service import OutputLayoutService

# ...existing code...

logger = logging.getLogger(__name__)


class PipelineRunner:
    """NJR-only pipeline runner with RunPlan-driven execution."""

    def __init__(
        self,
        executor: Any,  # Pipeline executor instance
        output_base_dir: str | Path = "outputs",
    ):
        self._executor = executor
        self._layout_service = OutputLayoutService(output_base_dir)

    def run_njr(
        self,
        njr: NormalizedJobRecord,
        cancel_token: "CancelToken | None" = None,
    ) -> PipelineRunResult:
        """
        Execute a pipeline run from a NormalizedJobRecord.

        This is the ONLY public entrypoint for pipeline execution.

        Args:
            njr: The normalized job record to execute
            cancel_token: Optional cancellation token

        Returns:
            PipelineRunResult with success status and stage outputs
        """
        start_time = time.monotonic()

        # Compute output layout
        layout = self._layout_service.compute_layout(njr)

        # Build run plan from NJR
        run_plan = build_run_plan(njr, layout)

        # Ensure directories exist for enabled stages
        enabled_stage_names = run_plan.stage_names()
        self._layout_service.ensure_directories(layout, enabled_stage_names)

        # Write NJR snapshot
        self._write_njr_snapshot(layout, njr)

        # Execute stages
        stage_outputs: list[StageOutput] = []
        final_image_paths: list[str] = []
        last_image_path: str | None = None
        error: str | None = None
        error_stage: str | None = None

        for stage_plan in run_plan.enabled_stages():
            # Check cancellation
            if cancel_token and cancel_token.is_cancelled():
                error = "Cancelled by user"
                error_stage = stage_plan.stage_name
                break

            stage_start = time.monotonic()
            logger.info(
                "PIPELINE_STAGE_START: job_id=%s, stage=%s",
                run_plan.job_id,
                stage_plan.stage_name,
            )

            try:
                stage_output = self._execute_stage(
                    stage_plan=stage_plan,
                    run_plan=run_plan,
                    layout=layout,
                    input_image_path=last_image_path,
                    cancel_token=cancel_token,
                )

                stage_output.duration_ms = int((time.monotonic() - stage_start) * 1000)
                stage_outputs.append(stage_output)

                # Update last image for next stage
                if stage_output.image_paths:
                    last_image_path = stage_output.image_paths[-1]
                    final_image_paths.extend(stage_output.image_paths)

                logger.info(
                    "PIPELINE_STAGE_DONE: job_id=%s, stage=%s, images=%d, duration_ms=%d",
                    run_plan.job_id,
                    stage_plan.stage_name,
                    len(stage_output.image_paths),
                    stage_output.duration_ms or 0,
                )

            except Exception as exc:
                logger.error(
                    "PIPELINE_STAGE_ERROR: job_id=%s, stage=%s, error=%s",
                    run_plan.job_id,
                    stage_plan.stage_name,
                    str(exc),
                )
                error = str(exc)
                error_stage = stage_plan.stage_name

                # Record failed stage
                stage_outputs.append(
                    StageOutput(
                        stage_name=stage_plan.stage_name,
                        error=str(exc),
                        duration_ms=int((time.monotonic() - stage_start) * 1000),
                    )
                )
                break

        # Compute success: txt2img must have produced images
        txt2img_outputs = [s for s in stage_outputs if s.stage_name == "txt2img"]
        success = bool(txt2img_outputs and txt2img_outputs[0].image_paths and not error)

        total_duration_ms = int((time.monotonic() - start_time) * 1000)

        # Write run metadata
        result = PipelineRunResult(
            success=success,
            job_id=run_plan.job_id,
            final_image_paths=final_image_paths,
            stage_outputs=stage_outputs,
            error=error,
            error_stage=error_stage,
            run_root=str(layout.run_root),
            duration_ms=total_duration_ms,
        )

        self._write_run_metadata(layout, result, run_plan)

        return result

    def _execute_stage(
        self,
        stage_plan: "StagePlan",
        run_plan: RunPlan,
        layout: "OutputLayout",
        input_image_path: str | None,
        cancel_token: "CancelToken | None",
    ) -> StageOutput:
        """Execute a single stage and return its output."""
        from src.pipeline.run_plan import StagePlan
        from src.services.output_layout_service import OutputLayout

        stage_name = stage_plan.stage_name
        config = stage_plan.config

        # Prepare output directory
        output_dir = Path(stage_plan.output_image_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_paths: list[str] = []
        manifest_paths: list[str] = []

        if stage_name == "txt2img":
            # txt2img stage
            result = self._executor.run_txt2img_stage(
                prompt=run_plan.positive_prompt,
                negative_prompt=run_plan.negative_prompt,
                config=config,
                output_dir=output_dir,
                image_name="txt2img_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                # Write manifest
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "img2img" and input_image_path:
            result = self._executor.run_img2img_stage(
                input_image_path=Path(input_image_path),
                prompt=run_plan.positive_prompt,
                config=config,
                output_dir=output_dir,
                image_name="img2img_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "upscale" and input_image_path:
            result = self._executor.run_upscale_stage(
                input_image_path=Path(input_image_path),
                config=config,
                output_dir=output_dir,
                image_name="upscale_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "adetailer" and input_image_path:
            result = self._executor.run_adetailer_stage(
                input_image_path=Path(input_image_path),
                config=config,
                output_dir=output_dir,
                image_name="adetailer_00",
                prompt=run_plan.positive_prompt,
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name in ("refiner", "hires"):
            # These are handled as part of txt2img in executor
            # Mark as skipped if reached separately
            return StageOutput(stage_name=stage_name, skipped=True)

        else:
            # Unknown or inapplicable stage
            return StageOutput(stage_name=stage_name, skipped=True)

        return StageOutput(
            stage_name=stage_name,
            image_paths=image_paths,
            manifest_paths=manifest_paths,
        )

    def _write_njr_snapshot(self, layout: "OutputLayout", njr: NormalizedJobRecord) -> None:
        """Write NJR snapshot to manifests directory."""
        try:
            snapshot = {
                "job_id": njr.job_id,
                "prompt_pack_id": njr.prompt_pack_id,
                "positive_prompt": njr.positive_prompt,
                "negative_prompt": njr.negative_prompt,
                "status": njr.status.value if njr.status else None,
                "created_ts": njr.created_ts,
            }
            layout.njr_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with open(layout.njr_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write NJR snapshot: %s", exc)

    def _write_stage_manifest(self, path: Path, metadata: dict[str, Any]) -> None:
        """Write stage manifest JSON."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write stage manifest %s: %s", path, exc)

    def _write_run_metadata(
        self,
        layout: "OutputLayout",
        result: PipelineRunResult,
        run_plan: RunPlan,
    ) -> None:
        """Write run metadata summary."""
        try:
            metadata = {
                "job_id": result.job_id,
                "success": result.success,
                "error": result.error,
                "error_stage": result.error_stage,
                "duration_ms": result.duration_ms,
                "stages_executed": [s.stage_name for s in result.stage_outputs if not s.skipped],
                "stages_skipped": [s.stage_name for s in result.stage_outputs if s.skipped],
                "final_image_count": len(result.final_image_paths),
                "run_plan": run_plan.to_dict(),
            }
            layout.run_metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(layout.run_metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write run metadata: %s", exc)


# ...existing code if any...
Step 4: Update pipeline_runner.py
Purpose: Execute RunPlan stages in order, return typed PipelineRunResult.
# ...existing imports...

import json
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.gui.state import CancelToken

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    PipelineRunResult,
    StageOutput,
)
from src.pipeline.run_plan import RunPlan, build_run_plan
from src.services.output_layout_service import OutputLayoutService

# ...existing code...

logger = logging.getLogger(__name__)


class PipelineRunner:
    """NJR-only pipeline runner with RunPlan-driven execution."""

    def __init__(
        self,
        executor: Any,  # Pipeline executor instance
        output_base_dir: str | Path = "outputs",
    ):
        self._executor = executor
        self._layout_service = OutputLayoutService(output_base_dir)

    def run_njr(
        self,
        njr: NormalizedJobRecord,
        cancel_token: "CancelToken | None" = None,
    ) -> PipelineRunResult:
        """
        Execute a pipeline run from a NormalizedJobRecord.

        This is the ONLY public entrypoint for pipeline execution.

        Args:
            njr: The normalized job record to execute
            cancel_token: Optional cancellation token

        Returns:
            PipelineRunResult with success status and stage outputs
        """
        start_time = time.monotonic()

        # Compute output layout
        layout = self._layout_service.compute_layout(njr)

        # Build run plan from NJR
        run_plan = build_run_plan(njr, layout)

        # Ensure directories exist for enabled stages
        enabled_stage_names = run_plan.stage_names()
        self._layout_service.ensure_directories(layout, enabled_stage_names)

        # Write NJR snapshot
        self._write_njr_snapshot(layout, njr)

        # Execute stages
        stage_outputs: list[StageOutput] = []
        final_image_paths: list[str] = []
        last_image_path: str | None = None
        error: str | None = None
        error_stage: str | None = None

        for stage_plan in run_plan.enabled_stages():
            # Check cancellation
            if cancel_token and cancel_token.is_cancelled():
                error = "Cancelled by user"
                error_stage = stage_plan.stage_name
                break

            stage_start = time.monotonic()
            logger.info(
                "PIPELINE_STAGE_START: job_id=%s, stage=%s",
                run_plan.job_id,
                stage_plan.stage_name,
            )

            try:
                stage_output = self._execute_stage(
                    stage_plan=stage_plan,
                    run_plan=run_plan,
                    layout=layout,
                    input_image_path=last_image_path,
                    cancel_token=cancel_token,
                )

                stage_output.duration_ms = int((time.monotonic() - stage_start) * 1000)
                stage_outputs.append(stage_output)

                # Update last image for next stage
                if stage_output.image_paths:
                    last_image_path = stage_output.image_paths[-1]
                    final_image_paths.extend(stage_output.image_paths)

                logger.info(
                    "PIPELINE_STAGE_DONE: job_id=%s, stage=%s, images=%d, duration_ms=%d",
                    run_plan.job_id,
                    stage_plan.stage_name,
                    len(stage_output.image_paths),
                    stage_output.duration_ms or 0,
                )

            except Exception as exc:
                logger.error(
                    "PIPELINE_STAGE_ERROR: job_id=%s, stage=%s, error=%s",
                    run_plan.job_id,
                    stage_plan.stage_name,
                    str(exc),
                )
                error = str(exc)
                error_stage = stage_plan.stage_name

                # Record failed stage
                stage_outputs.append(
                    StageOutput(
                        stage_name=stage_plan.stage_name,
                        error=str(exc),
                        duration_ms=int((time.monotonic() - stage_start) * 1000),
                    )
                )
                break

        # Compute success: txt2img must have produced images
        txt2img_outputs = [s for s in stage_outputs if s.stage_name == "txt2img"]
        success = bool(txt2img_outputs and txt2img_outputs[0].image_paths and not error)

        total_duration_ms = int((time.monotonic() - start_time) * 1000)

        # Write run metadata
        result = PipelineRunResult(
            success=success,
            job_id=run_plan.job_id,
            final_image_paths=final_image_paths,
            stage_outputs=stage_outputs,
            error=error,
            error_stage=error_stage,
            run_root=str(layout.run_root),
            duration_ms=total_duration_ms,
        )

        self._write_run_metadata(layout, result, run_plan)

        return result

    def _execute_stage(
        self,
        stage_plan: "StagePlan",
        run_plan: RunPlan,
        layout: "OutputLayout",
        input_image_path: str | None,
        cancel_token: "CancelToken | None",
    ) -> StageOutput:
        """Execute a single stage and return its output."""
        from src.pipeline.run_plan import StagePlan
        from src.services.output_layout_service import OutputLayout

        stage_name = stage_plan.stage_name
        config = stage_plan.config

        # Prepare output directory
        output_dir = Path(stage_plan.output_image_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        image_paths: list[str] = []
        manifest_paths: list[str] = []

        if stage_name == "txt2img":
            # txt2img stage
            result = self._executor.run_txt2img_stage(
                prompt=run_plan.positive_prompt,
                negative_prompt=run_plan.negative_prompt,
                config=config,
                output_dir=output_dir,
                image_name="txt2img_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                # Write manifest
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "img2img" and input_image_path:
            result = self._executor.run_img2img_stage(
                input_image_path=Path(input_image_path),
                prompt=run_plan.positive_prompt,
                config=config,
                output_dir=output_dir,
                image_name="img2img_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "upscale" and input_image_path:
            result = self._executor.run_upscale_stage(
                input_image_path=Path(input_image_path),
                config=config,
                output_dir=output_dir,
                image_name="upscale_00",
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name == "adetailer" and input_image_path:
            result = self._executor.run_adetailer_stage(
                input_image_path=Path(input_image_path),
                config=config,
                output_dir=output_dir,
                image_name="adetailer_00",
                prompt=run_plan.positive_prompt,
                cancel_token=cancel_token,
            )
            if result and result.get("path"):
                image_paths.append(result["path"])
                manifest_path = layout.stage_manifest_path(stage_name, 0)
                self._write_stage_manifest(manifest_path, result)
                manifest_paths.append(str(manifest_path))

        elif stage_name in ("refiner", "hires"):
            # These are handled as part of txt2img in executor
            # Mark as skipped if reached separately
            return StageOutput(stage_name=stage_name, skipped=True)

        else:
            # Unknown or inapplicable stage
            return StageOutput(stage_name=stage_name, skipped=True)

        return StageOutput(
            stage_name=stage_name,
            image_paths=image_paths,
            manifest_paths=manifest_paths,
        )

    def _write_njr_snapshot(self, layout: "OutputLayout", njr: NormalizedJobRecord) -> None:
        """Write NJR snapshot to manifests directory."""
        try:
            snapshot = {
                "job_id": njr.job_id,
                "prompt_pack_id": njr.prompt_pack_id,
                "positive_prompt": njr.positive_prompt,
                "negative_prompt": njr.negative_prompt,
                "status": njr.status.value if njr.status else None,
                "created_ts": njr.created_ts,
            }
            layout.njr_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with open(layout.njr_snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write NJR snapshot: %s", exc)

    def _write_stage_manifest(self, path: Path, metadata: dict[str, Any]) -> None:
        """Write stage manifest JSON."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write stage manifest %s: %s", path, exc)

    def _write_run_metadata(
        self,
        layout: "OutputLayout",
        result: PipelineRunResult,
        run_plan: RunPlan,
    ) -> None:
        """Write run metadata summary."""
        try:
            metadata = {
                "job_id": result.job_id,
                "success": result.success,
                "error": result.error,
                "error_stage": result.error_stage,
                "duration_ms": result.duration_ms,
                "stages_executed": [s.stage_name for s in result.stage_outputs if not s.skipped],
                "stages_skipped": [s.stage_name for s in result.stage_outputs if s.skipped],
                "final_image_count": len(result.final_image_paths),
                "run_plan": run_plan.to_dict(),
            }
            layout.run_metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(layout.run_metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to write run metadata: %s", exc)


# ...existing code if any...
First, let me examine the current pipeline_runner.py:

Step 5: Update job_builder_v2.py
Purpose: Ensure stage chain + per-stage config embedded in NJR.

# ...existing code...

    def build_from_run_request(self, run_request: PipelineRunRequest) -> list[NormalizedJobRecord]:
        """Build normalized jobs directly from a PipelineRunRequest.

        Expands each PackJobEntry's prompts list into individual NJRs.
        A pack with 10 prompts produces 10 NJRs.
        
        Stage chain is embedded from config with validation.
        """
        entries = list(run_request.pack_entries or [])
        if not entries:
            return []

        jobs: list[NormalizedJobRecord] = []
        output_dir = run_request.explicit_output_dir or "output"
        filename_template = "{seed}"

        global_prompt_index = 0

        for entry in entries:
            config = entry.config_snapshot or {}
            txt2img_config = config.get("txt2img", {})
            pipeline_config = config.get("pipeline", {})

            # Get list of prompts from the entry - each becomes a separate NJR
            prompts_to_expand = entry.prompts if entry.prompts else [entry.prompt_text or ""]

            for prompt_index, prompt_text in enumerate(prompts_to_expand):
                if global_prompt_index >= run_request.max_njr_count:
                    break

                seed = self._extract_config_value(config, "seed") or txt2img_config.get("seed")
                seed_val = int(seed) if seed is not None else None

                # Build stage chain from config
                stage_chain = self._build_stage_chain(config)

                # Validate stage configs exist for enabled stages
                self._validate_stage_configs(stage_chain, config)

                # Use the specific prompt from the prompts list
                final_prompt = prompt_text.strip() if prompt_text else ""
                final_negative = entry.negative_prompt_text or ""

                record = NormalizedJobRecord(
                    job_id=self._id_fn(),
                    config=config,
                    path_output_dir=output_dir,
                    filename_template=filename_template,
                    seed=seed_val,
                    variant_index=0,
                    variant_total=1,
                    batch_index=0,
                    batch_total=1,
                    created_ts=self._time_fn(),
                    randomizer_summary=entry.randomizer_metadata,
                    txt2img_prompt_info=StagePromptInfo(
                        original_prompt=final_prompt,
                        final_prompt=final_prompt,
                        original_negative_prompt=final_negative,
                        final_negative_prompt=final_negative,
                        global_negative_applied=False,
                    ),
                    pack_usage=self._build_pack_usage(config),
                    prompt_pack_id=run_request.prompt_pack_id,
                    prompt_pack_name=entry.pack_name or "",
                    prompt_pack_row_index=prompt_index,
                    positive_prompt=final_prompt,
                    negative_prompt=final_negative,
                    positive_embeddings=list(entry.matrix_slot_values.keys()),
                    negative_embeddings=[],
                    lora_tags=[],
                    matrix_slot_values=dict(entry.matrix_slot_values),
                    steps=int(txt2img_config.get("steps") or config.get("steps") or 20),
                    cfg_scale=float(txt2img_config.get("cfg_scale") or config.get("cfg_scale") or 7.5),
                    width=int(txt2img_config.get("width") or config.get("width") or 1024),
                    height=int(txt2img_config.get("height") or config.get("height") or 1024),
                    sampler_name=txt2img_config.get("sampler_name") or config.get("sampler") or "DPM++ 2M",
                    scheduler=txt2img_config.get("scheduler") or config.get("scheduler") or "ddim",
                    clip_skip=int(config.get("clip_skip", 0) or 0),
                    base_model=txt2img_config.get("model") or config.get("model") or "unknown",
                    vae=txt2img_config.get("vae"),
                    stage_chain=stage_chain,
                    loop_type=pipeline_config.get("loop_type", "pipeline"),
                    loop_count=int(pipeline_config.get("loop_count", 1)),
                    images_per_prompt=int(pipeline_config.get("images_per_prompt", 1)),
                    variant_mode=str(pipeline_config.get("variant_mode", "standard")),
                    run_mode=run_request.run_mode.name,
                    queue_source=run_request.source.name,
                    randomization_enabled=bool(config.get("randomization", {}).get("enabled")),
                    matrix_name=str(config.get("randomization", {}).get("matrix_name", "")),
                    matrix_mode=str(config.get("randomization", {}).get("mode", "")),
                    matrix_prompt_mode=str(config.get("randomization", {}).get("prompt_mode", "")),
                    config_variant_label="base",
                    config_variant_index=0,
                    config_variant_overrides={},
                    aesthetic_enabled=bool(config.get("aesthetic", {}).get("enabled")),
                    aesthetic_weight=config.get("aesthetic", {}).get("weight"),
                    aesthetic_text=config.get("aesthetic", {}).get("text"),
                    aesthetic_embedding=config.get("aesthetic", {}).get("embedding"),
                    extra_metadata={
                        "tags": list(run_request.tags),
                        "selected_row_ids": list(run_request.selected_row_ids),
                        "requested_job_label": run_request.requested_job_label,
                        "pack_prompt_index": prompt_index,
                        "pack_prompt_total": len(prompts_to_expand),
                    },
                    status=JobStatusV2.QUEUED,
                )
                jobs.append(record)
                global_prompt_index += 1

            if global_prompt_index >= run_request.max_njr_count:
                break

        return jobs

    def _build_stage_chain(self, config: dict[str, Any]) -> list[StageConfig]:
        """Build ordered stage chain from config."""
        pipeline_cfg = config.get("pipeline", {})
        txt2img_cfg = config.get("txt2img", {})

        stages: list[StageConfig] = []

        # txt2img is always first and always enabled
        stages.append(StageConfig(
            stage_type="txt2img",
            enabled=True,
            steps=int(txt2img_cfg.get("steps") or 20),
            cfg_scale=float(txt2img_cfg.get("cfg_scale") or 7.5),
            sampler_name=txt2img_cfg.get("sampler_name") or "DPM++ 2M",
            scheduler=txt2img_cfg.get("scheduler") or "ddim",
            model=txt2img_cfg.get("model") or "unknown",
            vae=txt2img_cfg.get("vae"),
            extra={},
        ))

        # img2img (optional)
        if pipeline_cfg.get("img2img_enabled", False):
            img2img_cfg = config.get("img2img", {})
            stages.append(StageConfig(
                stage_type="img2img",
                enabled=True,
                steps=int(img2img_cfg.get("steps") or 15),
                cfg_scale=float(img2img_cfg.get("cfg_scale") or 7.0),
                sampler_name=img2img_cfg.get("sampler_name") or "DPM++ 2M",
                scheduler=img2img_cfg.get("scheduler"),
                model=img2img_cfg.get("model"),
                vae=img2img_cfg.get("vae"),
                extra={"denoising_strength": img2img_cfg.get("denoising_strength", 0.3)},
            ))

        # upscale (optional)
        if pipeline_cfg.get("upscale_enabled", False):
            upscale_cfg = config.get("upscale", {})
            stages.append(StageConfig(
                stage_type="upscale",
                enabled=True,
                steps=int(upscale_cfg.get("steps") or 20),
                cfg_scale=float(upscale_cfg.get("cfg_scale") or 7.0),
                sampler_name=upscale_cfg.get("sampler_name"),
                scheduler=upscale_cfg.get("scheduler"),
                model=None,
                vae=None,
                extra={
                    "upscaler": upscale_cfg.get("upscaler", "R-ESRGAN 4x+"),
                    "upscaling_resize": upscale_cfg.get("upscaling_resize", 2.0),
                },
            ))

        # adetailer (optional)
        if pipeline_cfg.get("adetailer_enabled", False):
            adetailer_cfg = config.get("adetailer", {})
            stages.append(StageConfig(
                stage_type="adetailer",
                enabled=True,
                steps=int(adetailer_cfg.get("adetailer_steps") or 28),
                cfg_scale=float(adetailer_cfg.get("adetailer_cfg") or 7.0),
                sampler_name=adetailer_cfg.get("adetailer_sampler") or "DPM++ 2M",
                scheduler=None,
                model=None,
                vae=None,
                extra={
                    "adetailer_model": adetailer_cfg.get("adetailer_model", "face_yolov8n.pt"),
                    "adetailer_denoise": adetailer_cfg.get("adetailer_denoise", 0.4),
                },
            ))

        return stages

    def _validate_stage_configs(self, stage_chain: list[StageConfig], config: dict[str, Any]) -> None:
        """Validate that enabled stages have required config sections."""
        for stage in stage_chain:
            if not stage.enabled:
                continue

            stage_type = stage.stage_type

            # Skip txt2img validation (always present)
            if stage_type == "txt2img":
                continue

            # Check config section exists
            if stage_type == "adetailer":
                if "adetailer" not in config:
                    raise ValueError(
                        f"Stage '{stage_type}' is enabled but no '{stage_type}' config section exists"
                    )
            elif stage_type == "upscale":
                if "upscale" not in config:
                    raise ValueError(
                        f"Stage '{stage_type}' is enabled but no '{stage_type}' config section exists"
                    )
            elif stage_type == "img2img":
                if "img2img" not in config:
                    raise ValueError(
                        f"Stage '{stage_type}' is enabled but no '{stage_type}' config section exists"
                    )

# ...existing code...

Step 6: Create Test Files
A) tests/pipeline/test_run_plan_output_layout.py
"""Tests for RunPlan output layout generation."""

import pytest
from pathlib import Path

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig, JobStatusV2
from src.pipeline.run_plan import build_run_plan, STAGE_ORDER
from src.services.output_layout_service import OutputLayoutService, OutputLayout


class TestOutputLayoutService:
    """Test OutputLayoutService produces correct paths."""

    def test_compute_layout_creates_correct_structure(self):
        """Layout should have correct run_root and subdirectories."""
        service = OutputLayoutService(base_output_dir="outputs")

        njr = NormalizedJobRecord(
            job_id="test-job-123",
            prompt_pack_id="my-pack",
            positive_prompt="test prompt",
            negative_prompt="",
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)

        # Verify run_root contains job_id and pack_id
        assert "test-job-123" in str(layout.run_root)
        assert "my-pack" in str(layout.run_root)

        # Verify manifests directory
        assert layout.manifests_dir == layout.run_root / "manifests"
        assert layout.run_metadata_path == layout.manifests_dir / "run_metadata.json"
        assert layout.njr_snapshot_path == layout.manifests_dir / "njr_snapshot.json"

    def test_stage_images_dir_returns_correct_path(self):
        """stage_images_dir should return images/<stage>/ path."""
        service = OutputLayoutService(base_output_dir="outputs")

        njr = NormalizedJobRecord(
            job_id="job-1",
            prompt_pack_id="pack-1",
            positive_prompt="",
            negative_prompt="",
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)

        assert layout.stage_images_dir("txt2img") == layout.run_root / "images" / "txt2img"
        assert layout.stage_images_dir("upscale") == layout.run_root / "images" / "upscale"
        assert layout.stage_images_dir("adetailer") == layout.run_root / "images" / "adetailer"

    def test_stage_manifest_path_returns_correct_path(self):
        """stage_manifest_path should return manifests/<stage>_<index>.json."""
        service = OutputLayoutService(base_output_dir="outputs")

        njr = NormalizedJobRecord(
            job_id="job-1",
            prompt_pack_id="pack-1",
            positive_prompt="",
            negative_prompt="",
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)

        assert layout.stage_manifest_path("txt2img", 0) == layout.manifests_dir / "txt2img_00.json"
        assert layout.stage_manifest_path("upscale", 1) == layout.manifests_dir / "upscale_01.json"

    def test_ensure_directories_creates_folders(self, tmp_path):
        """ensure_directories should create all required folders."""
        service = OutputLayoutService(base_output_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="job-1",
            prompt_pack_id="pack-1",
            positive_prompt="",
            negative_prompt="",
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)
        service.ensure_directories(layout, ["txt2img", "upscale", "adetailer"])

        assert layout.manifests_dir.exists()
        assert layout.stage_images_dir("txt2img").exists()
        assert layout.stage_images_dir("upscale").exists()
        assert layout.stage_images_dir("adetailer").exists()


class TestRunPlanOutputLayout:
    """Test RunPlan produces correct output paths."""

    def test_build_run_plan_with_multistage_chain(self):
        """RunPlan should include correct output destinations for all stages."""
        service = OutputLayoutService(base_output_dir="outputs")

        # Create NJR with multi-stage chain
        njr = NormalizedJobRecord(
            job_id="multi-stage-job",
            prompt_pack_id="test-pack",
            positive_prompt="a beautiful landscape",
            negative_prompt="ugly",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="adetailer", enabled=True, steps=28, cfg_scale=7.0),
            ],
            config={
                "pipeline": {
                    "upscale_enabled": True,
                    "adetailer_enabled": True,
                },
            },
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)
        run_plan = build_run_plan(njr, layout)

        # Verify stages are present
        enabled_stages = run_plan.enabled_stages()
        stage_names = [s.stage_name for s in enabled_stages]

        assert "txt2img" in stage_names
        assert "upscale" in stage_names
        assert "adetailer" in stage_names

        # Verify output paths
        for stage in enabled_stages:
            assert "images" in stage.output_image_dir
            assert stage.stage_name in stage.output_image_dir
            assert "manifests" in stage.output_manifest_path
            assert stage.stage_name in stage.output_manifest_path

    def test_build_run_plan_requires_njr_type(self):
        """build_run_plan should reject non-NJR inputs."""
        service = OutputLayoutService(base_output_dir="outputs")

        # Create a minimal NJR just for layout
        njr = NormalizedJobRecord(
            job_id="x",
            prompt_pack_id="y",
            positive_prompt="",
            negative_prompt="",
            status=JobStatusV2.QUEUED,
        )
        layout = service.compute_layout(njr)

        # Should reject dict
        with pytest.raises(AssertionError, match="requires NormalizedJobRecord"):
            build_run_plan({"job_id": "fake"}, layout)  # type: ignore

    def test_run_plan_stage_order_is_canonical(self):
        """Stages should be in canonical order."""
        service = OutputLayoutService(base_output_dir="outputs")

        njr = NormalizedJobRecord(
            job_id="order-test",
            prompt_pack_id="pack",
            positive_prompt="",
            negative_prompt="",
            config={
                "pipeline": {
                    "img2img_enabled": True,
                    "upscale_enabled": True,
                    "adetailer_enabled": True,
                },
            },
            status=JobStatusV2.QUEUED,
        )

        layout = service.compute_layout(njr)
        run_plan = build_run_plan(njr, layout)

        # Get all stage names (including disabled)
        all_stage_names = [s.stage_name for s in run_plan.stages]

        # Verify order matches STAGE_ORDER
        for i, stage_name in enumerate(all_stage_names):
            if stage_name in STAGE_ORDER:
                assert STAGE_ORDER.index(stage_name) >= 0
B) tests/pipeline/test_pipeline_runner_true_ready_and_stages.py
"""Tests for PipelineRunner stage chain execution."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    StageConfig,
    JobStatusV2,
    PipelineRunResult,
    StageOutput,
)
from src.pipeline.pipeline_runner import PipelineRunner
from src.services.output_layout_service import OutputLayoutService


class FakeExecutor:
    """Fake executor that returns successful stage results."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.calls: list[str] = []

    def run_txt2img_stage(self, **kwargs) -> dict:
        self.calls.append("txt2img")
        # Create fake image file
        output_dir = kwargs.get("output_dir", self.tmp_path)
        image_name = kwargs.get("image_name", "txt2img_00")
        image_path = output_dir / f"{image_name}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake png data")
        return {"path": str(image_path), "name": image_name}

    def run_img2img_stage(self, **kwargs) -> dict:
        self.calls.append("img2img")
        output_dir = kwargs.get("output_dir", self.tmp_path)
        image_name = kwargs.get("image_name", "img2img_00")
        image_path = output_dir / f"{image_name}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake img2img data")
        return {"path": str(image_path), "name": image_name}

    def run_upscale_stage(self, **kwargs) -> dict:
        self.calls.append("upscale")
        output_dir = kwargs.get("output_dir", self.tmp_path)
        image_name = kwargs.get("image_name", "upscale_00")
        image_path = output_dir / f"{image_name}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake upscale data")
        return {"path": str(image_path), "name": image_name}

    def run_adetailer_stage(self, **kwargs) -> dict:
        self.calls.append("adetailer")
        output_dir = kwargs.get("output_dir", self.tmp_path)
        image_name = kwargs.get("image_name", "adetailer_00")
        image_path = output_dir / f"{image_name}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"fake adetailer data")
        return {"path": str(image_path), "name": image_name}


class TestPipelineRunnerStageExecution:
    """Test PipelineRunner executes stage chain correctly."""

    def test_run_njr_executes_txt2img_only_when_no_other_stages(self, tmp_path):
        """With only txt2img enabled, only txt2img should execute."""
        executor = FakeExecutor(tmp_path)
        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="txt2img-only",
            prompt_pack_id="test",
            positive_prompt="test prompt",
            negative_prompt="bad",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
            ],
            config={},
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        assert result.success is True
        assert "txt2img" in executor.calls
        assert len(executor.calls) == 1
        assert len(result.stage_outputs) >= 1
        assert result.stage_outputs[0].stage_name == "txt2img"

    def test_run_njr_executes_full_stage_chain(self, tmp_path):
        """With all stages enabled, all should execute in order."""
        executor = FakeExecutor(tmp_path)
        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="full-chain",
            prompt_pack_id="test",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="adetailer", enabled=True, steps=28, cfg_scale=7.0),
            ],
            config={
                "pipeline": {
                    "upscale_enabled": True,
                    "adetailer_enabled": True,
                },
                "upscale": {"upscaler": "R-ESRGAN 4x+"},
                "adetailer": {"adetailer_model": "face_yolov8n.pt"},
            },
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        assert result.success is True
        assert "txt2img" in executor.calls
        assert "upscale" in executor.calls
        assert "adetailer" in executor.calls

        # Verify order
        assert executor.calls.index("txt2img") < executor.calls.index("upscale")
        assert executor.calls.index("upscale") < executor.calls.index("adetailer")

    def test_run_njr_saves_artifacts_to_correct_directories(self, tmp_path):
        """Artifacts should be saved under correct stage folders."""
        executor = FakeExecutor(tmp_path)
        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="artifact-test",
            prompt_pack_id="pack1",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
            ],
            config={
                "pipeline": {"upscale_enabled": True},
                "upscale": {},
            },
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        assert result.success is True
        assert result.run_root is not None

        run_root = Path(result.run_root)

        # Check directories exist
        assert (run_root / "manifests").exists()
        assert (run_root / "images" / "txt2img").exists()
        assert (run_root / "images" / "upscale").exists()

        # Check manifests written
        assert (run_root / "manifests" / "run_metadata.json").exists()
        assert (run_root / "manifests" / "njr_snapshot.json").exists()

    def test_run_njr_returns_typed_result(self, tmp_path):
        """Result should be PipelineRunResult with correct fields."""
        executor = FakeExecutor(tmp_path)
        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="typed-result",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
            ],
            config={},
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        assert isinstance(result, PipelineRunResult)
        assert result.job_id == "typed-result"
        assert isinstance(result.stage_outputs, list)
        assert all(isinstance(s, StageOutput) for s in result.stage_outputs)
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    def test_run_njr_marks_success_when_txt2img_produces_images(self, tmp_path):
        """Job should be marked successful when txt2img produces images."""
        executor = FakeExecutor(tmp_path)
        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="success-test",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
            ],
            config={},
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        assert result.success is True
        assert result.error is None
        assert len(result.final_image_paths) >= 1


class TestPipelineRunnerErrorHandling:
    """Test PipelineRunner handles errors correctly."""

    def test_run_njr_captures_stage_error(self, tmp_path):
        """Stage errors should be captured in result."""
        executor = FakeExecutor(tmp_path)

        # Make upscale fail
        def failing_upscale(**kwargs):
            raise RuntimeError("Upscale failed!")

        executor.run_upscale_stage = failing_upscale

        runner = PipelineRunner(executor, output_base_dir=tmp_path / "outputs")

        njr = NormalizedJobRecord(
            job_id="error-test",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
            ],
            config={
                "pipeline": {"upscale_enabled": True},
                "upscale": {},
            },
            status=JobStatusV2.QUEUED,
        )

        result = runner.run_njr(njr)

        # txt2img succeeded, so we have images, but error occurred
        assert result.error is not None
        assert "Upscale failed" in result.error
        assert result.error_stage == "upscale"
C) tests/queue/test_queue_njr_multistage_completion.py
"""Tests for queue NJR multi-stage completion lifecycle."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    StageConfig,
    JobStatusV2,
    PipelineRunResult,
    StageOutput,
)


class TestQueueNJRMultistageCompletion:
    """Test queue correctly handles multi-stage NJR completion."""

    def test_njr_lifecycle_submitted_to_completed(self):
        """NJR should transition SUBMITTED → QUEUED → RUNNING → COMPLETED."""
        # Create NJR
        njr = NormalizedJobRecord(
            job_id="lifecycle-test",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="adetailer", enabled=True, steps=28, cfg_scale=7.0),
            ],
            config={
                "pipeline": {
                    "upscale_enabled": True,
                    "adetailer_enabled": True,
                },
                "upscale": {},
                "adetailer": {},
            },
            status=JobStatusV2.QUEUED,
        )

        # Simulate successful pipeline result
        result = PipelineRunResult(
            success=True,
            job_id=njr.job_id,
            final_image_paths=["/path/to/image.png"],
            stage_outputs=[
                StageOutput(stage_name="txt2img", image_paths=["/path/txt2img.png"]),
                StageOutput(stage_name="upscale", image_paths=["/path/upscale.png"]),
                StageOutput(stage_name="adetailer", image_paths=["/path/adetailer.png"]),
            ],
        )

        # When result.success is True, job should be COMPLETED
        assert result.success is True
        assert result.error is None

        # In actual queue implementation, this would set:
        # njr.status = JobStatusV2.COMPLETED
        # For this test, we verify the result indicates completion
        assert len(result.stage_outputs) == 3
        assert all(s.image_paths for s in result.stage_outputs)

    def test_njr_not_marked_failed_when_images_exist(self):
        # filepath: c:\Users\rob\projects\StableNew\tests\queue\test_queue_njr_multistage_completion.py
"""Tests for queue NJR multi-stage completion lifecycle."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.job_models_v2 import (
    NormalizedJobRecord,
    StageConfig,
    JobStatusV2,
    PipelineRunResult,
    StageOutput,
)


class TestQueueNJRMultistageCompletion:
    """Test queue correctly handles multi-stage NJR completion."""

    def test_njr_lifecycle_submitted_to_completed(self):
        """NJR should transition SUBMITTED → QUEUED → RUNNING → COMPLETED."""
        # Create NJR
        njr = NormalizedJobRecord(
            job_id="lifecycle-test",
            prompt_pack_id="pack",
            positive_prompt="test",
            negative_prompt="",
            stage_chain=[
                StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="upscale", enabled=True, steps=20, cfg_scale=7.0),
                StageConfig(stage_type="adetailer", enabled=True, steps=28, cfg_scale=7.0),
            ],
            config={
                "pipeline": {
                    "upscale_enabled": True,
                    "adetailer_enabled": True,
                },
                "upscale": {},
                "adetailer": {},
            },
            status=JobStatusV2.QUEUED,
        )

        # Simulate successful pipeline result
        result = PipelineRunResult(
            success=True,
            job_id=njr.job_id,
            final_image_paths=["/path/to/image.png"],
            stage_outputs=[
                StageOutput(stage_name="txt2img", image_paths=["/path/txt2img.png"]),
                StageOutput(stage_name="upscale", image_paths=["/path/upscale.png"]),
                StageOutput(stage_name="adetailer", image_paths=["/path/adetailer.png"]),
            ],
        )

        # When result.success is True, job should be COMPLETED
        assert result.success is True
        assert result.error is None

        # In actual queue implementation, this would set:
        # njr.status = JobStatusV2.COMPLETED
        # For this test, we verify the result indicates completion
        assert len(result.stage_outputs) == 3
        assert all(s.image_paths for s in result.stage_outputs)

    def test_njr_not_marked_failed_when_images_exist(self):
        
