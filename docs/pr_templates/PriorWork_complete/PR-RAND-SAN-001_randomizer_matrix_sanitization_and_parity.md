
# PR-RAND-SAN-001: Randomizer / Matrix Sanitization & Preview–Pipeline Parity

## 1. Title

**PR-RAND-SAN-001: Randomizer / Matrix Sanitization & Preview–Pipeline Parity**

---

## 2. Summary

This PR hardens the **Randomizer & matrix expansion layer** so that:

- All randomization / matrix logic is implemented as **pure functions** (no side effects).
- **Preview Prompt** and **Pipeline Prompt** are guaranteed to be **identical strings** for a given input + seed.
- All wildcard and matrix syntax is **fully expanded and sanitized** before the API call.
- No `[[matrix]]`, `__wildcard__`, or partial/randomizer tokens leak into the WebUI payload.
- Edge cases (malformed tokens, nested matrices, mixed wildcard/matrix syntax) are handled deterministically and tested.

This PR is intentionally scoped to **Randomizer / Sanitization only**. No GUI, controller, pipeline, API, or logger architectural behavior is changed.

Use this PR once the repo is at the state of the ZIP:

- `StableNew-MoreSafe-11-20-2025-07-27-00-AftrerPR-PIPE-CORE01.zip`

And with the project docs:

- `docs/ARCHITECTURE_v2_Translation_Plan.md`
- `docs/StableNew_Roadmap_v1.0.md`
- `docs/Known_Bugs_And_Issues_Summary.md`
- `docs/AGENTS_AND_AI_WORKFLOW.md`

---

## 3. Problem Statement

### 3.1 Symptoms & Risks

Historically, the Randomizer / matrix system has shown issues like:

- **Mismatch** between **Preview Prompt** (what the user sees) and the **actual pipeline prompt** (what we send to WebUI).
- **Residual tokens** leaking into the payload:
  - `[[matrix_entries]]`
  - `__wildcard__` markers
  - Partially expanded `{a|b|c}` sets
- Non-pure behavior where calling the randomizer twice with the same inputs does **not** always yield the same result (because of hidden state, global RNG usage, or side effects).
- Inconsistent treatment of nested matrices, wildcard combinations, and mixed syntax, especially under different seeds.

These problems undermine:

- Predictability of renders.
- Ability to reason about manifests and logs.
- Future work around PromptPack UX and advanced combinatorics.

### 3.2 Architecture v2 Requirements

Architecture v2 mandates that:

- **Randomizer layer** is composed of **pure functions only**.
- **Wildcard logic** and **matrix logic** are separated from the pipeline and GUI.
- **Prompt sanitization is mandatory before API call**.
- Preview and pipeline behaviors must be **identical** for any given run (same seed, same config).

Currently, these guarantees are not fully encoded in tests or enforced by invariants.

### 3.3 Why This PR Exists

Before we build any additional PromptPack / Randomizer GUI features or AI-assisted prompt transformations, we must:

1. Lock down **parity** between preview and pipeline prompts.
2. Guarantee **sanitized, stable prompts** with no randomizer tokens leaking through.
3. Ensure all randomizer logic is **testable, deterministic, and self-contained**.

This PR provides that foundation via tests + minimal refactors to the randomizer utilities.

---

## 4. Goals

1. **Preview–Pipeline Parity**
   - For a given input prompt, randomizer configuration, and seed, the Preview Prompt and Pipeline Prompt must be **bit-for-bit identical**.
2. **Full Sanitization**
   - No randomizer syntax (`[[matrix]]`, `__wildcard__`, `{a|b|c}` expansions, etc.) appears in the final payload sent to WebUI.
3. **Pure Functions**
   - Randomizer functions behave as pure functions:
     - No dependence on global mutable state.
     - No side effects (no file IO, no GUI access, no network).
4. **Determinism with Seed**
   - Given the same input, configuration, and seed:
     - Matrix expansion and wildcard choices are deterministic.
5. **Robust Error Handling**
   - Malformed randomizer syntax results in **clear, typed errors** surfaced to the caller (not mysterious failures buried deep in the pipeline).

---

## 5. Non-goals

- No GUI changes (no new controls, no visual changes).
- No controller changes (no lifecycle logic modifications).
- No pipeline-stage changes (txt2img, img2img, upscale, etc. remain untouched).
- No new PromptPack features or UX flows.
- No changes to WebUI API interaction patterns or manifest schemas.
- No new randomization features beyond what’s necessary to enforce purity, parity, and sanitization.

---

## 6. Allowed Files

Codex may modify **only** the following files (or their closest equivalents if names differ slightly; if they do, ask for clarification):

**Randomizer / Sanitization Core**

- `src/utils/randomizer.py`
- `src/utils/matrix_parser.py` (if present)
- `src/utils/prompt_sanitizer.py` or `src/utils/sanitizer.py` (if present)
- Any small helper module under `src/utils/` that is clearly and exclusively used by the randomizer/matrix system (must be confirmed in the code before editing).

