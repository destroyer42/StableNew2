PR-113 – End-to-End Smoke Tests.md

Risk Tier: Medium (Tier 2 – integration tests)
Baseline: After PR-103, 107, 108, 109, 112
Goal: “Pull the fire alarm”: prove that a minimal pipeline run works end-to-end, for both DIRECT and QUEUE flows, using a stubbed WebUI client in CI.

1. Intent

Create a single integration test suite that:

Boots the application components enough to:

Trigger a run from the controller surface (not full Tk).

Execute a tiny SDXL pipeline via stub runner/API.

Record a job in history.

Verifies:

DIRECT “Run Now” run completes and writes a JobRecord + stub images.

QUEUE “Run”/“Add to Queue” run is enqueued, processed by a runner, and recorded similarly.

No real WebUI/HTTP, no real GPU — just stub all external services.

2. Scope

Files

tests/integration/test_end_to_end_pipeline_v2.py (new)

Out-of-Scope

Real WebUI server.

Performance benchmarks, batch throughput.

Cluster/multi-node execution.

3. Test Harness Design

File: tests/integration/test_end_to_end_pipeline_v2.py

Use stubs for:

ApiClient (no network; returns fake “images”).

SingleNodeJobRunner or equivalent.

JobService (configured to use the stub runner and a real JobHistoryStore).

3.1 Stub ApiClient
class StubApiClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_images(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        # Minimal meta: pretend we generated one image per call
        return {
            "images": [f"image_for_{payload.get('prompt', 'unknown')}"],
            "meta": {"ok": True},
        }


Inject this into whatever executor/pipeline runner you use in tests (constructor argument or monkeypatch).

3.2 In-memory JobService + SingleNode runner

If your code already has abstractions, create a test configuration that:

Uses a background thread or synchronous loop for SingleNodeJobRunner that processes jobs from an in-memory queue.

For DIRECT runs, either:

Call the runner directly (synchronous), or

Go through the same JobService but wait for completion.

For QUEUE runs, always go through JobService + runner.

For tests, you can keep it simple:

Start runner in the same thread, blocking until queue is empty (no real concurrency required for smoke tests).

4. Test Scenarios
4.1 Scenario 1 – DIRECT run via “Run Now”

Test name: test_direct_run_now_end_to_end

Steps:

Build a minimal app/controller stack:

AppStateV2 with tiny SDXL config (e.g., 256x256, 5 steps).

AppController wired to V2 pipeline/JobService.

JobHistoryStore instance hooked to JobService.

Use the same entrypoint the GUI uses:

app_controller.on_run_job_now_v2()


Wait for completion:

Poll job_history.latest_job() until completed_at set, with a timeout.

Assertions:

A JobRecord exists:

job = history.latest_job()
assert job is not None
assert job.run_mode == "direct"
assert job.source == "run_now"


StubApiClient was called at least once:

assert len(api_client.calls) >= 1


The last call’s payload is small (e.g., steps=5, width/height=256):

payload = api_client.calls[-1]
assert payload["steps"] == 5
assert payload["width"] == 256
assert payload["height"] == 256


job.meta (or equivalent) shows some output (e.g., path or stub image info).

4.2 Scenario 2 – QUEUE run via “Run” or “Add to Queue”

Test name: test_queue_run_end_to_end

Steps:

Setup similar to Scenario 1, but configure:

job_draft.pack_id = "pack-123" (so we exercise pack-based flows).

Pipeline config that enables at least txt2img + upscale.

Trigger queue-style run:

app_controller.start_run_v2()      # if this is QUEUE-mode in your design
# or:
app_controller.on_add_job_to_queue_v2()


Let JobService enqueue job and SingleNodeJobRunner process it. For the test, you can:

Call a job_runner.run_pending() loop that processes jobs synchronously.

Wait for completion as before.

Assertions:

JobRecord exists and has queue metadata:

job = history.latest_job()
assert job.run_mode == "queue"
assert job.prompt_source in ("pack", "manual")  # pack if configured
if job.prompt_source == "pack":
    assert job.prompt_pack_id == "pack-123"


StubApiClient received calls for all the stages in the plan (txt2img, maybe upscale, maybe ADetailer):

prompts = [p.get("prompt") for p in api_client.calls]
assert any("image_for" in str(x) for x in prompts)  # simple smoke check


JobHistory fields (stage_count, has_upscale/has_adetailer) match expectations.

5. Validation & Acceptance

Commands:

pytest tests/integration/test_end_to_end_pipeline_v2.py
pytest tests/integration


Acceptance:

 There is a single integration test module (tests/integration/test_end_to_end_pipeline_v2.py) that:

Builds a minimal, stubbed stack (ApiClient, JobService, SingleNodeJobRunner, AppController, JobHistoryStore).

Does not depend on a real WebUI or GPU.

 Scenario 1:

“Run Now” triggers a DIRECT run end-to-end.

StubApiClient sees at least one SDXL payload with small resolution and steps.

JobHistory shows run_mode="direct", source="run_now", non-null completed_at.

 Scenario 2:

“Run”/“Add to Queue” triggers a QUEUE run end-to-end.

SingleNodeJobRunner processes the job from the queue.

JobHistory shows run_mode="queue" and correct prompt-origin fields.

 The integration tests pass in CI and can be treated as the final Phase 1 “does this whole thing actually run?” gate.