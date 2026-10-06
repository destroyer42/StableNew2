# PR-RUNTIME-FORGE-IDENTITY-150 - Managed Forge identity attestation

Result class: **BOUNDED RUNTIME-IDENTITY REPAIR**. No lifecycle, ownership, backend-selection, queue, retry or Forge change. The
canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.
Execution Profile: bounded runtime identity seam (Claude Code: Sonnet 5.5 High).

## Owner outcome

A StableNew-owned managed Forge that has been positively identified as Forge is not rejected as `unknown` because a *later* identity
probe could not re-read enough endpoint evidence, while the fail-closed Forge identity contract is otherwise unchanged.

## Verified root cause

`WebUIFamilyImageBackend.execute()` ran `classify_client_runtime(pipeline.client)` and `assert_runtime_matches_backend(...)` before
every stage. `SDWebUIClient.probe_runtime_identity()` issues four fresh read-only GETs (`/cmd-flags`, `/options`, `/sd-modules`,
`/sd-vae`) with no retry and no memory. Forge is classified positively only from a readable `/options` with a Forge option key, an
`/sd-modules` list and no A1111 `/sd-vae` list; `/cmd-flags` is already optional. A failure of either required endpoint therefore
turned the same healthy process from `forge_webui` into `unknown`, and the guard refused the stage before dispatch.

Pre-fix reproduction (unmodified source, real `ForgeWebUIImageBackend`, scripted probe): stage 1 observes Forge and dispatches;
stage 2 observes `unknown` and raises `WebUIRuntimeIdentityMismatch` ("classified 'unknown'") with no dispatch.

The existing local logs were produced by test runs; they carry no production `unknown` rejection, so whether the originally
observed failure was a transient evidence gap or a real replacement is **not** established from logs. The repair is safe in
either case (a replacement changes the session and is never covered); the physical acceptance below is what distinguishes them.

## Contract

**One narrow relaxation.** For a StableNew-owned runtime, after the endpoint has been *positively classified as Forge from real
endpoint evidence*, a later pre-dispatch probe of `unknown` is accepted for a `forge_webui` stage only when every fact of the
attested session still matches the currently authoritative owned runtime and the weak probe carries no contradicting evidence.

**Never proof.** A manager, its declared `runtime_identity`, `WebUIReadyEvent.runtime_identity`, port 7871, a path/name, settings,
the previous job's backend or a healthy endpoint do not create an attestation. Only a live positive Forge classification does.

**Session key** (`OwnedWebUISession`, `src/api/webui_identity_attestation.py`), all of which must match by identity/equality:

| fact | source (read-only from the existing authority) |
| --- | --- |
| manager object | `get_global_webui_process_manager()` compared by object identity (a replacement manager is a new session) |
| process object | `manager.process` compared by object identity (PID reuse is a new launch) |
| PID | `manager.pid`, which must equal `process.pid` |
| readiness epoch | `manager.ready_epoch` (>= 1): every startup or owned restart publishes a new epoch |
| endpoint | `manager.endpoint`, which must equal the probing client's `base_url` (trailing slash/case ignored) |
| declared identity | `manager.runtime_identity`, which must be `forge_webui` to establish |
| ownership + liveness | `manager.owns_process` and `manager.is_running()` must both hold, or there is no session |

**Establishment.** A live positive Forge probe attests the session only if the facts read before and after the probe are the same
launch (a probe that straddled a restart proves nothing). The attestation is one in-memory slot: never persisted to settings,
SQLite, NJRs, files or history.

**Invalidation.** Dropped immediately on: any session-fact mismatch (epoch, PID, process, manager, endpoint, ownership, liveness);
a positive A1111 classification; evidence that contradicts Forge; and a live Forge classification for a different or unowned
session. A dropped attestation is never resurrected (for example by ownership returning); a fresh positive proof is required.

**Contradiction always wins.** Positive A1111, an A1111-style `/sd-vae` list, or readable `/options` with no `forge_*` key is
positive evidence against Forge: the stage is rejected and any attestation dropped. Only *missing* evidence is a transient gap.

**External runtimes stay strict.** An external/unowned endpoint has no session, so it can never be attested or reuse an
attestation: live positive Forge is accepted per the existing policy, `unknown` and A1111 are rejected. The identity logic never
starts, stops, adopts or restarts a process; `RuntimeTransitionCoordinator` is unchanged.

**A1111 unchanged.** A1111 still tolerates an unclassifiable endpoint and still rejects a positively identified Forge through
`assert_runtime_matches_backend`. Its observations only ever invalidate (or, for a positive Forge on an owned session, establish)
the attestation.

## Initial identity-establishment settle

A first physical acceptance showed the other half of the same failure class: the owned managed Forge was READY (general
readiness proven, epoch 1) but could not yet be positively classified (`/sd-modules` readable; `/options`, `/sd-vae` and
`/cmd-flags` unavailable), and the first Forge stage would have been refused although the attestation had nothing to carry.
The settle bridges only the gap between "general readiness proven" and "enough endpoint evidence to classify Forge". It does
not weaken the rule that every managed session needs one real positive classification before any attestation exists.

