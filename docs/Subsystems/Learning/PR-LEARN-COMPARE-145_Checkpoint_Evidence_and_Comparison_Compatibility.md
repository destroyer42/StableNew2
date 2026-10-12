# PR-LEARN-COMPARE-145 — Persistent Checkpoint Evidence and Cross-Model Comparison Compatibility

## Execution Profile + Model/Reasoning Recommendation

Standard, identity/cache-sensitive work. Recommended Claude Code: Sonnet 5.5 High; Codex: GPT-6.1 Sol High. Preferred
host: Local/Desktop, because the Windows cache-path and file-fingerprint diagnosis can only be done on the machine that
owns the installation. Escalate to XHigh only for a genuine model-policy or identity-authority ambiguity (one is
recorded below as an owner decision).

## Controller Surface Assessment

No ratcheted `src/controller/*` file changed. `LearningController` is untouched (it only forwards to
`prepare_comparison_evidence` and `build_plan`). The work is in `src/assets/` (registry authority),
`src/learning/model_evidence_readiness.py` / `model_comparison.py` (small extractions) and
`src/image_backends/model_policy.py` (two derived properties).

## Defects and findings

### 1. Repeated multi-GB reads — what was and was not reproducible

A genuine two-process lifecycle (`tests/assets/test_checkpoint_evidence_persistence_145.py`, real `python -I -c`
children, temporary registry, instrumented `hashlib.sha256` and binary reads) shows that **an unchanged SDXL
checkpoint is not re-hashed by a second process** on the code before this change: the plain cold-then-warm restart
already reused the persisted digest and read only the bounded header. The defect is therefore not "the cache never
persists". Code-level mechanisms that *can* cost a full read were found and are now explicit and tested:

| Cause | Needs a full SHA-256 read? | Before | Now |
|---|---|---|---|
| No entry (cache lost, workspace/root moved, path spelled differently) | yes | silent | `no_entry` + `cache_state` |
| Different size / `mtime_ns` / kind | yes | silent | `size_changed` / `mtime_changed` / `kind_changed` |
| Entry without a valid digest | yes | treated as a hit (digest silently missing) | `digest_invalid`, rehash |
| Structure contract bump or pre-structure (v1) cache | **no** — header re-read | worked, invisible | `structure_stale`, counted, no hash |
| Sidecar edited/added/removed | **no** — sidecar re-read | worked, invisible | `sidecar_changed`, counted, no hash |
| Transient read failure (another process replacing the file, scanner holding it) | yes, *wrongly* | read error = empty cache = rehash everything | bounded retry, then `unreadable` |
| Non-object JSON cache | crash (`AttributeError`) | uncaught | `unreadable` |
| Unreadable / future-schema cache overwritten on first save | n/a | evidence silently destroyed | kept once as `*.unreadable` |
| `os.replace` refused while the file is held open (Windows) | n/a | refresh failed after hashing | bounded retry |
| Exact profile (Klein) | n/a | excluded from hashing by a Klein-only name test | policy-driven, see below |

`checkpoint_is_current()` returns false for more than one reason; only the first group above actually requires
rehashing. A header/sidecar-only invalidation never rehashes, and this is now asserted (`hashes_computed == 0`,
`bytes_hashed == 0`) rather than assumed.

### 2. Real Windows installation — not diagnosed in this session

This change was prepared on a cloud host that cannot see the owner's Windows workspace, so the requested read-only
inspection of the effective `WorkspacePaths.asset_registry_cache()`, entry count, exact resolved paths,
`mtime_ns`, sidecar fingerprints, publication conflicts and changed workspace roots was **not performed**. Nothing
about the installed cache or models was read or modified. `tools/diagnose_asset_registry_cache.py` performs exactly
that diagnosis read-only and path-free by default (no hashing, locking or writing):

    python tools/diagnose_asset_registry_cache.py --checkpoint "<exact served checkpoint path>"

It reports the cache's location label, parseability, schema version, entry and digest counts and, per checkpoint, the
miss reason, whether a full hash is actually required, whether the exact resolved path is cached, and whether the same
file name is cached under another path (the "moved workspace" signature). `asset_registry_cache()` is anchored to the
code checkout (`Path(__file__)…/state/asset_registry_v1.json`), so launching StableNew from a different checkout or
copy starts from a cold cache: this is the leading hypothesis to confirm with the tool.

### 3. Klein-only exception and SDXL-only study gates

`prepare_comparison_evidence` skipped checkpoint work for `is_klein_transformer_name` only, so an exact Z-Image
selection was fingerprinted, header-inspected and then **rejected by the SDXL-only structural gate**. Study eligibility
was likewise a literal `family == "sdxl"` test in two places.

## Changes

- `src/assets/cache_diagnostics.py` (new, pure): `CacheState`, `CheckpointMiss` (with `needs_hash` /
  `digest_reusable`), `CheckpointStatus`, `RefreshCounters`, `CacheDescription`. No path, file name or digest.
- `src/assets/registry.py` (still the sole identity/hash authority, same cache file, same lock): `checkpoint_status`
  (`checkpoint_is_current` delegates), `describe_cache`, `RefreshResult.counters`, `last_refresh`, `cache_state`;
  digest-validity is part of the reuse test; robust `_read_cache_file`; non-destructive `_save`. Hashing, cancellation
  per 1 MiB chunk, fingerprint re-check and the cross-process writer lock are unchanged.