**Tests**

- `tests/utils/test_randomizer.py` (if exists)
- `tests/utils/test_randomizer_matrix.py` (if exists)
- New tests:
  - `tests/utils/test_randomizer_parity.py`
  - `tests/utils/test_randomizer_sanitization.py`

**Docs**

- `docs/codex/prs/PR-RAND-SAN-001_randomizer_matrix_sanitization_and_parity.md` (this file)
- Optionally: add a short note to `docs/Known_Bugs_And_Issues_Summary.md` indicating that randomizer/matrix parity & sanitization are now covered by tests.

---

## 7. Forbidden Files

Do **not** modify any of the following in this PR:

- GUI layer:
  - `src/gui/*`
- Controller layer:
  - `src/controller/*`
- Pipeline layer:
  - `src/pipeline/*`
- API layer:
  - `src/api/*`
- Logger / manifest:
  - `src/utils/structured_logger.py` or equivalents.
- Tools / scripts / CI configuration:
  - `tools/*`, `.github/*`, `scripts/*`, etc.

If you think a change is required in these areas to fix a test or behavior, **stop and request a separate PR**.

---

## 8. Step-by-step Implementation

> **Important:** Follow TDD. Write failing tests first, then make the minimal code changes to satisfy them.

### 8.1 Test Design – Preview/Pipeline Parity

1. Create `tests/utils/test_randomizer_parity.py`.

   Add tests that assume there are two primary callers to the randomizer layer (names may vary; inspect existing code):
   - One used for **Preview Prompt**.
   - One used for **Pipeline Prompt** generation.

   Tests should:

   - Provide a sample input prompt containing combinations of:
     - Wildcards (e.g., `__hair_color__`).
     - Matrices (e.g., `[[knight,wizard,ranger]]`).
     - Mixed `{a|b|c}` syntax, if used in this codebase.

   - Set a fixed seed and/or deterministic configuration.

   - Assert that:
     - Preview Prompt string == Pipeline Prompt string (exact match).
     - No randomizer tokens remain in either string.

   Example (pseudocode-ish expectations):

   - `test_preview_and_pipeline_prompts_match_exactly_for_simple_matrix`
   - `test_preview_and_pipeline_prompts_match_with_wildcards_and_matrices`
   - `test_no_randomizer_tokens_remain_in_final_prompt`

### 8.2 Test Design – Sanitization & Token Removal

2. Create `tests/utils/test_randomizer_sanitization.py`.

   Add tests that focus on internal randomizer/matrix/sanitizer functions (direct unit tests):

   - `test_matrix_tokens_removed_after_expansion`
   - `test_wildcards_removed_after_expansion`
   - `test_no_unmatched_matrix_brackets_remain`
   - `test_no_unmatched_wildcard_markers_remain`
   - `test_malformed_matrix_raises_clear_error`
   - `test_malformed_wildcard_raises_clear_error`

   Use both valid and invalid inputs to assert that:

   - Valid inputs produce fully sanitized strings (no randomizer syntax).
   - Invalid inputs raise a typed error such as `RandomizerError` or `MatrixSyntaxError` (if not present, introduce a small custom exception type in the randomizer module).

### 8.3 Test Design – Purity & Determinism

3. In `tests/utils/test_randomizer_parity.py` (or a separate test module), add tests that enforce purity & determinism:

   - `test_randomizer_output_deterministic_for_given_seed`
   - `test_randomizer_functions_do_not_mutate_input_data`
   - `test_multiple_calls_with_same_seed_and_input_produce_identical_output`

   Approach:

   - Provide an input prompt and config, set a seed (explicitly or via a seed parameter).
   - Call the randomizer function multiple times with the same inputs.
   - Assert the outputs are identical.
   - Also assert that the input objects (dicts/lists) have not been mutated.

### 8.4 Implementation – Randomizer Core Cleanup

4. In `src/utils/randomizer.py` (and any related helpers such as `matrix_parser.py`):

   - Identify any global RNG/state usage and refactor to use:
     - A passed-in RNG object, or
     - A seed-driven local RNG instance (e.g., `random.Random(seed)`), or
     - Parameterized functions that avoid global random state.
   - Ensure all public randomizer functions are **pure** with respect to their inputs + seed.

5. Implement (or clean up) a **single canonical “sanitize_prompt” function** that:

   - Receives a prompt template + config (including seed).
   - Expands all:
     - Matrices.
     - Wildcards.
     - Optional syntax (`{a|b|c}`) if used.
   - Returns a fully expanded, sanitized string with **no randomizer syntax left**.

   This function should be the common entry point for both Preview and Pipeline prompt generation.

6. Introduce or standardize a **typed exception** (e.g., `RandomizerError`) for malformed syntax, thrown consistently by parsing/expansion helpers.

### 8.5 Wiring Preview & Pipeline Callers

