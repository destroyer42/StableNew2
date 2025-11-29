---
applyTo: "tests/**/*.py"
---

# Tests Folder Instructions

## Rules
- Tests must mirror the corresponding `src/` structure.
- Do not import archived legacy modules for new tests.
- Favor small, clear, deterministic tests.
- GUI tests should use provided patterns instead of inventing new frameworks.

## CI Alignment
- Ensure all tests pass with `pytest -q`.
- Avoid modifying GitHub Actions to “fix” failing tests.