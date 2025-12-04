PR-110 – Journey Test Helpers.md

Risk Tier: Medium (Tier 2 – test harness only)
Baseline: After PR-103, PR-107, PR-109 in place (run bridge, stage plan, job history)

1. Intent

Unblock PR-101 and future journey work by:

Defining a canonical helper API for journey tests that hides controller/runner internals.

Updating JT03, JT04, JT05 to use that helper API exclusively.

Adding a JT06 scaffold for more complex flows (e.g., prompt-pack batch + queue).

Codex’s specific blocker was: “I don’t know how to fetch the latest job/plan, and there’s no shared helper; I don’t want to duplicate logic in each test.” This PR creates that shared helper and applies it.

2. Scope
In-Scope

tests/journeys/journey_helpers_v2.py (new)

tests/journeys/test_jt03_*.py (update)

tests/journeys/test_jt04_*.py (update)

tests/journeys/test_jt05_*.py (update)

tests/journeys/test_jt06_*.py (new or early stub)

Out-of-Scope

Any code under src/ (controllers, runners, API).

New job history fields beyond what PR-109 provides.

GUI/Tk details (journeys should rely on AppController + services, not UI widgets).

3. Helper API: journey_helpers_v2

File: tests/journeys/journey_helpers_v2.py

Provide a small set of helpers that:

Start runs via AppController’s V2 methods.

Wait for job completion via JobService / JobHistoryStore.

Return JobRecord and StageExecutionPlan objects for assertions.

3.1 Surface

Example interface:

from typing import Any
from src.controller.app_controller import AppController
from src.pipeline.stage_models import StageExecutionPlan
from src.pipeline.job_history import JobRecord


def start_run_and_wait(
    app: AppController,
    *,
    use_run_now: bool = False,
    add_to_queue_only: bool = False,
    timeout_seconds: float = 30.0,
) -> JobRecord:
    ...


def get_latest_job(app: AppController) -> JobRecord | None:
    ...


def get_stage_plan_for_job(app: AppController, job: JobRecord) -> StageExecutionPlan | None:
    ...


You can adapt argument names as needed, but it should be simple for tests to call.

3.2 Implementation details

Starting the run

Use the existing V2 controller entrypoints:

if add_to_queue_only:
    app.on_add_job_to_queue_v2()
elif use_run_now:
    app.on_run_job_now_v2()
else:
    app.start_run_v2()


Waiting for completion

Assumes there is a job service or history store reachable from AppController, e.g.:

app.job_service

or app.job_history_store

or app.pipeline_controller.job_history

Pick the real reference and stick with it.

Pseudo-loop:

import time

def _wait_for_latest_job_completion(app: AppController, timeout_seconds: float) -> JobRecord:
    history = app.job_history_store  # or adapter
    deadline = time.time() + timeout_seconds

    last_seen: JobRecord | None = None
    while time.time() < deadline:
        job = history.latest_job()
        if job is not None:
            last_seen = job
            if job.completed_at is not None:
                return job
        time.sleep(0.1)

    if last_seen is None:
        raise TimeoutError("No job appeared in history within timeout.")
    raise TimeoutError(f"Job {last_seen.job_id} did not complete within timeout.")


start_run_and_wait then:

def start_run_and_wait(...):
    # trigger run
    ...
    # wait for job completion
    return _wait_for_latest_job_completion(app, timeout_seconds)


Stage plan retrieval

Depending on how you expose plans:

If the job stores a stage_plan_id or an embedded plan, fetch it directly.

Otherwise, you might expose a helper on a pipeline service, e.g.:

plan = app.pipeline_controller.get_stage_plan_for_job(job.job_id)


In tests, it’s enough to:

Provide an accessor that returns a StageExecutionPlan or None.

If the actual implementation is not ready yet, stub it out and add a TODO to wire it in once StageSequencer is fully integrated.

4. Updating JT03/JT04/JT05
4.1 JT03 – simple txt2img pipeline run

File: tests/journeys/test_jt03_*.py

Refactor to:

Set up AppController and initial pipeline config (txt2img only).

Call:

from tests.journeys.journey_helpers_v2 import start_run_and_wait, get_stage_plan_for_job

job = start_run_and_wait(app, use_run_now=False)


Assertions:

