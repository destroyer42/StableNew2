---
applyTo: "tests/**/*.py"
---

# Tests Instructions

- Prefer deterministic pytest tests.
- Match the current `tests/` domain layout.
- No real network calls, no real WebUI dependency, and no flaky sleeps.
- Keep GUI tests headless-safe and non-blocking.
- Remove or rewrite tests that defend retired legacy paths when the approved scope removes them.
