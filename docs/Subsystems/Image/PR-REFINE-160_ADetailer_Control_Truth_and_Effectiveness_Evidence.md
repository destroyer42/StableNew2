# PR-REFINE-160 — Forge ADetailer control truth, default hand correction and effectiveness evidence

Status: LOCAL IMPLEMENTATION COMPLETE; hosted CI and review pending. Class: Standard, cross-file. Claude Code Sonnet 5.5 High /
Codex GPT-6.1 Sol High, Windows Local/Desktop. No GPU generation, model load, Forge launch or backend change was part of this
package.

StableNew must not claim an anatomical correction from a detection, a completed request or a pixel change. This package makes the
ADetailer controls match the pinned extension, defaults both passes on for **newly authored** work, fixes a precedence defect that
neutralized Adaptive Refinement for GUI-authored jobs, and records four separate outcomes per ADetailer stage.

## What the pinned ADetailer-Neo (`af228eba…`) actually does

Read from the managed runtime's extension source and the frozen schema fixture
(`tests/data/contracts/adetailer_neo_af228eba_schema.json`, `additionalProperties: false`):

* A pass argument dict that fails the schema is **dropped silently** (`get_args` logs and `continue`s): an out-of-range or unsupported
  value makes the pass vanish without an API error. `ad_mask_filter_method` accepts only `Area` or `Confidence`; CFG is bounded to 1-24.
* There is **no machine-readable detection result**. Detections are printed to the console only, so Forge YOLO detection counts are
  `unknown`. The one structured trace in the response is the `ADetailer model[ Nth]: <detector>` infotext line per accepted,
  non-skipped pass: it says settings were accepted, not that anything was detected.
* `ad_mask_k` ("mask only top k", 0 = keep all) is the supported region filter. There is no argument for a detection limit or for mask
  feathering.

## Defaults and compatibility

* New cards default **Face pass on and Hand pass on** (`FRESH_PASS_DEFAULTS`, one source: the card's initial variables). The card exports
  both flags (`enable_hands_pass` with the `ad_hands_enabled` mirror), so work authored from the GUI, including newly created PromptPacks,
  carries explicit values.
* The overall ADetailer stage flag is untouched. Explicit saved `true`/`false` values are honored. A saved or historical configuration that
  **omits** the hand flag keeps its historical meaning (hand pass off): the default is not merged into saved configs, the executor fallback is
  unchanged, and immutable NJR snapshots replay with their frozen values (tested through `to_queue_snapshot`/`from_dict`).
* Not changed: `src/utils/config.py` default template (it is merged *under* saved configs and would silently enable hands there), the
  curation face-triage builder (a face-specific workflow), the Photo Optimize tab and the legacy `adetailer_config_panel` (not wired).
  Unsupported model profiles (qualified Klein) still refuse ADetailer.

## Control truth

* Removed from the active card: **Max Detections**, face and hand **Mask Feather** (no extension argument). Historical saved values
  round-trip untouched through the card but are never presented as effective and never transmitted; the executor already built its
  arguments from supported keys only, now asserted against the frozen schema.
* `Mask Max-K` is **Retained Masks (Top-K)** (0 keeps every mask). Mask Filter offers `Area`/`Confidence` (the former `largest`/`all`
  values were rejected by the extension). CFG is capped at 24.
* Face and hand detector lists are separated by detector kind. Under Forge MediaPipe and body/person models are never offered; a saved
  selection that is not in the list is **kept and flagged, never substituted**. A one-line projection on the card shows which passes are on,
  their detectors, unavailable or wrong-kind detectors and any setting the schema would reject.
* The executor logs `[adetailer/contract]` warnings for a pass argument the pinned schema rejects (it does not block historical replays).

## Adaptive Refinement (YuNet) fidelity

`PipelineRunner._apply_adetailer_refinement_overrides` set the policy's confidence/min-ratio/padding at the stage's top level, but the
backend later flattens the stage's `extra` **over** it. GUI-authored jobs always carry those keys in `extra`, so the policy never reached
Forge. The override is now applied to a copy of `extra` as well. Only face keys are touched; hand settings are not. YuNet remains the CPU-side
Adaptive Refinement detector and Forge keeps its YOLO detectors. An unavailable or failed YuNet is `unknown`, never a confirmed absence of faces.

## Effectiveness evidence — `stablenew.adetailer-effectiveness.v1`

Built in `src/pipeline/adetailer_effectiveness.py` and written into the ADetailer stage manifest and result (existing artifact ownership; the
NJR is never modified). Four categories, never conflated:

1. **Detection** — Forge YOLO per region: `status: unknown`, `count: null`, with the reason above. StableNew's YuNet observation (status,
   count) is recorded separately and labelled as a refinement-policy observation.
