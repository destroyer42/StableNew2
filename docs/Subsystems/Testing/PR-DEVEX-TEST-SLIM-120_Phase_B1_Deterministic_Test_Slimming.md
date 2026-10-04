# PR-DEVEX-TEST-SLIM-120 - Phase B1 deterministic test slimming

Result class: **TEST HERMETICITY + ONE PRODUCTION TEST-ACCOMMODATION REMOVAL + ONE EXPLICIT SERVICE MODE.** No test was
deleted, skipped, xfailed or weakened; no production retry/transport/ownership semantics changed. Execution profile: Standard
(Claude Code, Sonnet 5.5 High). Principle: make existing tests faster by removing accidental real-time/network/ambient-state
dependence, never by reducing behavioral coverage.

## Measured results (focused, current source, Windows workstation, Python 3.14)

Before = unmodified `origin/main` (`83fa2b2e`); after = this branch. "after" values below 0.01 s are hidden by pytest's
`--durations` floor.

| Target | Root cause | Before | After |
|---|---|---:|---:|
| `test_ensure_connected_timeout_sets_error` | `ensure_connected()` fell through to the real `find_webui_port()` loopback scan | 49.05 s | < 0.01 s |
| `test_filesystem_fallback` | `client=None` was replaced by a default `SDWebUIClient` (`client or SDWebUIClient()`), so "filesystem" discovery made real retrying API calls | 38.33 s | < 0.01 s |
| `test_check_api_ready_failure` | production retry backoff (`5 x 2.0 s`) paid in real time | 30.65 s | < 0.01 s |
| `test_client_closed_on_failure` | real `1+2+4+8+8` restart backoff | 23.00 s | < 0.01 s |
| `test_run_defaults_to_queue` / `test_run_now_defaults_to_queue` | `PYTEST_CURRENT_TEST` branch in production `start_run` built a real `ApiClient` and issued a generation request | 7.15 s + 7.13 s | 0.03 s + < 0.01 s |
| four ADetailer failure/fallback tests | retry backoff on the `/scripts` GET | ~3.5 s each (13.9 s) | < 0.01 s each |
| `test_webui_launch_emits_proc_log` | see "GUI process logging" | 2.78 s locally (10.4 s hosted) | 1.43 s, deterministic |
| Whole focused set (10 files, 82 tests) | | 185.1 s | 14.8 s (+ 10 new tests) |

Local full census on the final source SHA: **5,040 collected, 5,016 passed, 22 skipped, 2 failed, 1,002 s** (the CI-110
local census was 4,830 tests / 1,100 s). None of the targeted tests is in the slowest-30 any more; the operator-journey file
(~148 s, six tests) is now the dominant cost and is a Phase B3 matter. The hosted Python 3.14 CI census is the integration
verdict and was not run from this session. The two local failures are not caused by this change (see "Findings outside scope").

## What changed and the signal each test keeps

* **Connection controller (A).** The test fakes the exact dependency `ensure_connected()` imports (`src.api.healthcheck.find_webui_port`)
  with a recording fake; no production abstraction was added. It still proves: initial probe fails, managed start is attempted, retries
  fail, discovery finds nothing, state is `ERROR`, timing snapshot is coherent. A new test covers the alternate-endpoint success path
  (discovery finds another URL -> `READY`, base URL updated, `detected_url` recorded).
* **API client tests (B).** `SDWebUIClient._sleep` (the existing seam) is replaced in readiness and ADetailer resource tests. Backoff
  computation and attempt counts remain owned by `test_webui_retry_policy_v2.py`; generation-POST rules by
  `test_http_100_definite_http_fail_fast.py`. Neither was edited. Production client code is unchanged.
* **Restart failure (C).** The process-manager module's `time.sleep` is patched. The test still asserts six attempts, six closed
  temporary clients and a `False` result; a new spy test asserts the requested delays are exactly `1, 2, 4, 8, 8` (doubling to the
  cap, no wait after the last attempt).
* **Resource service (D).** `WebUIResourceService(client=...)` now distinguishes *omitted* from *explicit `None`* with the
  `DEFAULT_CLIENT` sentinel in `src/api/webui_resources.py`: omitted builds the default API-first `SDWebUIClient`; explicit `None`
  is filesystem-only and never creates or touches a client. The extended service in `webui_resource_service.py` shares the same
  contract (its `refresh_all()` returns filesystem lists plus API-only fallbacks - empty samplers, default schedulers - without
  touching a client). The only production caller, `AppController`, always holds a real client and keeps API-first behavior; its
  default (no client) path still builds the default client. Tests prove omitted vs explicit `None`, no client construction in
  filesystem mode, each of the five filesystem resource types, extended `refresh_all()` in both modes, and the AppController
  default/injected behavior.
