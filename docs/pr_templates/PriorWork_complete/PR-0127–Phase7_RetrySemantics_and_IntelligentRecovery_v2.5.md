# PR-0127 — Phase 7: Retry Semantics & Intelligent Recovery (V2.5)

## 1. Summary

- Introduces `RetryPolicy` syntax for stage-aware retry defaults and exposes `apply_retry_policy`/`retry_callback` on `SDWebUIClient`.
- Logs every failed attempt with `LogContext`, records retries inside `JobExecutionMetadata`, and surfaces retry history via `UnifiedErrorEnvelope.retry_info`.
- Keeps core pipeline semantics unchanged: transient WebUI/network hiccups are retried before failing, permanent failures still bubble up with structured envelopes.

## 2. Context

- WebUI requests currently all fail fast. Some stages (txt2img, img2img, upscale) are sensitive to transient timeouts or 500/503 responses, which abort entire jobs and appear indistinguishable from permanent failures.
- Phase 6 introduced structured error envelopes, but they lacked retry history. Phase 7 makes retries first-class citizens and records each attempt so diagnostics and crash bundles can show exactly how many tries were made and why.

## 3. Scope

### In Scope
- `src/utils/retry_policy_v2.py` — `RetryPolicy`, stage constants, and helper map.
- `src/api/client.py` — `SDWebUIClient` now accepts `retry_callback`, logs every retry, calls optional callback, and honors stage-based policy defaults for txt2img/img2img/upscale.
- `src/controller/job_service.py`/`src/queue/job_model.py`/`src/queue/single_node_runner.py` — capture retry attempts, store them on `JobExecutionMetadata`, expose them on dashboards, and append them to `UnifiedErrorEnvelope.retry_info`.
- `src/controller/pipeline_controller.py` — pass a retry callback to the WebUI client so JobService metadata stays in sync.
- Tests: `tests/api/test_webui_retry_policy_v2.py`, `tests/controller/test_job_retry_metadata_v2.py`.

### Out of Scope
- No changes to `executor.py`, `pipeline_runner.py`, or existing pipeline sequencing. Retry behavior is confined to API client, JobService metadata, and diagnostics surfaces.

## 4. Testing

- `tests/api/test_webui_retry_policy_v2.py` fakes transient failures and verifies stage policies plus callback invocation.
- `tests/controller/test_job_retry_metadata_v2.py` uses a stubbed JobService/runner to ensure retry metadata is recorded and serialized into the error envelope.
- Existing regression suites should continue to pass; no new heavy runner tests required.

## 5. Documentation

- Update `docs/StableNew_Coding_and_Testing_v2.5.md` with a Phase 7 subsection describing retry policy usage and diagnostics.
- Add PR entry to `CHANGELOG.md`.

## 6. Rollout Strategy

- Merge as a low-risk Phase 7 PR once tests pass.
- Retries default to the newly defined policies but can be overridden through direct SDWebUIClient calls (`policy` argument or `apply_retry_policy`).
- Crash bundles and diagnostics dashboards now include retry history automatically.
