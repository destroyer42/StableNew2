# Active Test Surface for StableNew v2.6

Status: Authoritative
Updated: 2026-09-06

## 1. Purpose

This manifest separates tests that block an MVP change from tests that are
merely collectable, optional, compatible with older behavior, manually invoked,
quarantined, or archived. Test presence and a green assertion do not make a
behavior canonical. Architecture authority comes from the active canon and the
Finalized MVP Roadmap.

## 2. Pytest authority and default collection

`pyproject.toml` is the only pytest configuration. Default collection is strict,
uses importlib mode, and starts at `tests/`.

These paths are excluded by default:

| Path | Classification | Reason |
|---|---|---|
| every `archive/` or `ARCHIVE/` tree | Archive | Historical evidence only |
| `tests/gui/` | Optional legacy GUI | Requires a live display and does not define GUI v2 |
| `tests/gui_v1_legacy/` | Legacy GUI | Superseded surface |
| `tests/legacy/` | Legacy | Superseded behavior |
| `tests/quarantine/` | Quarantine | Known unsafe, display-bound, or unresolved coverage |
| `tests/scripts/` | Manual | Diagnostic scripts, not pytest tests |

`tests/gui_v2/` remains collectable. A GUI v2 test must skip safely when its
display dependency is unavailable. Integration and journey suites are
collectable, but collection is not permission to contact an external service.

## 3. Surface classifications

### 3.1 Required merge gate

The required pytest subset is the positive list in
`tools/ci/run_required_smoke.py`. It covers repository completeness,
architecture enforcement, CI/configuration truth, runtime-state hygiene,
workspace/output isolation, the current controller-to-queue seam, queued
execution, and queue error handling.

The list deliberately omits legacy direct-mode compatibility. It must never be
implemented as all tests minus an ignore list. Any change to the list must also
update this manifest, `tests/system/test_ci_truth_sync_v2.py`, and
`docs/StableNew_Coding_and_Testing_v2.6.md`.

Required CI commands are:

```text
python tools/ci/check_repository_completeness.py
python tools/ci/run_ruff_baseline.py
python tools/ci/run_mypy_smoke.py
python tools/ci/run_collection_gate.py
python tools/ci/run_required_smoke.py
```

The collection and smoke runners use a disposable working directory,
deterministic no-WebUI/test-mode environment, and repository-content comparison.
A passing pytest return code with repository pollution is a failed gate.

The required lint gate pins Ruff 0.14.9 and ratchets 2,208 pre-existing
findings by source path and rule. New or increased debt fails. Every MVP PR must
leave its touched source files clean; PR-MVP-080 owns bounded cleanup of
untouched findings, and PR-MVP-090 requires the baseline to reach zero.

### 3.2 Collected active-development coverage

Subsystem directories such as `api/`, `controller/`, `data/`, `debughub/`,
`history/`, `pipeline/`, `queue/`, `randomizer/`, `regression/`, `safety/`,
`services/`, `state/`, `system/`, and `utils/` are collected development
coverage. Individual tests may still encode current implementation debt. Only
the exact required subset blocks every PR.

### 3.3 Optional integration and journey coverage

`integration/`, `journey/`, `journeys/`, and `gui_v2/` provide broader
cross-subsystem feedback. They run in the non-blocking broad CI job while the
MVP contract migrations are active. Journey fixtures use fakes by default.

### 3.4 Compatibility coverage

`compat/` and tests marked `compat` or `legacy` constrain temporary behavior.
They cannot overrule canon or block deletion of an obsolete path in its owning
approved migration PR.

### 3.5 Post-MVP or not-yet-promoted coverage

Cluster, broad learning/product-training, photo optimization, non-native video,
and other post-MVP feature suites do not become release gates by being
collectable. `PR-MVP-060` through `PR-MVP-090` own exact promotion, quarantine,
or removal decisions.

### 3.6 Real-backend acceptance

Real WebUI and native SVD tests are explicit acceptance work, marked
`real_backend`, run separately on the target machine, and never enter required
CI. Journey fixtures construct a real client only when
`STABLENEW_REAL_BACKEND_TESTS=1` is set explicitly.

## 4. Placement rules

- New tests go in the nearest subsystem directory, never directly under
  `tests/`.
- Unit tests for `src/X/y.py` normally go in `tests/X/test_y.py`.
- Cross-subsystem tests go in `tests/integration/`; product journeys go in a
  journey directory.
- Live-display tests stay out of required CI until made headless-safe.
- Manual executable probes go under `tests/scripts/` and must use a main guard.
- Fixture files belong under `tests/fixtures/`; runtime artifacts are not
  fixtures.
- Legacy semantics belong under `tests/compat/` and need a named deletion PR.
- No test may write user packs or mutable state into the repository.

## 5. Marker policy

Every custom marker must be registered in `pyproject.toml`. Registration is a
collection contract, not a statement of authority. `real_backend` requires
explicit operator opt-in. `compat` and `legacy` never satisfy an MVP architecture
gate. Step markers `gp1` through `gp15`, `golden_path`, `journey`, and similar
labels describe grouping only.

## 6. Isolation rules

- Tests default to `STABLENEW_NO_WEBUI=1` and `STABLENEW_TEST_MODE=1`.
- WebUI discovery cache, logs, output, history, and temporary data use pytest
  temporary paths.
- Required tests use fakes and deterministic event/poll synchronization.
- Collection performs no assertions, pack rewrites, backend launches, or root
  artifact creation.
- Test completion closes threads, clients, loggers, and temporary resources.
- The standard pytest `tmp_path` fixture is not overridden.
- Tracked runtime/cache/probe files fail the hygiene guard.

## 7. Deferred cleanup ownership

- NJR and serialization assertions: `PR-MVP-020`.
- Direct-mode, broad submission, queue/controller compatibility, and related
  duplicate tests: `PR-MVP-030`.
- JSON/JSONL persistence coverage: `PR-MVP-040`.
- Paired PromptPack coverage: `PR-MVP-050`.
- Image GUI/integration promotion: `PR-MVP-060`.
- Video surface quarantine/native SVD proof: `PR-MVP-070`.
- Learning, cluster, and post-MVP operator quarantine: `PR-MVP-080`.
- Final required/optional inventory and remaining harmless duplicates:
  `PR-MVP-090`.

No new root test or compatibility shim may be added while this debt is open.