It runs, inside `verify_backend_runtime_identity`, only when ALL hold: the backend is `forge_webui`; the authoritative manager
exists, owns the live process, declares `forge_webui`, serves the client's endpoint and has readiness epoch >= 1; the session has
no valid attestation (never proven, or its proof was dropped by a restart); the live classification is `unknown`; and the gap is
missing/incomplete/malformed evidence (`complete_endpoint_loss`, `options_unavailable|malformed`, `sd_modules_unavailable|malformed`).
Positive A1111, an A1111-style `/sd-vae` list or readable `/options` without Forge keys are contradictions: they reject at once,
never settle, and drop any stale proof.

* **Bound:** `INITIAL_IDENTITY_SETTLE_SECONDS = 8.0`, polled every `INITIAL_IDENTITY_POLL_SECONDS = 0.5` (at most 16 further
  probes); the last sleep is clamped to the remaining time. Clock and sleeper are injectable, so tests never wait. A probe already
  in flight is not interrupted, so wall time can exceed the bound by at most one probe. It re-runs the same read-only identity
  probe: no generation endpoint and none of the HTTP retry machinery is involved.
* **Revalidation:** before every further probe, and again after it, the session facts (manager and process objects, PID, endpoint,
  readiness epoch, ownership, liveness) are re-read; any change aborts at once as `session_changed` and discards even a positive
  result that straddled the change. Only a real positive classification of the unchanged session ends the settle successfully and
  establishes the attestation.
* **Exhaustion** leaves the original refusal (`no_valid_attestation` or `session_changed`) in place; a manager declaration, ownership
  or a healthy port never converts it into Forge.
* **Never again:** once the session has an attestation, a transient `unknown` uses the same-session attestation and is not re-polled.
  External/unowned endpoints and A1111 get no settle at all.

`IdentityDecision.settle` (`IdentitySettleReport`) records `outcome` (`initial_identity_established`,
`initial_identity_settle_timeout`, `initial_identity_settle_contradiction`, `initial_identity_settle_session_changed`,
`initial_identity_settle_ineligible_evidence`), attempts, elapsed and bound seconds and the latest gap. It is logged once per settle
and appended to a rejection message; no payloads are kept.

## Diagnostics

`IdentityDecision` (`WebUIFamilyImageBackend.last_identity_decision`, and appended to a rejection message as
`[identity: source=..., observed=..., gap=..., pid=... epoch=... endpoint=...]`) reports the **source**:
`live_positive`, `same_session_attestation`, `no_valid_attestation`, `contradictory_identity`, `session_changed`
(`not_applicable` for a non-Forge backend). `identity_gap()` classifies why an endpoint was not positive:
`complete_endpoint_loss`, `options_unavailable`, `options_malformed`, `sd_modules_unavailable`, `sd_modules_malformed`,
`conflicting_sd_vae`, `options_without_forge_keys`. Classification evidence gains `any_forge_option` and a per-endpoint
`endpoint_state` (`ok` / `unavailable` / `malformed`); no raw payloads are kept. Reuse of an attestation is logged once per
session; establishment and invalidation are logged once each.

## Not changed

No generation retry, backoff or `retry_policy_v2` change (the only waiting is the bounded initial settle above); no Forge/A1111 change;
no queue/SQLite/shutdown/GUI change; `WebUIProcessManager` gained no classifier and no new API (it already exposed every fact);
no controller file was touched, so no ratchet ceiling moved.

## Validation

`tests/api/test_managed_forge_initial_identity_settle.py` (38 deterministic fake-clock tests: unknown-unknown-Forge establishes once and
dispatches only afterwards, exhaustion, contradiction, each session fact changing between attempts and during a probe, a restarted
session settling on its own, external/A1111 getting zero settle, no re-poll after establishment, diagnostics) and
`tests/api/test_managed_forge_identity_attestation.py` (45 deterministic tests: same-session reuse, first-unknown reject, restart/epoch,
PID, process object, endpoint, client/manager endpoint mismatch, ownership loss, not running, manager replacement, no manager,
raising manager, positive A1111, contradictory evidence, external endpoints with and without a prior owned attestation,
no lifecycle mutation, A1111 semantics, two-job `PipelineRunner` shape, real `WebUIProcessManager` facts, diagnostics). Every
rejection case also asserts no generation dispatch. Existing identity, lifecycle, runtime-transition and Forge canonical-path suites
stay green. No network, GPU or generation is used.

## Physical acceptance (separate owner authorization required; not part of this package)

Bounded, non-generating, against the normal managed Forge only: confirm no unrelated StableNew/Forge process; start or use the
StableNew-owned runtime; record manager ownership, PID, endpoint and readiness epoch; establish a real positive Forge
classification; confirm the attestation is bound to that session; perform one owner-authorized managed restart; confirm the new
epoch/PID rejects an `unknown` probe until a fresh positive classification; stop only the owned runtime; confirm port/process
cleanup. No image generation, model load or upgrade; no external process is touched. A real failure showing the earlier `unknown`
was an actual process replacement or endpoint switch is a stop condition, not something to mask.
