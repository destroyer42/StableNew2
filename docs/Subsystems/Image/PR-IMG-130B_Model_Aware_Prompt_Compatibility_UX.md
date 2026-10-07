# PR-IMG-130B - Model-aware Prompt compatibility UX

Result class: **BOUNDED UX / DIAGNOSTICS (Standard)**. Compatibility *awareness* only: nothing here translates, rewrites or
converts a prompt. The canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.
Execution Profile: Claude Code Sonnet 5.5 High.

## Owner outcome

The Prompt tab understands the currently selected image model and truthfully adapts its presentation, guidance and
compatibility diagnostics from the canonical `ModelPolicy` (PR-IMG-130A), for ordinary SDXL and the qualified FLUX.2 Klein 4B FP8
profile, without another set of Klein-specific GUI branches.

## Authorities (unchanged)

`ModelPolicy` stays the capability/operator-policy authority; the immutable Klein profile stays the exact executable authority;
`AssetRegistry` stays the model/asset evidence authority; the compiler and backend stay authoritative even if this projection is
wrong or bypassed. There is no second family detector, asset scanner, prompt compiler, backend selector or LoRA resolver.

## Design

**Pure analysis** - `src/prompting/prompt_compatibility.py`. `project_prompt_target(policy, model_name, PromptStateSnapshot,
lora_resolver=...)` is deterministic, I/O-free and mutates nothing. It returns an immutable `PromptTargetProjection`: target
label, family/profile reference, prompt dialect, feature applicability (optimizer available, embedding additions allowed,
negative prompt supported), operator guidance, notes, and `PromptFinding`s (stable `code`, `severity`, `scope`, `message`,
count-only `details`; `to_dict()` for PR-IMG-130C). Severity: `action_required` is reserved for exact qualified-profile limits
the backend rejects; syntax/style patterns are `advisory`; informational notices are `info`.

**LoRA** - `src/image_backends/model_policy_lora.py` (`assess_lora_selection`) is the one place the policy's reference to the
existing PR-IMG-117 admission (`evaluate_klein_loras`) is dispatched; the Base Generation projection and the Prompt analysis both
call it. The Prompt analysis counts the slot LoRAs **plus an applied pack-level Style Consistency LoRA** (it becomes an executable
`<lora:...>` token), so a slot LoRA plus an applied style LoRA is reported as exceeding Klein's one-LoRA envelope. Nothing is
removed; findings carry counts, never LoRA names.

**Presentation** - `src/gui/prompt_target_presenter.py` applies the projection to the Prompt tab (banner, guidance/findings line,
negative/optimizer/embedding notes, control availability). `PromptTabFrame` keeps authoring state only and exposes
`on_model_projection(...)`; it reads the selected-model context from the existing 130A `ModelPolicyPanelProjection` through a
generic read-only `add_listener` seam (`main_window_v2._wire_prompt_model_target` is thin wiring; no `AppController` change).

## Behaviour

* **Target display**: `Prompt Target: SDXL — <checkpoint>`, `Prompt Target: FLUX.2 Klein 4B FP8 — profile v2`,
  `Prompt Target: Unclassified — <checkpoint> — capabilities unverified` (`evidence conflicting` when evidence conflicts). The profile
  comes only from the policy; unknown/conflicting evidence is never guessed as SDXL or Klein.
* **SDXL**: unchanged (no findings, nothing disabled, optimizer preview as before).
* **Qualified Klein**: natural-language guidance; the positive editor stays editable and untouched; the negative editor stays
  visible, editable and removable with an "unsupported" note and an `action_required` finding while non-empty (the text is never
  cleared); Prompt Optimizer controls are disabled and the preview states it is not applied (stored settings untouched, restored
  exactly on switching back); embedding **additions** are refused while existing entries stay visible and removable, with an
  `action_required` finding while any are selected; LoRA findings come from the existing admission evidence.
* **Global negative**: where the target's policy disables negative prompts, a stored non-empty global negative is kept exactly as set
  but is shown as `Global Negative: stored but not applied for <model>.` instead of "appended" (the text is never repeated), with an
  informational `global_negative_not_applied` finding (never `action_required`: the qualified compile policy deliberately disables
  global terms). Where negatives are supported the preview is unchanged.
* **Unknown / unqualified**: an informational unverified notice; every Prompt tool behaves as it always has.
* **Templates and Matrix** stay available and unchanged; the analysis reads the current rendered prompt (template + free text) and
  does not expand Matrix values.
* **Dialect diagnostics** (natural-language targets only, advisory, never blocking): explicit weighted-attention syntax
  `(phrase:1.2)`, the upper-case A1111 `BREAK` separator, and a run of at least 3 distinct quality-tag boilerplate terms
  (`QUALITY_TAG_THRESHOLD`). `<lora:...>` tokens and `[[matrix]]` markers are not prose; a lone ordinary phrase never fires.
  Messages say the prompt is preserved; there is no "Adapt" action (a later package).
* **No scan from a model switch**: the compatibility analysis and `on_model_projection` never resolve the Style Consistency selection
  (resolving may scan LoRA directories). They read the last resolution recorded by the existing, separate Style Consistency availability
  path (which keeps its behavior, including its scan). A selected style that has not been evaluated yet is reported as
  `style_lora_not_evaluated` (informational, only for bounded/unsupported LoRA targets) rather than counted or silently treated as valid.
* **Non-destructive**: a model switch never writes the pack (dirty flag unchanged) and never touches slot text, negative text,
  optimizer settings, embeddings, LoRAs, style selection, template or Matrix state.
* **Content visibility**: findings are derived from the real stored text but are suppressed for content the visibility mode hides
  (one generic notice instead); no finding contains prompt text, embedding names or LoRA names.

## Not changed / limits

* `StyleLoRAManager._infer_model_family` (a filename heuristic that decides whether a style LoRA is "applied" for the pack's base
  model) is **not** used as the target authority and is unchanged; it only determines whether the style LoRA counts as applied. It is
  recorded as non-blocking debt; exact executable Klein admission still decides runnability at the backend.
* No prompt/PromptPack schema or load/save change; no Learning change; no conversion either direction; no new backend or model.
* The default LoRA resolver is the cache-only `RegistryLoraResolver` (persisted snapshot; no scan/hash on the Tk thread).
* Matrix values are not expanded for dialect analysis.

## Validation

`tests/image_backends/test_prompt_compatibility_130b.py` (pure: SDXL, exact Klein v2, unknown/conflicting, synthetic future policy,
dialect patterns and thresholds, negative/embeddings/LoRA/style-LoRA, no mutation, no content leakage, no scan/hash/network, no
filename conditional) and `tests/gui_v2/test_prompt_target_130b.py` (Tk: banner, SDXL unchanged, Klein guidance, negative
preservation/removal, optimizer availability and preview, embeddings, LoRA/style-LoRA, round trip, templates/Matrix, content
visibility, synthetic policy, wiring). The PR-IMG-130A, PR-IMG-117, Prompt-tab layout, optimizer, Matrix, content-visibility and
PromptPack suites stay green. No generation, GPU, network or user-data mutation.