* **Pytest-only generation hook (E).** `AppController._invoke_mock_generate_for_tests` and the `PYTEST_CURRENT_TEST` branch in
  `QueueRunSubmissionService.start_run` are removed (the only two references in the repository; no test relied on them). The
  Run/Run Now tests now inject a spy `PipelineController`, forbid `ApiClient.generate_images` and `requests.Session.request`, and
  assert queue normalization (including `direct` -> `queue`), the exact hand-off (`run_mode == "queue"`, source value), and that
  no transport occurs. `app_controller.py` shrank from 7,782 to 7,731 physical lines and its checked-in ceiling was lowered to
  7,731. Other `PYTEST_CURRENT_TEST` uses (workspace isolation, output routing, diagnostics) are untouched.
* **Forge canonical path (F).** The test's NJR config carried no negative prompt and no frozen global-prompt policy, so the executor's
  documented legacy fallback merged the *mutable global negative prompt* (presets/default text, resolved from the working directory)
  into the payload and the optimizer reordered/de-duplicated it ("lowres, blurry" stopped being a substring in an isolated working
  directory). The test now supplies the explicit negative prompt and an empty frozen policy via the production helper
  `apply_global_prompt_policy` (the pattern the Klein and D110 canonical tests already use) and asserts exact equality. Identity,
  single-POST, seed/sampler/scheduler/geometry assertions are unchanged. This is incidental test state, not a product decision.
* **GUI process logging (G).** Profiling showed two separate issues, both test-hermeticity: (1) `WebUIProcessManager.start()` calls the
  real `SingleInstanceLock.is_gui_running()` loopback connect (about 1 s on a closed Windows port; its result depends on whether a
  real StableNew GUI is running, and an earlier test in the same process can bind the lock, which makes the launch path run for
  real); (2) once the launch path runs, app teardown reaches `stop_webui()`, which polled its full 10 s graceful-exit window because the
  test's fake process never reported an exit after `terminate()` - this matches the hosted 10.4 s. The test now pins the GUI-running and
  WebUI-port probes and its fake process exits on `terminate()`/`kill()`. The asserted launch log is unchanged and the test now
  deterministically exercises the real launch path.

## Findings outside scope (not fixed here)

* `tests/test_api_client.py::test_generate_images_500_then_connection_loss_is_outcome_unknown_not_crash_recovery` **fails on
  unmodified `origin/main`**: it still expects a 500 generation response to be retried once before the connection loss, which
  the definite-HTTP fail-fast rule (PR-HTTP-100 and its predecessor) forbids; the POST is now made exactly once. Recommended repair
  (Phase B1.1, bounded): make the lost-response `ConnectionError` the first POST outcome and assert one call, keeping the
  "outcome unknown, not crash recovery" signal; the definite-500 half is already covered by `test_http_100_definite_http_fail_fast.py`.
* `tests/pipeline/test_pr_harden_009_r1a_txt2img_cancellation.py::test_canonical_txt2img_completes_once_when_not_cancelled` failed once
  in the 17-minute local census (a UI heartbeat-stall diagnostics bundle was written during it, i.e. the machine was loaded) and passed
  in three isolated reruns and with the neighbouring file. Treat as a load-sensitive wall-clock wait (Phase B1.1 candidate); not
  attributable to this change.
* `test_process_inspector_shortcut_logs` (about 2.4 s) and other GUI tests build a full app and still perform a short loopback
  readiness probe at startup; Phase B3 (GUI/E2E restructuring).
* Fake processes elsewhere that never report an exit may hide the same 10 s `stop_webui()` poll; a quick audit is a B1.1 candidate.
* Operator-journey GUI tests (~148 s) and historical `test_pr_*` / backend-matrix consolidation remain Phase B2/B3 per
  `PR-DEVEX-CI-110_Risk_Proportionate_CI.md`.

## Validation

`python tools/ci/run_pr_gate.py` passed on this source (completeness, controller ratchet, Ruff, mypy smoke, 5,038-test collection,
341-test required smoke). `tools/ci/validation_plan.py` classifies this change as a full census because
`tools/ci/controller_surface_baseline.json` is CI authority (expected: the ratchet ceiling was lowered).
