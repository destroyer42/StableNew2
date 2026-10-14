# PR-IMG-FORGE-230 — Forge supported-option defaults integrity

Execution Profile + Model/Reasoning Recommendation: Narrow, one API-client method and its
regressions. Claude Code Sonnet 5.5 Medium; Codex equivalent Medium. No host preference: no
GUI, native Windows or GPU behavior is involved.

Controller Surface Assessment: no controller/coordinator code touched. The executor's
`_apply_webui_defaults_once` is unchanged; it ignores the client method's return value, so the
additive return type changes no caller contract. No compiler, NJR, queue, runner, history,
runtime-ownership or GPU policy change; no new authority.

Token-Efficient Validation Plan: failing API/caller regressions first, focused client and
executor tests, then the canonical PR gate once. No physical Forge write, restart or job.

## Defect

`SDWebUIClient.apply_upscale_performance_defaults` (called once per run by
`Pipeline._apply_webui_defaults_once`) POSTed one `/sdapi/v1/options` payload that always named
`DAT_tile` and `DAT_tile_overlap`. The managed Forge does not advertise those options and
answers a write naming an unknown option with HTTP 500 (`KeyError: DAT_tile` in its log), so
the whole write was refused and the HTTP layer replayed it three times. The client swallowed the
failure and the executor then marked defaults applied: the conservative ESRGAN/cache defaults
were attempted but never confirmed, and nothing reported that.

Source of the finding: the OPS230 operational-acceptance report (current-main fake-transport
probe sent the payload three times on HTTP 500; the owner's Forge log shows three
`KeyError: DAT_tile` failures). No connection to the October 12 device-loss incident is
established or claimed.

## Contract

- The method reads the WebUI's advertised option keys (a fresh `GET /sdapi/v1/options` for each
  call) and writes only the intended defaults that are advertised. Intended values are unchanged.
- Options not advertised are left unchanged and reported, not sent.
- An unreadable or empty listing writes nothing (never a blind write, never "everything
  unsupported"), and a failed listing is no longer cached as an empty option set for the life of
  the client (`_ensure_option_keys`; this also stops `set_hypernetwork` from permanently
  skipping strength after one transient failure).
- It returns a `WebUIDefaultsOutcome` (`applied`, `unsupported`, `skipped_reason`, `error`).
  Logs say what was applied and what was not; a rejected write is logged as unverified. It still
  never raises.
- Unchanged: SafeMode/readiness/throttle gating (checked first, no request when refused), the
  once-per-run flag in the executor, retry policy, and `ensure_safe_upscale_defaults`, which
  already only touches keys the WebUI returns.

## Validation

Regressions: `tests/test_api_client.py` (full payload when everything is advertised, DAT keys
omitted for a Forge-like listing, nothing advertised, unreadable listing not written and not
cached, rejected write reported without raising, SafeMode silent) and
`tests/pipeline/test_forge_supported_option_defaults_230.py` (the real executor entry sends one
filtered write, once per run, and survives a refusing WebUI). Seven of the eight failed against
the unmodified client; the eighth pins existing behavior.

Run with the project's Python 3.14.8 environment: focused API/executor/queue selection
(530 passed), `ruff check`, `git diff --check`, and the canonical PR gate (repository
completeness, controller ratchet, Ruff, mypy smoke, 9,532 collected, 386 smoke passed).

## Not changed / residual risk

- The executor still marks defaults applied after one attempt, including a refused write. This is
  deliberate scope control (a retry-until-applied lifecycle is a separate decision); the outcome
  is now available to a future caller.
- No runtime was written to: the owner's live Forge was not contacted, and whether its effective
  tile values are the conservative ones was not measured.
- The deployment mismatch in the OPS230 report (running checkout lacks #100–#102) needs an
  owner-controlled relaunch, not code; this PR does not change that.
- Forge `/cmd-flags` response-schema 500s are separate runtime compatibility debt.
