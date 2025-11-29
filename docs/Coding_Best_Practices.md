# Coding Best Practices

## 1. Comments & Timestamps
Avoid timestamps in code; use Git. Comment intent, not history.

## 2. Logging Strategy
Log boundaries, state transitions, failures, and long operations. Avoid excessive logging.

## 3. Code Organization & Style
Use consistent formatting, small functions, clear naming, avoid global state, use type hints.

## 4. Version Control & PR Hygiene
One PR = one change. Descriptive commits. Review diffs. Never break main.

## 5. Testing Best Practices
Unit tests, integration tests, contract tests, regression tests, maintain fast subset.

## 6. Documentation & Comments
Use module docstrings, focused function docstrings, architecture docs. Comment why, not what.

## 7. Observability
Use metrics, tracing, and feature flags.

## 8. AI Safety Practices
Provide exact files, forbid core files, enforce minimal diffs, review AI-generated code carefully.

## 9. Performance
Avoid inefficient patterns, use caching appropriately, clean up resources.

## 10. Universal Checklist
Ensure change is scoped, clear, tested, logged, and understandable to future developers.
