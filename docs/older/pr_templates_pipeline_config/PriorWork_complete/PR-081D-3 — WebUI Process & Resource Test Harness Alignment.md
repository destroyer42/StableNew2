PR-081D-3 — WebUI Process & Resource Test Harness Alignment

Intent
Fix the failing WebUI process-manager and resource-discovery tests by updating the test harness (DummyProcess and resource expectations) to match the current WebUI V2 startup and resource-mapping contracts.
No functional changes to the real WebUI process manager or WebUI resource manager unless technically unavoidable.
This is a tests + stubs only PR.

Summary of Failures Addressed
❌ Errors from test_webui_process_manager.py

Tests expect process stubs to behave like subprocess.Popen, but our DummyProcess does not provide:

.pid

.poll()

.terminate()

.wait()

Resulting in:

WebUIStartupError: '_DummyProcess' object has no attribute 'pid'

❌ Errors from test_webui_resources.py::test_filesystem_fallback

The test expects a legacy resources map, but the real system now includes additional keys:

Refiner models

ADetailer models/detectors

New SDXL resource families

Updated VAE/model folder structure

The test hard-codes outdated expectations, producing:

assert False

Scope & Risk

Risk Level: Low
Subsystems: Test harness only
Changes Allowed: Tests & test stubs
Changes Forbidden: Any functional change to:

src/api/webui_process_manager.py

src/api/webui_resources.py

src/api/client.py

(Unless a tiny shim is absolutely required for patch safety.)

Files Allowed to Modify
tests/api/test_webui_process_manager.py
tests/api/test_webui_resources.py
tests/conftest.py (Test DummyProcess & stubs)
tests/test_fixtures/* (if DummyProcess moved there)

Forbidden Files
src/api/webui_process_manager.py
src/api/webui_resources.py
src/api/webui_api.py
src/main.py
src/controller/*
src/gui/*
src/pipeline/*

Implementation Plan
1. Fix DummyProcess in tests to mirror subprocess.Popen

The tests stub the WebUI process using _DummyProcess, but this must include:

class DummyProcess:
    def __init__(self):
        self.pid = 12345
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def wait(self, timeout=None):
        return self._returncode


Make this change ONLY in the test stub.

2. Adjust process-manager tests to pass realistic configuration

Ensure tests include any required startup args now expected by:

WebUIProcessManager.start_webui()

Environment variable injection

Working directory expectations

If real process manager now reads more fields, tests must provide them.

3. Update test_filesystem_fallback to match the new unified resources map

The current resource manager returns keys such as:

"models"

"vaes"

"refiner_models"

"adetailer_models"

"adetailer_detectors"

"samplers"

"schedulers"

Tests must reflect the real contract, not the V1-era 3-key contract.

Implement minimal updates:

assert "models" in resources
assert isinstance(resources["models"], list)
assert "adetailer_models" in resources
assert "refiner_models" in resources


Rather than hard-coded equality.

4. Confirm resource-loader behavior under filesystem fallback

Tests should check:

Filesystem fallback returns non-empty default values when WebUI API is unavailable

Future-proof expectations (non-strict dict equality)

5. No change to production code unless required

If a test reveals a missing attribute that must exist for the API to be internally consistent, add a 1–2 line shim, but do not alter overall logic.

Acceptance Criteria
✔ test_start_invokes_subprocess_with_config passes

DummyProcess presents .pid and other required methods.

✔ test_stop_handles_already_exited_process passes

Process stub returns a valid poll/returncode.

✔ test_filesystem_fallback passes

Resource map matches current contract.

✔ No changes to production WebUI logic

Except minimal guard rails if absolutely required for consistency.

✔ All API tests pass cleanly with no warnings

Particularly no more:

'_DummyProcess' has no attribute 'pid'
assert False

Validation Checklist

Only test harness updated

Full compatibility with modern WebUI resource mapper

No forbidden files modified

App boots unaffected

Test expectations adjusted to the V2 resource schema

DummyProcess fully Popen-compatible

🚀 Deliverables

Updated DummyProcess

Updated resource-map expectations

Updated WebUI process tests

No failures in tests/api/*