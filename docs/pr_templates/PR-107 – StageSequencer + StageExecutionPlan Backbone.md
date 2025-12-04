PR-107 – StageSequencer + StageExecutionPlan Backbone.md

Risk Tier: Medium → treat as Tier 3 (heavy) because it touches the pipeline runner path.
Baseline: StableNew-snapshot-20251203-071519.zip + repo_inventory.json

Goal:
Lock in a single, canonical stage order and require every pipeline run to go through a StageExecutionPlan:

txt2img → (optional) refiner/hires → (optional) upscale → (optional) ADetailer

…with guardrails so we:

Never run ADetailer without at least one generation stage.

Keep refiner/hires attached as metadata to the generation stage(s), not random free-floating options.

Have a runner that only iterates a StageExecutionPlan, using one _call_stage helper and last_image_meta to chain images.

1. Intent & Outcomes

After PR-107:

StageSequencer.build_plan(pipeline_config) becomes the single place where we:

Interpret the high-level pipeline_config.

Decide which stages actually run and in what order.

Attach refiner/hires/upscale/adetailer metadata to those stages.

PipelineRunner.run(...) only executes a StageExecutionPlan:

If given a config, it first delegates to StageSequencer.build_plan.

It loops over plan entries with _call_stage(stage, last_image_meta) and pipes outputs forward.

Misconfigured pipelines (e.g., ADetailer enabled but no txt2img/img2img) fail fast with a clear error before talking to WebUI.

We have unit tests for sequencing and a small smoke test for the runner executing a full 4-stage plan (using fakes, not a real SD server).

2. Scope
In-Scope

src/pipeline/stage_models.py

StageExecution, StageExecutionPlan, any StageType enum or equivalent.

src/pipeline/run_plan.py (or stage_sequencer.py)

StageSequencer and its build_plan entrypoint.

src/pipeline/pipeline_runner.py

PipelineRunner.run(plan_or_config) and internal _call_stage helper.

tests/pipeline/test_stage_sequencing.py

New or extended tests for the sequencer and runner.

Out-of-Scope

src/pipeline/executor.py (no direct edits).

API client / WebUI HTTP calls – use fakes in tests.

GUI wiring and controller routing (handled by other PRs).

Learning/queue/cluster logic (they consume jobs; this PR stops at the runner/plan boundary).

3. Data Model: StageExecution & StageExecutionPlan

File: src/pipeline/stage_models.py

If these already exist, extend them; if not, introduce them in this shape.

3.1 StageType enum

Define an explicit enum (or equivalent constants) so sequence rules can be expressed cleanly:

from enum import Enum


class StageType(str, Enum):
    TXT2IMG = "txt2img"
    IMG2IMG = "img2img"
    UPSCALE = "upscale"
    ADETAILER = "adetailer"


Refiner and Hires are not separate StageTypes; they are metadata on txt2img (and possibly img2img) stages.

3.2 StageExecution dataclass

A single stage entry:

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass
class StageExecution:
    stage_type: StageType

    # Pointer to the logical “slot” in the pipeline config (e.g., "txt2img", "img2img")
    config_key: str

    # Shallow snapshot of values needed to build the payload for this stage
    config: Mapping[str, Any] = field(default_factory=dict)

    # Refiner / Hires metadata (optional, only used on generation stages)
    refiner_enabled: bool = False
    refiner_model_name: Optional[str] = None
    refiner_switch_step: Optional[int] = None

    hires_enabled: bool = False
    hires_upscaler_name: Optional[str] = None
    hires_denoise_strength: Optional[float] = None
    hires_scale_factor: Optional[float] = None

    # ADetailer toggle may be linked but often represented as a separate stage
    adetailer_enabled: bool = False


You can keep this lean and adjust field names to match your existing config schema (refiner_model, hires_upscaler, etc.) – the PR should align them.

3.3 StageExecutionPlan

Simple wrapper for an ordered list:

@dataclass
class StageExecutionPlan:
    stages: list[StageExecution]

    def is_empty(self) -> bool:
        return not self.stages

    def has_generation_stage(self) -> bool:
        return any(s.stage_type in (StageType.TXT2IMG, StageType.IMG2IMG) for s in self.stages)

    def __iter__(self):
        return iter(self.stages)


Optionally add helper get_stage_types() for tests.

4. StageSequencer.build_plan(pipeline_config)

File: src/pipeline/run_plan.py (or stage_sequencer.py)

Add or complete a StageSequencer class with a single public API:

class StageSequencer:
    def build_plan(self, pipeline_config: Mapping[str, Any]) -> StageExecutionPlan:
        ...

