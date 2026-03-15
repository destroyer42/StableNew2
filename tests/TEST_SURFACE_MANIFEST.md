# TEST_SURFACE_MANIFEST.md
# Active Test Surface for StableNew v2.6

Status: Authoritative
Updated: 2026-03-12

---

## 1. Purpose

This manifest classifies all test areas, their canonical locations, and their
collection status. It is the single source of truth for "which tests are supposed
to run in CI" and "where to add new tests for each subsystem."

---

## 2. Active Test Directories (repository test surface)

All directories below are under `tests/`. They are part of the maintained test
surface, even if CI currently runs only a subset of them in required gates.

| Directory | Subsystem | Notes |
|---|---|---|
| `tests/ai_v2/` | AI pipeline v2 | |
| `tests/api/` | WebUI API client | |
| `tests/app/` | Application-level smoke | |
| `tests/cluster/` | Cluster compute | |
| `tests/compat/` | Compatibility layer | |
| `tests/controller/` | AppController, job service, heartbeat | |
| `tests/data/` | Data access / cache | |
| `tests/debughub/` | DebugHub diagnostics | |
| `tests/history/` | Job history / history cache | |
| `tests/integration/` | Cross-subsystem integration | Optional/full-suite CI, not required gate |
| `tests/journey/` | End-to-end journey | Optional/full-suite CI, tagged `journey` |
| `tests/journeys/` | Additional journey tests | Optional/full-suite CI |
| `tests/learning/` | Legacy learning tests | |
| `tests/learning_v2/` | v2.6 learning subsystem | Canonical; priority |
| `tests/photo_optimize/` | Photo optimize workflow | |
| `tests/pipeline/` | Builder pipeline, VAE, NJR | |
| `tests/queue/` | Queue, persistence, remove | |
| `tests/randomizer/` | Randomizer determinism | |
| `tests/regression/` | Regression cases | |
| `tests/safety/` | Safety guard tests | |
| `tests/services/` | Background services | |
| `tests/state/` | State persistence, workspace paths | |
| `tests/utils/` | Utility functions | |
| `tests/video/` | Video workflow | |
| `tests/gui_v2/` | GUI v2 integration | Optional/full-suite CI; not in required gate |

---

## 3. CI Gate Mapping

The current CI policy is split intentionally:

| Surface | Coverage |
|---|---|
| Required CI gate | lint + fast deterministic non-GUI/non-journey/non-integration tests |
| Optional/full-suite CI | `tests/gui_v2/`, `tests/integration/`, `tests/journey/`, `tests/journeys/`, and the broader suite under Xvfb |

---

## 4. Excluded by CI Configuration

| Path | Reason | How to Run Locally |
|---|---|---|
| `tests/gui/` | Requires live Tk display | `pytest tests/gui/ -v` |
| `tests/quarantine/` | Tk-dependent or manual scripts | See `tests/quarantine/README.md` |
| `tests/tmp_executor/` | Temp / scratch | Evaluate and promote or delete |
| `tests/legacy/` | Pre-v2.6 tests | Reference only |

---

## 5. Test Placement Rules

- **Where does a new unit test for `src/X/y.py` go?**
  → `tests/X/test_y.py` or the nearest matching directory in §2.

- **Where does a controller integration test go?**
  → `tests/controller/`

- **Where does a learning analytics test go?**
  → `tests/learning_v2/`

- **Where does a queue/persistence test go?**
  → `tests/queue/`

- **Where does a GUI test go if it requires Tk?**
  → `tests/quarantine/` until it is rewritten with mock fixtures;
    then `tests/gui_v2/` or `tests/gui/`

- **Fixture files (static committed data)?**
  → `tests/fixtures/` only. No runtime artifacts in fixtures/.

---

## 6. Canonical Test Naming Conventions

- Pure unit tests: `test_<module_name>.py`
- Contract tests: `test_<area>_contract.py`
- Integration tests: `test_<feature>_integration.py`
- Regression cases: `test_<ticket_or_pr>_<description>.py`

---

## 7. Maintenance Rules

- If a new test directory is added under `tests/`, add it to §2 in the same PR.
- If a test is removed or quarantined, update §3 in the same PR.
- Do not add tests directly to the root of the repository; use canonical
  subdirectories.

---

**Document Status**: ✅ CANONICAL
**Last Updated**: 2026-03-12