- `ModelPolicy.exact_identity_authority` and `ModelPolicy.explicit_capabilities` (derived, not stored, so frozen policy
  contexts and old arms are unchanged).
- `model_comparison.candidate_ineligibility(policy)`: the single study-eligibility rule used by readiness and by
  `_require_candidate` (Preview and frozen Run). It reads policy content only.
- `model_evidence_readiness`: exact-profile authority is asked of the canonical policy, not of a name test; the
  structural diagnosis stays but the family decision goes through the policy; a one-line cost summary is reported.
- `tools/acceptance/img_forge_100_acceptance.py::intent_digest` ignores the freshly minted `batch_id` (fixes the
  baseline failure `test_smoke_a_then_b_complete_end_to_end_with_fakes_one_dispatch_each` introduced by
  PR-REVIEW-BATCH-200's per-submission random Review `batch_id`).

## Supported versus still unsupported (Model Comparison, `txt2img` arms)

| Candidate | Status | Basis |
|---|---|---|
| Standard SDXL base checkpoint | supported | registry metadata and/or structural evidence → `sdxl` policy |
| SDXL derivative (Pony, Lightning, Turbo, merges) **with SDXL evidence** | supported | same `sdxl` policy; evidence = metadata or LDM SDXL-base layout, never the file name |
| Exact FLUX.2 Klein, exact Z-Image | supported, cold and warm | exact profile is the identity authority; no hash, header read or SDXL gate |
| SDXL refiner / inpaint, conflicting, malformed, unreadable, unknown | rejected (fail closed) | unchanged |
| A file only *named* Pony/Lightning/SD15 without evidence | rejected | no filename inference |
| SD1 / SD2 / SD3 / unqualified Flux / Qwen with registry family evidence | **rejected — owner decision needed** | see below |

An "SDXL Lightning/Turbo" checkpoint runs under the ordinary SDXL policy, exactly as it does in the normal pipeline
today; no distilled-SDXL sampler/CFG/steps policy exists to adopt and none was invented.

## Owner decisions required (stopped, not invented)

1. **SD1/SD2 (and any other evidenced non-SDXL ordinary family).** `resolve_model_policy` labels them
   `unverified_generic:<family>` — every optional feature is `UNVERIFIED`, i.e. no qualification states what they can
   execute (native geometry, sampler/CFG ranges, VAE, hires, LoRA/embedding behaviour). Admitting them to comparisons
   would expand unknown-model execution on a policy that claims nothing. The gate is now policy-driven
   (`explicit_capabilities`): when the owner qualifies a family (for example an `sd15` `ModelPolicy` with explicit
   feature positions and geometry), it becomes eligible with no further study change. Options: (a) authorize a
   minimal, explicitly-scoped SD1.5 policy (native 512-class geometry choices, same prompt dialect, features
   marked unsupported unless qualified), (b) keep fail-closed (current), (c) allow a clearly disclosed "generic
   WebUI" tier for comparisons only.
2. **Per-file publication of finished digests.** Today a cancelled or failed Preview publishes nothing, so a completed
   multi-GB digest is discarded if the *next* selected file fails or the user cancels (PR-LEARN-142's accepted
   "cancelled hash publishes nothing" contract, pinned by `test_cancelled_hash_publishes_nothing_…`). Publishing each
   verified digest as it finishes would stop that loss but changes that contract; it was prototyped, conflicted with the
   accepted test, and was **not** adopted.

## Behaviour that is deliberately unchanged

- Size + `mtime_ns` remains the documented trust model: a same-size, same-mtime content replacement is not detected
  (pinned by a test so a change is deliberate). The WebUI legacy `hash` is never a SHA-256 substitute.
- Frozen Run performs no registry scan, hash, inspection, family lookup or adaptation; arm digests and frozen identity
  evidence are revalidated purely from the snapshot; admission is one `JobService.submit_njrs`.
- Controlled Variable studies, ratings, resume, results and the `target_envelope_preference` interpretation.
- No second cache, hash authority, database, scanner, detector, runner or startup checkpoint sweep.

## Validation

New deterministic tests (temporary safetensors fixtures only; no WebUI, Forge, GPU or installed model):
`tests/assets/test_checkpoint_evidence_persistence_145.py` (two real processes; size/mtime/same-fingerprint;
malformed/missing/old/future caches; sidecar-only and structure-only refreshes without a hash; invalid digest;
concurrent writers; cancellation leaves the cache byte-identical; path-free diagnostics; transient read/replace
retries), `tests/learning_v2/test_model_comparison_evidence_145.py` (exact Klein/Z-Image cold and warm; evidenced
SDXL derivatives; filename-only rejection; evidenced non-SDXL fail-closed; unknown/conflicting/malformed; mixed
SDXL/Z-Image and SDXL/Klein studies; geometry/backend/control rejection of the whole study; frozen Run with every
registry entry point disabled and exactly one `submit_njrs`), `tests/tools/test_acceptance_intent_digest_145.py`,
`tests/tools/test_diagnose_asset_registry_cache_145.py`. Existing Learning, ModelPolicy, asset and readiness suites
were re-run unchanged.
