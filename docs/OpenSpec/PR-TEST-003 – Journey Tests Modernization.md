# PR-TEST-003 — Journey Tests Modernization

**Status**: 🔄 PARTIAL IMPLEMENTATION  
**Date**: 2025-12-21  
**Category**: Test Suite Modernization  
**Related**: PR-TEST-001, PR-TEST-002, PR-TEST-004

---

## Purpose

Modernize journey tests (JT-01 through JT-06) to use the canonical NJR execution path instead of mocking at the API layer, enabling real pipeline logic execution while still avoiding WebUI dependencies.

---

## Problem Statement

Current journey tests mock at the **wrong layer**:
- ❌ Mock `ApiClient.generate_images()` — bypasses executor, stage logic, runner state machine
- ❌ Use full GUI/AppController setup — adds unnecessary complexity
- ❌ Don't invoke actual `run_njr()` execution — can't catch pipeline bugs

This violates the v2.6 principle: **Test the real canonical path**.

---

## Solution: Modern NJR Journey Pattern

**New Pattern** (PR-TEST-003):
```python
# PromptPack → Builder → NJR → Queue → Runner → History
# Mock ONLY: requests.Session.request (HTTP transport layer)

njr = make_test_njr(...)  # Create test NJR
api_client = SDWebUIClient(base_url="...")

with patch.object(api_client._session, 'request') as mock_request:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {...}
    mock_request.return_value = mock_response
    
    entry = run_njr_journey(njr, api_client)  # NEW HELPER
    assert entry.status == JobStatus.COMPLETED
```

**Old Pattern** (DEPRECATED):
```python
with patch("src.api.client.ApiClient.generate_images") as mock_generate:
    mock_generate.return_value = mock_response
    job_entry = start_run_and_wait(controller)  # Bypasses executor logic
```

---

## Implementation Summary

### Step 1: Create `run_njr_journey()` Helper ✅

**File**: [tests/journeys/journey_helpers_v2.py](tests/journeys/journey_helpers_v2.py)

**Added**:
```python
def run_njr_journey(
    njr: NormalizedJobRecord,
    api_client: SDWebUIClient,
    *,
    timeout_seconds: float = 30.0,
    mock_http_response: dict | None = None,
) -> JobHistoryEntry:
    """Execute NJR through canonical runner path with mocked HTTP transport.
    
    This is the MODERN journey test pattern (PR-TEST-003). It executes the full
    pipeline stack (run_njr → executor → stages) while mocking only at the HTTP
    transport layer to avoid real WebUI dependencies.
    """
```

**Benefits**:
- ✅ Executes real `PipelineRunner.run_njr()` logic
- ✅ Invokes actual executor stages (txt2img, refiner, hires, adetailer)
- ✅ Tests stage sequencing, state machine, error handling
- ✅ Mocks only HTTP transport (deepest safe mock point)

---

### Step 2: Create Reference Implementation ✅

**File**: [tests/journeys/test_njr_modern_pattern.py](tests/journeys/test_njr_modern_pattern.py)

**Purpose**: Demonstrates the modern journey test pattern for new tests.

**Example Test**:
```python
@pytest.mark.journey
def test_njr_txt2img_canonical_path():
    """Test txt2img execution through full NJR canonical path."""
    
    njr = make_test_njr(
        positive_prompt="A beautiful sunset",
        base_model="sdxl",
        config={"sampler": "Euler", "steps": 20, ...},
    )
    
    api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")
    
    with patch.object(api_client._session, 'request') as mock_request:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "images": ["data:image/png;base64,..."],
            "parameters": {...}
        }
        mock_request.return_value = mock_response
        
        entry = run_njr_journey(njr, api_client)
        
        assert entry.status == JobStatus.COMPLETED
        assert mock_request.called  # HTTP was invoked
```

---

### Step 3: Refactor Journey Tests 🔄 IN PROGRESS

**Files to Update**:
1. ❌ [test_jt01_prompt_pack_authoring.py](tests/journeys/test_jt01_prompt_pack_authoring.py) — No execution, just pack authoring
2. 🔄 [test_jt02_lora_embedding_integration.py](tests/journeys/test_jt02_lora_embedding_integration.py) — NEEDS UPDATE
3. 🔄 [test_jt03_txt2img_pipeline_run.py](tests/journeys/test_jt03_txt2img_pipeline_run.py) — NEEDS UPDATE
4. 🔄 [test_jt04_img2img_adetailer_run.py](tests/journeys/test_jt04_img2img_adetailer_run.py) — NEEDS UPDATE
5. 🔄 [test_jt05_upscale_stage_run.py](tests/journeys/test_jt05_upscale_stage_run.py) — NEEDS UPDATE
6. 🔄 [test_jt06_prompt_pack_queue_run.py](tests/journeys/test_jt06_prompt_pack_queue_run.py) — NEEDS UPDATE

