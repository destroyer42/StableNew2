# TEST_SURFACE_MANIFEST.md
# Active Test Surface for StableNew v2.6

Status: Authoritative
Updated: 2026-03-29

---

## 1. Purpose

This manifest classifies the test surface into canonical, compat, and excluded
areas so CI and developers can tell which suites define current runtime truth.

Canonical suites validate the active v2.6 architecture. Compat suites validate
temporary migration or legacy-compat behavior. Quarantine and archive do not
define architecture.

---

## 2. Active Test Directories

All directories below are under `tests/`. They remain maintained surfaces, but
they do not all have the same authority.

| Directory | Subsystem | Notes |
|---|---|---|
| `tests/ai_v2/` | AI pipeline v2 | Canonical |
| `tests/api/` | WebUI API client | Canonical |
| `tests/app/` | Application-level smoke | Canonical |
| `tests/cluster/` | Cluster compute | Canonical |
| `tests/compat/` | Compatibility and migration validation | Temporary; not canonical runtime truth |
| `tests/controller/` | AppController, job service, heartbeat | Canonical |
| `tests/data/` | Data access and cache | Canonical |
| `tests/debughub/` | DebugHub diagnostics | Canonical |
| `tests/history/` | Job history and cache | Canonical |
| `tests/integration/` | Cross-subsystem integration | Canonical integration only; optional/full-suite CI |
| `tests/journey/` | End-to-end journey | Canonical journey; optional/full-suite CI |
| `tests/journeys/` | Additional journey tests | Canonical journey; optional/full-suite CI |
| `tests/learning/` | Learning subsystem | Canonical learning tests and hooks |
| `tests/learning_v2/` | v2.6 learning subsystem | Canonical; priority |
| `tests/photo_optimize/` | Photo optimize workflow | Canonical |
| `tests/pipeline/` | Builder pipeline, VAE, NJR | Canonical |
| `tests/queue/` | Queue, persistence, remove | Canonical |
| `tests/randomizer/` | Randomizer determinism | Canonical |
| `tests/regression/` | Regression cases | Canonical |
| `tests/safety/` | Safety guard tests | Canonical |
| `tests/services/` | Background services | Canonical |
| `tests/state/` | State persistence and workspace paths | Canonical |
| `tests/system/` | Architecture and surface enforcement | Canonical |
| `tests/utils/` | Utility functions | Canonical |
| `tests/video/` | Video workflow | Canonical |
| `tests/gui_v2/` | GUI v2 integration | Canonical GUI integration; optional/full-suite CI |

---

## 3. CI Gate Mapping

The CI policy is intentionally tiered:

| Surface | Coverage |
|---|---|
| Required canonical gate | `python tools/ci/run_required_smoke.py` |
| Required typed seam gate | `python tools/ci/run_mypy_smoke.py` |
| Optional/full-suite CI | `tests/gui_v2/`, `tests/integration/`, `tests/journey/`, `tests/journeys/`, and the broader suite under a GUI-capable environment |
| Compat gate | `tests/compat/` and explicitly marked migration or legacy-compat checks |

Canonical gates should prefer current queue-first, NJR-first runtime truth.
Compat coverage exists to constrain temporary migration behavior and must shrink
over time.
The required smoke contract is the exact pytest subset encoded in
`tools/ci/run_required_smoke.py`; CI and docs must point to that script rather
than duplicating the ignore list ad hoc. The typed architecture seam contract is
the exact target list encoded in `tools/ci/run_mypy_smoke.py`.

---

## 4. Excluded by Default Collection Policy

| Path | Reason | How to Run Locally |
|---|---|---|
| `tests/gui/` | Requires a live Tk display | `pytest tests/gui/ -v` |
| `tests/quarantine/` | Tk-dependent or manual scripts | See `tests/quarantine/README.md` |
| `tests/tmp_executor/` | Temp or scratch | Evaluate and promote or delete |
| `tests/legacy/` | Pre-v2.6 tests | Reference only |

---

## 5. Placement Rules

- New unit tests for `src/X/y.py` go in `tests/X/test_y.py` or the nearest matching canonical directory above.
- Controller integration tests go in `tests/controller/`.
- Learning analytics tests go in `tests/learning_v2/` unless they exercise existing learning hooks in `tests/learning/`.
- Queue and persistence tests go in `tests/queue/`.
- GUI tests that still need a live Tk display go in `tests/quarantine/` until rewritten with mock fixtures.
- Fixture files belong in `tests/fixtures/` only. No runtime artifacts in fixtures.
- Archive DTO or legacy submission semantics belong in `tests/compat/`, not in canonical subsystem directories.

---

## 6. Naming Conventions

- Pure unit tests: `test_<module_name>.py`
- Contract tests: `test_<area>_contract.py`
- Integration tests: `test_<feature>_integration.py`
- Regression cases: `test_<ticket_or_pr>_<description>.py`

---

## 7. Maintenance Rules

- If a new test directory is added under `tests/`, update Section 2 in the same PR.
- If a test is moved between canonical, compat, quarantine, or archive buckets, update Sections 2 and 3 in the same PR.
- Do not add tests directly to the repository root; use canonical subdirectories.
- Canonical suites must not import archive runtime DTOs. If legacy coverage is still needed, move it to `tests/compat/`.

---

Document Status: CANONICAL
Last Updated: 2026-03-29