4.1 Expected pipeline_config inputs

At minimum, the sequencer needs:

Generation toggles:

pipeline_config["txt2img_enabled"]  # bool
pipeline_config["img2img_enabled"]  # bool


Upscale & ADetailer toggles:

pipeline_config["upscale_enabled"]
pipeline_config["adetailer_enabled"]


Refiner / Hires knobs (on the txt2img config – align names with app_state):

pipeline_config["refiner_enabled"]
pipeline_config["refiner_model_name"]
pipeline_config["refiner_switch_step"]

pipeline_config["hires_enabled"]
pipeline_config["hires_upscaler_name"]
pipeline_config["hires_denoise_strength"]
pipeline_config["hires_scale_factor"]


You can adapt these keys to whatever your PipelineConfig already exposes; the spec is about behavior, not exact names.

4.2 Canonical ordering rules

Implement build_plan to:

Initialize an empty list stages: list[StageExecution] = [].

Determine booleans:

txt2img_enabled = bool(pipeline_config.get("txt2img_enabled"))
img2img_enabled = bool(pipeline_config.get("img2img_enabled"))
upscale_enabled = bool(pipeline_config.get("upscale_enabled"))
adetailer_enabled = bool(pipeline_config.get("adetailer_enabled"))


Compute refiner/hires metadata once from config.

Append stages in order, if enabled:

if txt2img_enabled:
    stages.append(StageExecution(
        stage_type=StageType.TXT2IMG,
        config_key="txt2img",
        config=pipeline_config.get("txt2img_config") or {},
        refiner_enabled=refiner_enabled,
        refiner_model_name=refiner_model_name,
        refiner_switch_step=refiner_switch_step,
        hires_enabled=hires_enabled,
        hires_upscaler_name=hires_upscaler_name,
        hires_denoise_strength=hires_denoise_strength,
        hires_scale_factor=hires_scale_factor,
    ))

if img2img_enabled:
    stages.append(StageExecution(
        stage_type=StageType.IMG2IMG,
        config_key="img2img",
        config=pipeline_config.get("img2img_config") or {},
        # Typically refiner/hires are not used on img2img, but if you do,
        # you can choose to propagate or leave False here.
    ))

if upscale_enabled:
    stages.append(StageExecution(
        stage_type=StageType.UPSCALE,
        config_key="upscale",
        config=pipeline_config.get("upscale_config") or {},
    ))

if adetailer_enabled:
    stages.append(StageExecution(
        stage_type=StageType.ADETAILER,
        config_key="adetailer",
        config=pipeline_config.get("adetailer_config") or {},
    ))


Guardrails:

If not stages → return an empty plan or raise a specific error depending on your design; for now, only error on invalid ADetailer usage:

If adetailer_enabled and no generation stage (txt2img/img2img) is present → raise:

class InvalidStagePlanError(ValueError):
    ...

if adetailer_enabled and not any(
    s.stage_type in (StageType.TXT2IMG, StageType.IMG2IMG)
    for s in stages
):
    raise InvalidStagePlanError(
        "ADetailer requires at least one generation stage (txt2img or img2img)."
    )


Wrap:

return StageExecutionPlan(stages=stages)


This is the canonical source of truth: any other code building stages should delegate to StageSequencer.build_plan.

5. PipelineRunner.run(plan) – plan-only execution

File: src/pipeline/pipeline_runner.py

The runner should only execute using a StageExecutionPlan. The public API can remain flexible, but internally it must always normalize to a plan.

5.1 Normalizing entrypoint

If you have something like:

class PipelineRunner:
    def run(self, pipeline_config: Mapping[str, Any]) -> RunResult:
        ...


Refactor to:

    def run(
        self,
        plan_or_config: StageExecutionPlan | Mapping[str, Any],
    ) -> dict[str, Any]:
        if isinstance(plan_or_config, StageExecutionPlan):
            plan = plan_or_config
        else:
            # treat as high-level config
            plan = self._sequencer.build_plan(plan_or_config)

        if plan.is_empty():
            # either no-op or early error; choose one.
            return {"images": [], "meta": {}}

        last_image_meta: dict[str, Any] | None = None
        for stage in plan:
            last_image_meta = self._call_stage(stage, last_image_meta)

        # final output; structure depends on your existing runner.
        return {
            "images": last_image_meta.get("images") if last_image_meta else [],
            "meta": last_image_meta or {},
        }


Where _sequencer is a StageSequencer instance (injected or constructed in __init__).

5.2 _call_stage with StageExecution

