# PR-REPLAY-250 - Replay Fidelity Contract and Versioned Validation

Status: Completed 2026-03-29

## Purpose

Formalize replay acceptance so replayable history snapshots are versioned,
hash-closed, and rejected before execution when intent drift is detected.

## Delivered

- replay validation now checks `intent_contract` and `config_layers.intent_hash`
  before hydrating an NJR
- invalid replay metadata now raises `ReplayValidationError`
- legacy snapshots without the new contract remain accepted for backward
  compatibility

## Validation

- `tests/pipeline/test_replay_validation_v2.py`
- `tests/pipeline/test_replay_vs_fresh_v2.py`
- `tests/history/test_history_replay_integration.py`