**Migration Steps for Each Test**:
1. Replace `with patch("src.api.client.ApiClient.generate_images")` 
   → `with patch.object(api_client._session, 'request')`
2. Replace `start_run_and_wait(controller)` 
   → `run_njr_journey(njr, api_client)`
3. Remove unnecessary GUI/AppController dependencies
4. Update mock responses to HTTP layer format

---

### Step 4: Map Journey Tests to Golden Path Scenarios ✅

| Journey Test | GP Scenario | Description |
|--------------|-------------|-------------|
| JT-01 | N/A | Pack authoring only (no execution) |
| JT-02 | GP4 | LoRA/embedding integration |
| JT-03 | GP1 | Simple txt2img run |
| JT-04 | GP5 | img2img with ADetailer |
| JT-05 | GP6 | Multi-stage (txt2img → upscale) |
| JT-06 | GP2 | Queue-only run (multiple jobs) |

**Action**: Future PR-TEST-004 will implement GP1-GP15 tests that supersede journey tests for canonical coverage.

---

## Test Coverage Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Journey tests mocking at API layer | 4 | 0 (after refactor) | -4 ✅ |
| Journey tests mocking at HTTP layer | 0 | 4+ (after refactor) | +4 ✅ |
| Journey tests invoking real `run_njr()` | 0 | 4+ (after refactor) | +4 ✅ |
| Modern pattern examples | 0 | 1 | +1 ✅ |

---

## Architectural Benefits

1. **Real Pipeline Logic Execution**: Tests now validate actual executor stages, state machine, error handling
2. **Deeper Coverage**: HTTP-layer mocking allows testing of payload construction, stage sequencing, result handling
3. **Bug Detection**: Can catch executor bugs, stage transition errors, config propagation issues
4. **Canonical Path Validation**: Tests match production execution path exactly
5. **Reduced GUI Dependencies**: Journey tests can run without full Tkinter setup

---

## Mock Layer Comparison

| Layer | What It Tests | What It Skips | Verdict |
|-------|---------------|---------------|---------|
| `generate_images()` (OLD) | GUI → Controller → Config | Executor, stages, runner | ❌ Too high |
| `_session.request()` (NEW) | Full pipeline except HTTP | Only network I/O | ✅ Optimal |
| No mocking | Everything | Nothing | ❌ Requires WebUI |

---

## Migration Guide

### Before (Old Pattern):
```python
with patch("src.api.client.ApiClient.generate_images") as mock_generate:
    mock_response = Mock()
    mock_response.success = True
    mock_response.images = [Mock(), Mock()]
    mock_generate.return_value = mock_response
    
    job_entry = start_run_and_wait(controller, use_run_now=False)
```

### After (New Pattern):
```python
njr = make_test_njr(positive_prompt="...", base_model="sdxl", config={...})
api_client = SDWebUIClient(base_url="http://127.0.0.1:7860")

with patch.object(api_client._session, 'request') as mock_request:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "images": ["data:image/png;base64,..."],
        "parameters": {...}
    }
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response
    
    entry = run_njr_journey(njr, api_client)
```

---

## Next Steps

### Immediate (Complete PR-TEST-003):
1. 🔲 Refactor `test_jt02` to use `run_njr_journey()`
2. 🔲 Refactor `test_jt03` to use `run_njr_journey()`
3. 🔲 Refactor `test_jt04` to use `run_njr_journey()`
4. 🔲 Refactor `test_jt05` to use `run_njr_journey()`
5. 🔲 Refactor `test_jt06` to use `run_njr_journey()`
6. 🔲 Verify all journey tests pass with new pattern

### Future (PR-TEST-004):
- Implement GP1-GP15 tests using modern NJR pattern
- Create PromptPack fixtures for repeatable test scenarios
- Add compat fixtures for version migration testing

---

## Related Work

- **PR-TEST-001**: Controller Archive Cleanup (completed)
- **PR-TEST-002**: Legacy Archive Import Purge (completed)
- **PR-TEST-004**: Golden Path & Compat Fixtures (next)

---

## Lessons Learned

1. **Mock at the deepest safe point**: HTTP transport layer is the optimal mock point — deep enough to test logic, shallow enough to avoid WebUI dependency.
2. **Helper functions improve consistency**: `run_njr_journey()` standardizes the pattern across all journey tests.
3. **Reference implementations matter**: `test_njr_modern_pattern.py` serves as a living example for contributors.
4. **Incremental migration is safer**: Refactoring journey tests one-by-one allows validation at each step.

---

## Status

- ✅ Created `run_njr_journey()` helper
- ✅ Created reference implementation (`test_njr_modern_pattern.py`)
- ✅ Documented journey-to-GP mapping
- 🔄 Journey test refactoring in progress (5 tests remaining)
- 🔲 Full PR-TEST-003 completion pending individual test migration

**Recommendation**: Complete journey test refactoring in follow-up commits or defer to PR-TEST-004 if Golden Path tests provide equivalent coverage.
