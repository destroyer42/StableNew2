# CODING_STANDARDS

---

## 1. Python Style

- Follow **PEP 8**.
- Use **type hints** for new public functions and classes.
- Prefer `dataclasses` for structured configurations and records.
- Use f-strings for string interpolation.

---

## 2. Logging

- Use the `logging` module, never `print` in production code.
- Logger per-module: `logger = logging.getLogger(__name__)`.
- Log levels:
  - `debug` for internal details.
  - `info` for high-level lifecycle events.
  - `warning` for recoverable issues.
  - `error` for failures.

---

## 3. Error Handling

- Raise specific exceptions where helpful; avoid silent failures.
- Propagate exceptions to controllers, which convert them to user-facing messages.

---

## 4. Testing

- All new logic should include tests in `tests/...`:
  - Unit tests for pure logic.
  - Integration tests where external resources are touched.
- Use pytest-style tests with clear names:
  - `test_what_is_being_verified`.

---

## 5. Imports / Dependencies

- Relative imports inside `src/`:
  - `from src.pipeline.pipeline_runner import PipelineRunner`
- No side-effect imports (no heavy work at module import time).