2. **Execution** — per pass: requested state, detector, supported settings, schema issues, `acknowledged_by_extension` (true/false/unknown from
   the response infotext, attributed only by detector name) and the request-level completion. Both passes share one request, so completion is
   not independent proof of either.
3. **Observable image change** — the image sent to ADetailer versus its output, `pil_rgb_abs_diff/1` (identical flag, mean absolute difference,
   changed-pixel fraction), bounded to 64 MP; mismatched dimensions, missing files or decode errors are `not_comparable`, never "unchanged".
   Combined, not per pass; not a quality measure.
4. **Visual improvement** — `unreviewed` until an operator judges it.

`improvement_claimed` is always false. Prompts are not copied into the record.

## Operator review (existing Review tab and feedback record)

For an ADetailer output whose source is **verified** (embedded stage `adetailer`, an artifact input path that exists and differs from the
output), the Review tab enables an **ADetailer Before/After** button (the existing compare viewer, input on the left) and optional **Face** and
**Hands** judgments — Unreviewed (default), Improved, Unchanged, Worsened, Uncertain — plus a short note. The judgment rides in
`feedback["context"]` of the existing `save_review_feedback` call (`review_context` in the Learning record and the stamped portable
metadata), labelled a post-ADetailer assessment by region with operator provenance and the reviewed pair. The overall 1-5 rating stays the
operator's own input; no numeric quality is derived and nothing is promoted into Learning recommendations. Only the displayed image carries
a judgment (batch saves never inherit it), and the prompt-redaction policy is unchanged.

## Tests

`tests/pipeline/test_adetailer_truth_160.py` (contract against the frozen schema, evidence, executor dispatch), `test_adetailer_canonical_160.py`
(NJR snapshot → `run_njr` → executor → Forge args, adaptive precedence, YuNet states), `tests/gui_v2/test_adetailer_card_truth_160.py`,
`tests/review/test_adetailer_outcome_160.py` and `tests/gui_v2/test_review_adetailer_outcome_160.py`.

## Known limits

* Forge detection counts are unknown by construction; the infotext acknowledgement is not a detection. No reviewed improvement exists until an
  operator provides one; there is no controlled per-pass attribution.
* The effectiveness record lives in the manifest JSON (not the PNG); the Review tab reads the optional record only when the manifest sits beside
  the output.
* Invalid historical values (for example a saved `largest` filter) are flagged, not rewritten, so such a saved pass is still dropped by the extension.

## Controller surface assessment

No controller was touched: `AppController`, `PipelineController` and `PipelineRunner`'s size is unchanged apart from a nine-line precedence fix in a
static helper of `PipelineRunner`; the controller-surface ratchet is unchanged. New logic is in small pure modules
(`adetailer_contract`, `adetailer_effectiveness`, `review/adetailer_outcome`).

## Optional operator acceptance procedure (not executed; needs separate approval)

Run the unchanged workflow on a small, bounded set of real images — one close portrait, one partial-body, one full-body, one multi-subject —
with both passes on. For each result, read `adetailer_effectiveness` in the manifest (acknowledgement, pixel change), open **ADetailer
Before/After**, and record Face and Hands judgments. Tabulate separately: acknowledged passes, measurable change, and operator-rated
improvement. Four images are a smoke check, not a statistic; report counts, not percentages, and make no claim of significance.
