# PR-DEVEX-CENSUS-140 - parallel / sharded full census

Result class: **CI EXECUTION (no coverage change).** The full census runs the same deterministic test surface as before; only how it executes changed. No test was deleted, skipped, xfailed,
weakened or consolidated; zero `src/` changes; `required`, affected-lane routing, docs-only evidence reuse and the informational status of the census are unchanged.

## Design

* **Partition:** whole test files, `shard = int(sha256(repo-relative POSIX path).hexdigest(), 16) % shard_count` (`tools/ci/census_shards.py`). No timing database, no checked-in file list, no optimizer;
  a new test file is assigned automatically, and Windows and Linux compute the same shard (paths are normalised to POSIX before hashing).
* **Active surface (one authority):** `active_test_files()` mirrors pytest's own selection - `testpaths`, `python_files = test_*.py`, `norecursedirs` (read from `pyproject.toml`) and the
  `--ignore` list owned by `tools/ci/run_collection_gate.DEFAULT_COLLECTION_EXCLUDES` - and keeps files that yield no runnable node (for example the two documented collection-time skips). A test asserts
  the planner never admits an excluded directory and that every module pytest collects is an active file.
* **Hosted:** three independent `full-suite-shard` jobs (matrix `shard: [0, 1, 2]`; each its own runner, checkout, Python process, Xvfb, JUnit and artifact) run ordinary pytest on their whole files via an argument file
  (`-q -rfE --tb=short --timeout=300`, JUnit total durations, no `--maxfail`; flags live once in `census_shards.PYTEST_ARGS`). No `pytest-xdist`.
* **Aggregate `full-suite` job (the human-visible verdict, informational like before):** downloads the shard artifacts and fails closed unless the partition is complete and disjoint, every shard's executed manifest equals
  the current partition, every artifact exists, every shard's pytest exited 0 and no JUnit record belongs to a file outside its shard. It merges the JUnit into one `census.xml` so `census_summary.py` remains the single summarizer,
  and reports parallel census wall (slowest shard), fastest shard, imbalance, summed shard wall and summed test durations separately. Elapsed census time is the slowest shard's pytest wall, never the sum of shard walls.
* **Local:** `python tools/ci/run_sharded_census.py [--workers 2]` uses the same partition with one pytest process per worker, each with its own `--basetemp`, cache, JUnit and log, then runs the same completeness gate.
  Each worker runs in its own isolated checkout (a detached worktree of HEAD plus the current uncommitted changes), mirroring one checkout per hosted shard. It never starts, stops or adopts an external runtime.

## Concurrency finding (one bounded repair)

The first local run shared one working tree between workers. The operator-journey isolation guard watches the repository's real `state/` tree and failed ("protected data changed in state/:
asset_registry_v1.json") because the other worker's tests wrote it; the test passes alone and cannot occur in hosted CI where every shard has its own checkout. The repair is in the runner, not the tests: per-worker isolated
checkouts. No serial exception, test change or skip was needed. (A collection-skip record has an empty classname and the dotted module as its name; `census_summary.py` now attributes it to that module instead of `(unknown)`.)

## Local measurement (Windows workstation, 2 workers, current source)

Complete census: 5,093 JUnit records = 5,071 passed, 22 skipped, 0 failed, 0 errors over 722 active test files (completeness gate PASS). Worker walls 356.5 s and 463.8 s; **census wall 464.0 s** (imbalance 1.30;
summed worker time 820 s). The earlier serial Windows census was about 1,002 s (directional; different source state). Targets: <= 600 s (met), <= 480 s stretch (met).

## Hosted evidence (first sharded run of the executable change, Python 3.14)

`required` passed; all three shard jobs and the aggregate `full-suite` passed; `affected` was skipped (subsumed). The aggregate completeness gate reported **no problems**: 722 active test files, each in exactly one shard
(233 / 231 / 258), every shard exit code 0, every JUnit record inside its own shard's manifest.

| Shard | Files | JUnit records (passed / skipped) | Pytest wall | Job elapsed |
|---:|---:|---:|---:|---:|
| 0 | 233 | 1,772 (1,743 / 29) | 134.8 s | 2 m 48 s |
| 1 | 231 | 1,622 (1,613 / 9) | 116.3 s | 2 m 20 s |
| 2 | 258 | 1,699 (1,690 / 9) | 114.9 s | 2 m 27 s |

Aggregate: 5,093 JUnit records = 5,046 passed, 47 skipped, 0 failed, 0 errors; the aggregate job took 12 s. Reconciliation with collection: 5,093 = 5,091 runnable tests (the local gate count) + the 2 documented
collection-time skips. Two active files legitimately collect zero tests (`tests/controller/test_checkbox_fix.py`, and a 54-byte removed-file stub), so 720 of 722 files have records.

**Parallel census wall = slowest shard pytest wall = 134.8 s** (fastest 114.9 s, imbalance 1.17; summed shard wall 366.0 s is reported separately and is not elapsed time) versus about 565.7 s for the serial PR #50
census: a reduction of about 76 %. Hard target <= 300 s and stretch <= 240 s are both met. The local Windows two-worker census (464 s) met its <= 600 s requirement and <= 480 s stretch.

An independent read-only verification confined to census completeness approved the package: it recomputed the active surface independently of the helper, recomputed every file's SHA-256 shard, matched all three hosted
manifests exactly, reconciled the JUnit records, found no excluded directory admitted and no omitted active file, and confirmed `required` and the affected lanes are byte-identical to before.

## Deferred hardening (non-blocking; not required for acceptance)

* A future active file that silently collects zero tests passes the aggregate, exactly as it would in a serial pytest run (informational list only).
* `pyproject.toml` sets `norecursedirs`, which replaces pytest's defaults, while the planner skips only dot-directories and `__pycache__`; no `build`/`dist`-style directory exists under `tests/` today, so there is no current divergence.
* The aggregate does not compare each shard's argument file with its manifest (both derive from the same function and the manifest is already compared with the recomputed partition).

Shard balancing (hosted imbalance 1.17, Windows 1.30) was deliberately not pursued: the targets were exceeded, and dedicated test-performance work stops here in favor of opportunistic per-PR test hygiene.