7. Locate how Preview Prompt and Pipeline Prompt currently call into the randomizer layer. Without modifying GUI or pipeline behavior:

   - Ensure they both use the same canonical randomizer/sanitizer function.
   - Ensure they supply the same seed when parity is required (tests will enforce this).

   If there is no obvious “preview caller” in tests, create a small internal helper tested in `tests/utils/test_randomizer_parity.py` that simulates both sides uniformly.

### 8.6 Clean Up & Docs

8. Add or update docstrings for:

   - Core randomizer functions.
   - Matrix/wildcard parsing helpers.
   - The canonical sanitize/expand entry point.

9. Optionally add a short line to `docs/Known_Bugs_And_Issues_Summary.md` under the randomizer-related issue, marking it as covered by PR-RAND-SAN-001 tests.

---

## 9. Required Tests (Failing First)

Before implementation, create and run these tests so they **fail** against the current baseline:

1. `tests/utils/test_randomizer_parity.py::test_preview_and_pipeline_prompts_match_exactly_for_simple_matrix`
2. `tests/utils/test_randomizer_parity.py::test_preview_and_pipeline_prompts_match_with_wildcards_and_matrices`
3. `tests/utils/test_randomizer_parity.py::test_randomizer_output_deterministic_for_given_seed`
4. `tests/utils/test_randomizer_sanitization.py::test_matrix_tokens_removed_after_expansion`
5. `tests/utils/test_randomizer_sanitization.py::test_wildcards_removed_after_expansion`
6. `tests/utils/test_randomizer_sanitization.py::test_malformed_matrix_raises_clear_error`

Run:

```bash
pytest tests/utils/test_randomizer_parity.py -v
pytest tests/utils/test_randomizer_sanitization.py -v
```

After verifying failures, implement minimal code changes to make them pass, then run:

```bash
pytest tests/utils -v
pytest -v
```

All tests must pass before this PR can be considered complete.

---

## 10. Acceptance Criteria

This PR is complete when:

1. All new tests in:
   - `tests/utils/test_randomizer_parity.py`
   - `tests/utils/test_randomizer_sanitization.py`
   are passing consistently.

2. The existing tests in `tests/utils/` (if any) remain passing, or are updated minimally to align with clarified behavior.

3. Manual spot checks confirm that:
   - Preview Prompt and Pipeline Prompt are always identical for the same input + seed.
   - No randomizer syntax appears in the final payloads sent to WebUI.
   - Malformed syntax (e.g., broken matrices, unmatched tokens) produce clear, typed errors rather than silent failures.

4. There are **no changes** to GUI, controller, pipeline, API, or logging behavior outside the randomizer utilities.

---

## 11. Rollback Plan

If regressions or unexpected behaviors are discovered:

1. Revert changes to:
   - `src/utils/randomizer.py`
   - Any additional randomizer/matrix helper modules modified.
   - `tests/utils/test_randomizer_parity.py`
   - `tests/utils/test_randomizer_sanitization.py`

2. Remove any new notes from `docs/Known_Bugs_And_Issues_Summary.md` referencing PR-RAND-SAN-001.

3. Re-run `pytest -v` to confirm the system is back to its previous stable state.

---

## 12. Codex Execution Constraints

**For Codex (Implementer):**

- Open this spec at:
  - `docs/codex/prs/PR-RAND-SAN-001_randomizer_matrix_sanitization_and_parity.md`

Constraints:

1. **Do not modify** any files outside the **Allowed Files** list.
2. **Do not refactor** beyond what’s necessary to satisfy the new tests.
3. Implement **TDD-first**:
   - Create the new tests in `tests/utils/test_randomizer_parity.py` and `tests/utils/test_randomizer_sanitization.py`.
   - Run them and capture failing output.
   - Only then adjust the randomizer/matrix/sanitizer code.
4. After implementation:
   - Run:
     - `pytest tests/utils -v`
     - `pytest -v`
   - Paste the **full test output** back for review.
5. If file paths differ (e.g., randomizer lives in a slightly different module), ask for confirmation before proceeding.

---

## 13. Smoke Test Checklist (Manual)

After tests pass, perform these quick manual checks in the running app (once wiring is confirmed to use the canonical sanitizer):

1. **Simple Matrix Prompt**
   - Use a prompt pack or simple text prompt with a matrix like `[[knight,wizard,ranger]]`.
   - Verify:
     - Preview shows a single expanded role (e.g., “knight”).
     - Generated images use the same role.
     - No `[[` or `]]` appears in logs or manifests.

2. **Wildcard + Matrix Combination**
   - Use a prompt that includes both wildcards and matrices.
   - Verify:
     - Preview and pipeline prompts match real text exactly.
     - No `__wildcard__` or matrix syntax appears in logs/manifests.

3. **Malformed Input**
   - Intentionally use a malformed matrix (`[[knight,wizard` with a missing `]]`).
   - Confirm:
     - A clear error is surfaced.
     - The app does not quietly proceed with a broken prompt.

If all above pass and tests are green, PR-RAND-SAN-001 can be considered complete.
