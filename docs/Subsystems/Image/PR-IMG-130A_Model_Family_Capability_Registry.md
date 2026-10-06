# PR-IMG-130A - Model-family capability registry and dynamic image UX foundation

Result class: **BOUNDED FOUNDATION (Standard)**. No backend, model family, prompt translation, PromptPack, Learning, queue or
runtime change. The canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.
Execution Profile: Claude Code Sonnet 5.5 High.

## Owner outcome

One capability-aware image-model policy layer replaces the Klein-only GUI branch, so SDXL, Klein and future qualified families
are presented from policy rather than from per-family GUI code, while the exact immutable Klein profile stays the executable
authority.

## Concepts (kept distinct)

| concept | owner | example |
| --- | --- | --- |
| A. backend/runtime identity | configuration, `WebUIProcessManager` | `forge_webui`, `a1111_webui` |
| B. broad model family | exact profile first, else `AssetRegistry` evidence | `sdxl`, `flux2_klein`, `unknown` |
| C. exact qualified executable profile | `forge_klein_profile.py` (immutable, versioned) | `flux2_klein_4b_fp8@v2` |
| D. capability / operator policy | `model_policy.py` (`ModelPolicy`) | configurable vs fixed controls, feature support, hooks |

`ModelPolicy` is a read-only projection. It is not an executor, compiler, scanner or hash authority, and it never selects or
switches a backend. `src/learning/model_profiles.py` (learning/style priors) is a different concept and is documented as such,
not merged or renamed (sidecars untouched).

## The policy (`src/image_backends/model_policy.py`)

Pure, no I/O at import. A policy states: family and display identity; allowed/required backend; the exact profile reference
when one exists; stages and qualified modes; per value control (sampler, scheduler, steps, CFG, VAE, geometry) one of
**configurable / fixed / unsupported** (geometry may be a restricted choice: the qualified sizes, first = default); per feature
(negative prompt, prompt optimizer, embeddings, LoRA, hires, refiner, ADetailer, ControlNet, upscale) one of
**supported / unsupported / unverified** with an optional limit and a *reference* to an existing compatibility policy (the Klein
LoRA admission) rather than a copy of its rules; `prompt_dialect` guidance; an operator note; and a derived
`learning_variables()` query (unrestricted configurable controls plus LoRA strength where supported) as the hook for
PR-LEARN-130D.

Resolution (`resolve_model_policy`):

1. the **exact Klein transformer name** resolves to the current qualified profile first (whole-name match, never a substring;
   a lookalike name stays unclassified; family evidence is not even consulted);
2. otherwise a cheap injected `family_lookup` over `AssetRegistry`'s **persisted snapshot only** (`RegistryFamilyLookup`: no
   scan, no hashing, no network; disagreeing records are reported conflicting): resolved SDXL -> the SDXL policy; other resolved
   families (SD1/SD2/SD3/generic FLUX) are labelled but never qualified; unknown or conflicting evidence stays
   `unknown` (evidence class `unknown_evidence` / `conflicting_evidence`), absent evidence `no_evidence`;
3. nothing is ever guessed as SDXL.

Initial policies: **Klein** projects the accepted v2 semantics exactly (Forge required; Euler, Beta, 4 steps, CFG 1.0 fixed;
the two qualified geometries; no standard negative prompt, optimizer, embeddings, hires, refiner, ADetailer, ControlNet or
upscale; one explicitly Klein-4B-compatible LoRA; v1 admits none). **SDXL** keeps every control configurable and the features
StableNew's image path already has (it exposes no ControlNet), and claims no exact qualification. **Unclassified/other
families** keep today's generic WebUI usability (controls configurable) with every optional feature `unverified` rather than
supported or unsupported, so nothing is claimed and nothing is narrowed.

## Compiler

`apply_model_compile_policy` is the single compile entry used by the CLI, matrix and PromptPack builders. It freezes the
selected model's exact profile semantics (today the unchanged `apply_klein_compile_policy`; a golden test pins equivalence) and
is a no-op for models without a qualified profile. Profile-version persistence, pre-dispatch validation/rejection, replay and
NJR immutability are untouched: a persisted v1 NJR stays v1, a persisted v2 stays v2, new work stamps the latest version. The
GUI is advisory; the compiler and backend independently enforce the profile.

## GUI projection

`src/gui_v2/model_policy_projection.py` (pure) and `src/gui/model_policy_panel_projection.py` (Tk glue) replace the
Klein-specific modules. Selecting a model re-projects the controls: fixed values are written and the control disabled,
restricted geometry limits the preset list (snapping to the first qualified size only when the current size is not allowed),
unsupported controls are disabled without rewriting their persisted value, the policy note and any backend mismatch message
are shown in the helper line, and the Klein LoRA annotations still use the same admission decision as the backend. The
configured backend is only read to explain a mismatch; it is never switched.

**Draft state for any number of families.** The operator's working values are snapshotted exactly when they are about to be
overwritten, on a transition from an unconstrained model into a constrained one, keyed by the family left; constrained ->
constrained moves never overwrite it. Selecting an unconstrained model again restores that family's draft (consumed), else
the most recent working values (older drafts are then dropped as stale). Moves between unconstrained models leave values
untouched, as before.

## Seams for later packages (read-only)

`ModelPolicy.prompt_dialect`, `feature("negative_prompt" | "prompt_optimizer" | "embeddings" | ...)`, `family`/`profile_ref`
and `learning_variables()`. Nothing rewrites a prompt, changes PromptPack storage, or alters Learning recommendation semantics.

## Not changed / limits

* Only the Base Generation panel consumes the policy. Feature capabilities (negative prompt, optimizer, hires, ...) are exposed
  but their other-tab projections are deferred (Prompt-tab and Learning redesign are out of scope).
* The default family lookup loads the registry's persisted cache once per process on first use; a registry refreshed by another
  component after that is not seen until restart (a stale or empty cache can only make the projection more conservative).
* A partially constrained family locks only the controls its policy constrains; none exists yet beyond test doubles.
* No new backend, model, download, Diffusers/Comfy image path or backend auto-switch.

## Validation

`tests/image_backends/test_model_policy_130a.py` (resolution, exact-profile precedence, v1/v2 policies, unknown/conflicting
evidence, snapshot-only lookup, no scan/hash/network, compiler equivalence and entry points) and
`tests/gui_v2/test_model_policy_panel_130a.py` (SDXL unchanged, Klein fixed values, round trips, more than two families, repeat
switching, partial/unsupported controls, helper text, no backend switching). Existing Klein profile/LoRA/GUI, Forge backend,
compile-policy, canonical-path and SDXL suites stay green. No generation, GPU or network is used.
