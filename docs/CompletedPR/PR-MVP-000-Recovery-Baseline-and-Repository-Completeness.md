# PR-MVP-000 — Recovery Baseline and Repository Completeness

Status: Completed
Priority: Critical
Completed: 2026-09-05
Owner approval: Rob, 2026-09-05

## Outcome

StableNew now has a non-destructive recovery branch rooted at the best known
stable behavioral reference, with the previously ignored state modules and
focused tests tracked. A deterministic repository-completeness guard proves
that internal Python source is present without relying on ignored local files.

This PR closes only the repository-completeness architecture gap. It does not
claim full startup, test-suite, NJR, persistence, image, video, or MVP health.

## Recovery provenance

- Original worktree: `C:\Users\rob\projects\StableNew`
- Original branch after canon commit: `QOL-Work` at `45b8d079840bf09d7717992f4c55f6dbd0313e3f`
- Preserved user change: `data/webui_cache.json`
- Preserved `main`: `d452a2a8c2ac0db65039b7172c30ec373f6c0337`
- Stable baseline: `f919cb436af2e9e703ca357e830fb57c1f60d578`
- Recovery worktree: `C:\Users\rob\projects\StableNew-mvp-recovery`
- Recovery branch: `recovery/mvp-baseline`
- Carried canon commit: `14d10712997265e73d01d553a5d476c01f71ea44`
  (cherry-pick of `45b8d079840bf09d7717992f4c55f6dbd0313e3f`)
- Verified implementation commit: `d6d91f020f2b4e7397b78d420568967fba6b7111`

The verification worktree was created detached from the implementation commit,
checked clean before and after testing, and then safely removed.

## Source recovery decisions

The original local-only SHA-256 evidence was:

- `src/state/__init__.py`:
  `D3731DD0E3016E7DAFF16774EE4A348274055DBB486154D848F78827D8C97CE2`
- `src/state/workspace_paths.py`:
  `09D956CC7D48F0C91EB0455B6CC6232D13147F7C7E978B09D1631DFD7A980D7B`
- `src/state/output_routing.py`:
  `AA5B0656154B84E1193173934A79A30A4E6AAFCD9FFBFA986FAC7C5CE41BEC2B`

`output_routing.py` was recovered from the local source without functional
changes. `workspace_paths.py` retained its API and path layout while file-path
getters were made non-creating, preventing import-time directory writes;
explicit writers already create their parent directories. The package docstring
was normalized. The two `tests/state/` files were also found to be hidden by the
same broad ignore rule and were recovered at their already-approved paths.

## Files delivered

Runtime/tool/test changes:

- `.gitignore`
- `src/state/__init__.py`
- `src/state/workspace_paths.py`
- `src/state/output_routing.py`
- `tests/state/test_workspace_paths.py`
- `tests/state/test_output_routing.py`
- `tests/system/test_repository_completeness_v2.py`
- `tools/ci/check_repository_completeness.py`

Closeout changes:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- this CompletedPR record
- removal of the duplicate backlog spec

## Verification

Available interpreter: Python 3.10.6 with pytest 9.0.1.

Focused recovery-worktree results:

- completeness guard: passed, 435 tracked Python source files;
- `tests/system/test_repository_completeness_v2.py`: 8 passed;
- `tests/state/test_workspace_paths.py`: 24 passed;
- `tests/state/test_output_routing.py`: 10 passed;
- consumer tests for learning paths, output folder structure, and curation
  routing: 14 passed;
- `python -m compileall -q src`: passed;
- direct imports of all three `src.state` modules: passed;
- root `state/` existed before/after import: false/false;
- root `state/` remained ignored and `src/state/` remained unignored.

Independent tracked-files-only worktree results:

- exact implementation commit: `d6d91f0`;
- completeness guard: passed;
- compile and direct state imports: passed;
- combined focused suite: 42 passed in 1.39 seconds;
- Git status before and after: clean;
- root `state/` before and after: absent.

`git diff --check` passed for the implementation. The original QOL worktree
still contained only the pre-existing `data/webui_cache.json` modification.

## Verification deviations and deferred debt

- The approved spec expected a managed Python 3.11 environment. No Python 3.11
  interpreter was installed on the machine; the existing project environment is
  Python 3.10.6. No system runtime was installed implicitly. Python 3.11 setup
  and certification remain owned by `PR-MVP-010`.
- Pytest reported that `pytest.ini` overrides/causes the pyproject pytest config
  to be ignored. Configuration convergence remains owned by `PR-MVP-010`.
- Ruff was not installed in the managed environment, so a Ruff check was not
  available. Toolchain pinning remains owned by `PR-MVP-010`.
- Later changes in `24063b7`, `d452a2a`, and pre-canon `1a9eb49` were not
  imported. Their disposition remains owned by `PR-MVP-005`.

These deviations do not weaken the verified tracked-source completeness result
and do not close the broader test-truth gap.

## Rollback

The original worktree and protected refs were not rewritten. Recovery can be
abandoned by ceasing to use `recovery/mvp-baseline`; the worktree/branch should
only be removed after confirming no unique later work exists. The implementation
commit can be reverted on its branch without modifying `main` or `QOL-Work`.

## Next step

Write and approve `PR-MVP-005`, an evidence-only delta disposition for
`24063b7`, `d452a2a`, and pre-canon `1a9eb49`. It must classify changes before
any selective implementation or merge.
