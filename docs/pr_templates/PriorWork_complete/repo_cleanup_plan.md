# StableNew Repository Cleanup Plan (MajorRefactor)

## Goals

- Consolidate and modernize documentation.
- Reduce clutter at the repo root.
- Make it clear which docs are authoritative.
- Prepare the repo for multi-agent, multi-PR workflows.

## 1. Documentation Consolidation

### Actions

- Use `docs/` as the canonical home for documentation.
- Ensure:
  - `docs/engineering_standards.md` captures coding rules.
  - `docs/testing_strategy.md` captures testing rules.
  - `docs/gui_overview.md` captures GUI layout and UX rules.
- Move older root docs into `docs/legacy/`:
  - `ARCHITECTURE.md`
  - `AUDIT_REPORT_S3_S4_READINESS.md`
  - `GUI_ENHANCEMENTS.md`
  - `ISSUE_ANALYSIS.md`
  - `OPEN_ISSUES_RECOMMENDATIONS.md`
- Update `README.md` to:
  - Point to `docs/` as the canonical docs location.
  - Add an AI-agent note pointing to the standards docs.

## 2. Root-Level File Cleanup

Target root-level debug or exploratory scripts such as:

- `_tmp_check.py`
- `temp_ppp_test.py`
- `temp_ppp_test2.py`
- `temp_tk_test.py`
- `simple_debug.py`
- `debug_batch.py`
- `test_advanced_features.py`
- `test_gui_enhancements.py`

Actions:

- Move debug scripts to `archive/root_experiments/`.
- Move root-level test files into `tests/legacy/` (if still useful) or `archive/root_experiments/` (if fully superseded).

## 3. Tests Reorganization

Suggested structure:

- `tests/unit/`
- `tests/gui/`
- `tests/integration/`
- `tests/journey/`

Actions:

- Move GUI-focused tests to `tests/gui/`.
- Move pipeline integration tests to `tests/integration/`.
- Put new full-journey GUI tests in `tests/journey/`.
- Preserve test names where possible, adjusting imports as necessary.

## 4. CODEOWNERS and Responsibility

Add `.github/CODEOWNERS` to express ownership:

- `src/gui/*` → GUI specialist
- `tests/**` → test specialist
- `docs/**` → docs specialist
- Fallback: `@destroyer42` as overall owner

## 5. Process

- Start with a dry-run using a reorg helper script (e.g., `scripts/reorg_repo.py`).
- Confirm all moves with `git status`.
- Run the full test suite.
- Then commit and open a PR titled:

> Repo Cleanup: Docs Consolidation & Root File Reorg

This PR should not change behavior—only file locations, imports, and documentation references.