assert job.run_mode == "direct"
assert job.source == "run"
assert job.prompt_source in ("manual", "pack")  # depending on test setup

plan = get_stage_plan_for_job(app, job)
assert plan is not None
types = [stage.stage_type for stage in plan.stages]
assert types == [StageType.TXT2IMG]  # or includes IMG2IMG if configured that way


Keep any existing assertions about images / output paths, but retrieve them from job.meta or wherever your pipeline stores them.

4.2 JT04 – img2img + ADetailer flow

File: tests/journeys/test_jt04_*.py

Scenario: interactive run, typically direct or queue according to your design (most likely DIRECT via Run).

Use helper:

job = start_run_and_wait(app, use_run_now=False)


Assertions:

Mode & source:

assert job.run_mode in ("direct", "queue")  # choose the intended one
assert job.source == "run"


Stage order:

plan = get_stage_plan_for_job(app, job)
assert plan is not None
types = [s.stage_type for s in plan.stages]
assert StageType.IMG2IMG in types
assert StageType.ADETAILER in types
assert types.index(StageType.IMG2IMG) < types.index(StageType.ADETAILER)

4.3 JT05 – upscale journey

File: tests/journeys/test_jt05_*.py

Scenario: “Run Now” style queue-backed upscale.

Use helper:

job = start_run_and_wait(app, use_run_now=True)


Assertions:

assert job.run_mode == "queue"
assert job.source == "run_now"

plan = get_stage_plan_for_job(app, job)
assert plan is not None
types = [s.stage_type for s in plan.stages]
assert StageType.UPSCALE in types


If the journey config includes a generation stage before upscale, check full order (TXT2IMG/IMG2IMG → UPSCALE).

5. JT06 – Prompt-pack batch / queue journey (scaffold)

File: tests/journeys/test_jt06_*.py (new or upgraded stub)

Scenario: at least one prompt-pack-based queue run.

Setup:

Load or construct a prompt pack.

Configure AppController/state so job_draft.pack_id is set.

Choose queue-enabled run mode (Run or Add to Queue).

Use helper:

job = start_run_and_wait(app, use_run_now=True)


Assertions:

assert job.run_mode == "queue"
assert job.prompt_source == "pack"
assert job.prompt_pack_id == "your-pack-id"

plan = get_stage_plan_for_job(app, job)
assert plan is not None
assert plan.has_generation_stage()


If images/outputs are available via job.meta, basic smoke check that something was produced.

JT06 doesn’t need to be fully fleshed out in this PR; the important part is the helper usage and verifying the correlation between prompt pack and job.

6. How This Answers Codex’s PR-101 Question

You can summarize to Codex:

There is no existing shared journey helper; this PR explicitly introduces tests/journeys/journey_helpers_v2.py.

That helper encapsulates:

Starting a run via AppController.start_run_v2 / on_run_job_now_v2 / on_add_job_to_queue_v2.

Waiting for completion using JobService/JobHistory.

Fetching the StageExecutionPlan from the pipeline layer.

JT03/04/05/06 must be refactored to call only these helpers and assert:

job.run_mode (direct vs queue),

job.source (run, run_now, add_to_queue),

Stage ordering in the plan.

This gives Codex exactly the “known API” it needs to safely update the journeys.

7. Validation & Acceptance Criteria

Commands:

pytest tests/journeys/test_jt03_*.py
pytest tests/journeys/test_jt04_*.py
pytest tests/journeys/test_jt05_*.py
pytest tests/journeys/test_jt06_*.py
pytest tests/journeys


Acceptance:

 tests/journeys/journey_helpers_v2.py exists and provides:

start_run_and_wait(app, use_run_now=False, add_to_queue_only=False, timeout_seconds=...)

get_latest_job(app)

get_stage_plan_for_job(app, job)

 JT03/04/05 no longer poke directly at controllers/runners; they use the helpers.

 JT03 asserts a simple txt2img journey with correct run_mode and stage order.

 JT04 asserts img2img + ADetailer ordering, run_mode, and job presence.

 JT05 asserts upscale journey with queue (or chosen) run_mode and the presence of UPSCALE stage.

 JT06 exists as a basic prompt-pack + queue journey that uses helpers and checks prompt_source == "pack".

 All journey tests pass end-to-end, giving you a stable harness for future pipeline/GUI changes.