# Quarantine

Holding area for test files that cannot be collected by the standard CI pytest
run (`pyproject.toml` ignores this directory). It is intentionally empty.

PR-TEST-TRUTH-200 audited the previous contents: nine manual, `mainloop()`-driven
render/import/heartbeat scripts with no pytest tests were deleted (superseded by
`tests/gui_v2`, `tests/controller/test_heartbeat_stall_fix.py`,
`tests/services/test_pr_harden_008_watchdog.py`, and `tests/utils/test_diagnostics_bundle_v2.py`);
the two real tests graduated to `tests/learning/test_learning_baseline_config.py`
and `tests/gui_v2/test_queue_panel_remove_updates_gui.py`.

Add a file here only with a recorded reason and a removal condition. A file with
no behavioral protection should be deleted, not quarantined.

## Flake policy

The census is a blocking gate, so a test that fails and later passes without a code change is repaired, not retried.
If it cannot be fixed in the same PR, move it here with a first-line header and open the repair:

```
# quarantined: YYYY-MM-DD; owner: <name>; expires: YYYY-MM-DD; reason: <why>
```

A quarantine lasts at most 30 days. `tests/system/test_quarantine_policy.py` fails once a quarantine expires, which
forces the decision: fix it, extend it deliberately, or delete it.