Ensure _call_stage signature consistently uses StageExecution:

    def _call_stage(
        self,
        stage: StageExecution,
        last_image_meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Build the payload and call the underlying executor/API for a single stage.
        """
        # Build payload from stage.config + refiner/hires metadata + last_image_meta.
        # Pseudo-structure:
        payload = self._build_payload_for_stage(stage, last_image_meta)

        # This should ultimately call into executor / ApiClient.generate_images,
        # but this PR does not change those internals.
        response_meta = self._executor.run_stage(stage.stage_type, payload)

        return response_meta


_build_payload_for_stage can be a small helper that merges:

Base config from stage.config.

refiner_* and hires_* fields on generation stages.

last_image_meta for input image / seed chaining.

The key is that all downstream code consumes StageExecution, not random dicts.

6. Tests

File: tests/pipeline/test_stage_sequencing.py (new or extended)

6.1 Unit tests: StageSequencer

Basic txt2img only

Config: txt2img_enabled=True, others False.

build_plan returns a plan with exactly one stage of type TXT2IMG.

No refiner/hires metadata if disabled.

Full chain: txt2img + refiner + hires + upscale + ADetailer

Config: all toggles on, with non-default refiner & hires options.

build_plan returns 3 or 4 stages in order:

[TXT2IMG, (optional IMG2IMG), UPSCALE, ADETAILER]


First generation stage (TXT2IMG) has refiner_enabled=True, refiner_model_name set, hires_enabled=True, etc.

ADetailer stage appears last.

Img2img with upscale, no txt2img

Config: img2img_enabled=True, txt2img_enabled=False, upscale_enabled=True, adetailer_enabled=False.

Plan: [IMG2IMG, UPSCALE].

Invalid: ADetailer enabled but no generation

Config: both txt2img_enabled=False, img2img_enabled=False, adetailer_enabled=True.

build_plan raises InvalidStagePlanError.

Empty plan behavior

Config: all toggles False.

build_plan returns an empty plan or raises a specific error (match your runner’s design).

6.2 Runner smoke tests

Use a stub executor so no SD/WebUI calls happen.

class StubExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[StageType, dict[str, Any]]] = []

    def run_stage(self, stage_type: StageType, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((stage_type, payload))
        # mimic output structure; include images list + meta
        return {"images": [f"{stage_type.value}_image"], "meta": {"stage": stage_type.value}}


Hook into PipelineRunner via injection in tests:

def make_runner_with_stub() -> tuple[PipelineRunner, StubExecutor]:
    executor = StubExecutor()
    runner = PipelineRunner(executor=executor, sequencer=StageSequencer())
    return runner, executor


Tests:

Full plan is executed in order

Build a config enabling all stages.

Call runner.run(config).

Assert:

assert [t for t, _ in executor.calls] == [
    StageType.TXT2IMG,  # maybe IMG2IMG too, if enabled
    StageType.UPSCALE,
    StageType.ADETAILER,
]


Assert result images list is from the last stage.

last_image_meta chaining

In StubExecutor.run_stage, capture some “input” from payload when last_image_meta is present and assert that second stage payload contains output from first stage.

E.g.:

def run_stage(...):
    if self.calls:
        assert "input_from_previous" in payload
    ...


This proves _call_stage is piping last_image_meta into payload.

7. Validation & Commands

Commands:

# Run new pipeline sequencing tests
pytest tests/pipeline/test_stage_sequencing.py

# Run all pipeline tests
pytest tests/pipeline

8. Acceptance Criteria

 StageType, StageExecution, StageExecutionPlan are defined in stage_models.py (or equivalent) and are used by both StageSequencer and PipelineRunner.

 StageSequencer.build_plan(pipeline_config):

Produces a plan whose stage types always follow TXT2IMG → IMG2IMG → UPSCALE → ADETAILER ordering when those stages are enabled.

Attaches refiner/hires metadata to generation stages when enabled.

Raises InvalidStagePlanError when ADetailer is enabled without any generation stage.

 PipelineRunner.run(...):

Always normalizes its input to a StageExecutionPlan using StageSequencer.

Iterates the plan sequentially, calling _call_stage(stage, last_image_meta) for each stage.

Correctly propagates last_image_meta from one stage to the next.

 New tests in tests/pipeline/test_stage_sequencing.py:

Cover valid sequencing cases and the invalid ADetailer-only case.

Include at least one smoke test where the runner executes a full chain using a stub executor.

 All existing pipeline tests continue to pass.

Once this lands, the stage pipeline becomes deterministic and auditable: controllers and jobs feed a single pipeline_config → StageSequencer.build_plan → PipelineRunner.run(plan) chain, and every change to stage ordering or refiner/hires logic can be tested in isolation.