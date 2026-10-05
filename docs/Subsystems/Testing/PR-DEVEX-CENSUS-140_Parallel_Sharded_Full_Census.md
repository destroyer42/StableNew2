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

## Hosted evidence

Pending the first sharded run of this change on GitHub (serial reference: about 565.7 s of pytest for the PR #50 executable census; hard target <= 300 s, stretch <= 240 s).
