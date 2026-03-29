# PR-REPLAY-250 - Replay Fidelity Contract and Versioned Validation

Status: Completed 2026-03-29

## Delivered

- replay validation now enforces versioned intent contracts before replay
- drifted `intent_hash` values are rejected through `ReplayValidationError`
- legacy snapshots without the new contract remain replayable for compat

## Validation

- `tests/pipeline/test_replay_validation_v2.py`
- `tests/pipeline/test_replay_vs_fresh_v2.py`
- `tests/history/test_history_replay_integration.py`
