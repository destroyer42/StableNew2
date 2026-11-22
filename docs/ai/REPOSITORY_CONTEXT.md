# Offline repository context

The repository context command extends the task descriptions in `docs/CODEX_MAP.md`
and the module summaries in `docs/CODE_MAP.md`. It gives Claude Code and Codex
a short reading list grounded in the selected checkout. Use `AGENTS.md` and
`STATUS.md` first, then verify the relevant sources and subsystem records.

## Commands

```sh
python -m tools.repo_context route "Freeze Comfy video workflow inputs for queue admission"
python -m tools.repo_context capsule "Find compile_njr" --format json
python -m tools.repo_context capsule "Find compile_njr" --budget 900
python -m tools.repo_context index
python -m tools.evaluate_repo_context
```

`route` yields ranked JSON with explanations. The default cap is five
implementation paths. Related dependencies, tests and documents have smaller
individual caps. Use `--limit 1` for a narrow query, an exact path or symbol
to disambiguate, or `--broader --limit 8` to intentionally widen the search.
An empty or ambiguous result is a reason to consult the task map or refine the
task description. `--root PATH` before the subcommand selects another trusted
local Git worktree whose origin is the StableNew2 repository. The commands use
the Python standard library and local Git.

To save a machine-readable capsule, redirect JSON output to a new file outside
the worktree or in an ignored directory. Before reusing one, supply it to
`python -m tools.repo_context verify`
on standard input from the same worktree. For a saved Markdown capsule, compare
its identity with a fresh invocation, or regenerate it. Verify checks checkout
freshness. Its exit status does not certify the recommendations or the origin
of the saved text.

## Index and capsule contracts

**Index v1.** The JSON maps each source path to a qualified module name,
source SHA-256, parse status, module summary, symbols with kind and line, imports,
dependencies, reverse dependents, package initializers, test hints, and document
references. `static` records a resolvable local module and, for a from-import,
a statically visible name when resolution depends on the name. With
`attribute-unverified` the base module is known and the attribute binding is
uncertain. `external` includes standard-library and third-party imports.
`unresolved` denotes an unmatched local or invalid relative import.
`dynamic-syntax` records a recognizable dynamic call without making an edge.
Resolution covers normal relative imports, aliases, and package initializers.
Guarded and deferred syntax are marked. Reflection, runtime registration,
complex re-exports and plugin discovery can hide relationships. Imported tests
show a syntax connection. Matching filenames and documentation links are hints.

The index is rebuilt on demand and kept in memory for routing. The command
writes to stdout. Its source corpus is tracked `src/**/*.py` and `tests/**/*.py`,
plus non-ignored additions in those locations. Navigation also reads the existing
maps, registered living documents and local CI metadata. File and directory links,
junctions, excluded cache/output paths and other working-tree data are outside
the read corpus. The corpus hash binds the collected bytes and known navigation
paths to a checkout and HEAD. Dirty status is independently recorded. Generate
again after edits, and verify before using a saved capsule. Generate while the
checkout is stable so concurrent edits cannot produce a mixed snapshot.

**Capsule v1.** Markdown and JSON have the same authority-first reading order and
include the query, checkout identity, index version, evidence for selected
paths, dependency limitations and focused validation guidance. The renderer
enforces an approximate output budget of three UTF-8 bytes per unit, with a
default of 1,200 units. Actual tokenizer counts vary. Use the full route output
for additional candidates. The capsule is a navigation aid. All editing,
runtime activity and shared-state actions remain subject to repository authority
and the current work-package authorization.

## Regression and evaluation method

Run `python -m pytest tests/tools/test_repo_context.py tests/tools/test_code_map.py`
for the focused suite and `python tools/generate_code_map.py --check` for
freshness. For a docstring-only pass, `python tools/generate_code_map.py
--verify-docstrings-from COMMIT` checks the source inventory and verifies that
removing each added module docstring reproduces its original AST.

The evaluation takes ten fixed queries in `tests/tools/context_cases.json`.
A read-only reviewer used the source and CI definitions to choose primary
implementation paths before inspecting any router code or results. The runner
repeats each route three times, compares ordered outputs and emits all paths,
hits, misses and timings in JSON. The baseline uses the two Markdown maps and
the same lexical scorer and cap, with the AST, graph, and CI job signals
removed. Recall and labeled precision count implementation paths only. A
candidate outside the labels adds reading burden and can still be relevant
supporting context. Capsule size is a byte-based estimate. Warm routing
excludes cold index creation. This is a retrieval benchmark without paired
Claude Code or Codex sessions.

## Evaluation results

Windows, Python 3.14.9, 22 November 2026. Both routes used the completed code
map and current task map. Each could recommend at most five implementation
paths. Labels were fixed before evaluation. Ranking changes were evaluated on
the same set, so these numbers are development evidence.

| Measure | Router | Two-map baseline |
| --- | ---: | ---: |
| Primary recall | 14/15 (93.3%) | 14/15 (93.3%) |
| Labeled precision | 14/42 (33.3%) | 14/41 (34.1%) |
| Unlabeled implementation paths | 28 | 27 |
| Median warm routing | 57.58 ms | 26.25 ms |
| Median Markdown capsule size, estimated units | 785 | 551 |
| Identical ordered results over three runs | 10/10 | 10/10 |

Cold index creation took 9.66 seconds in this run. Neither route recommended
source for the unrelated query.

| Case | Router hits | Baseline hits |
| --- | ---: | ---: |
| Outage dispatch | 2/2 | 2/2 |
| GUI queue submission | 2/2 | 2/2 |
| NJR compilation | 1/1 | 1/1 |
| SQLite snapshots and lifecycle | 1/1 | 1/1 |
| Image model compatibility | 0/1 | 1/1 |
| Comfy workflow admission | 2/2 | 2/2 |
| Review and Learning evidence | 2/2 | 2/2 |
| Managed WebUI readiness | 2/2 | 2/2 |
| Local and hosted CI | 2/2 | 1/2 |
| Unrelated task | 0/0 | 0/0 |

The richer matching recovered `.github/workflows/ci.yml` but ranked specific
backend and profile modules ahead of `src/image_backends/model_policy.py`.
The benchmark therefore supports comparable primary recall and richer
provenance, with higher latency and a slightly higher reading burden. It does
not establish better general retrieval or lower agent-session token usage.

A future reranker can consume the same index and candidate records. The
current commands can supply a deterministic fallback for any optional
reranker introduced under a separate work package.
