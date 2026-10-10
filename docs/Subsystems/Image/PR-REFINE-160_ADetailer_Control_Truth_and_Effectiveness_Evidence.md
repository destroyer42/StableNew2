# PR-REFINE-160 — Forge ADetailer control truth, default hand correction and effectiveness evidence

Status: COMPLETE / ACCEPTED (PR #81; hosted `required` and `affected` passed, independent reviews found no blocker). Class: Standard, cross-file. Claude Code Sonnet 5.5 High /
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
* Not changed, deliberately: the `src/utils/config.py` default template gains **no** pass defaults (it is merged *under* saved configs and
  would silently enable hands there); its only edit is removing the unsupported `adetailer_mask_feather` default; the curation face-triage builder (it copies a source configuration, so it is historical); and the **Photo Optimize** and **Review
  reprocess** paths. Those are wired: they author their own face-only ADetailer configuration (`AppController._build_reprocess_config`,
  `ReprocessJobBuilder`) with no pass toggles, so their hand pass stays off exactly as before. Giving them a hand pass changes the work those
  workflows perform with no operator control, and would grow a ratcheted controller; that is an **owner product decision**, not made here.
  Unsupported model profiles (qualified Klein) still refuse ADetailer.
* A card loaded from an empty or absent `adetailer` section stays in its fresh state (hands on); a saved configuration with an `adetailer`
  section that omits the flag loads as hands off. Known debt: a legacy pack with the stage enabled but no `adetailer` section would show the
  fresh state and export explicit values on its next GUI submit.

## Dispatch rules (fail closed)

* **No pass requested.** If neither pass is requested the extension is a no-op, but WebUI would still run the stage's whole-image img2img at the
  stage denoise strength. The executor therefore sends **no generation POST**, passes the input image through unchanged, and records
  `dispatched: false` with the reason; the card projection says "No correction will run".
* **Schema-rejected pass.** The extension drops a pass whose arguments fail its schema without any error. A requested pass the pinned schema
  would reject (for example a saved `largest` mask filter or CFG above 24) is refused before dispatch with an error naming the issue, rather
  than running a degraded or plain-img2img request. Frozen NJRs are not rewritten, so a historical job with such a value is refused too; a value
  on a disabled pass is ignored.
* **Legacy filter values.** When the card loads `largest`/`all` (never accepted by the extension) it shows `Area` with a visible note.
* **Scope of "no request".** Both guards run after the stage-start event, the pressure and runtime-admission checks and, on the default
  (non-request-local) path, a model/VAE synchronization. "No request" therefore means **no generation POST**: those preliminary checks and
  a model/VAE sync (normally a read, because the model already matches) can still happen for a stage that is then skipped or refused.

## Control truth

* Removed from the active card: **Max Detections**, face and hand **Mask Feather** (no extension argument). Historical saved values
  round-trip untouched through the card but are never presented as effective and never transmitted; the executor already built its
  arguments from supported keys only, now asserted against the frozen schema.
* `Mask Max-K` is **Retained Masks (Top-K)** (0 keeps every mask). Mask Filter offers `Area`/`Confidence` (the former `largest`/`all`
  values were rejected by the extension). CFG is capped at 24.
* Face and hand detector lists are separated by detector kind. Under Forge MediaPipe and body/person models are never offered; a saved
  selection that is not in the list is **kept and flagged, never substituted**. A one-line projection on the card shows which passes are on,
  their detectors, unavailable or wrong-kind detectors and any setting the schema would reject.
* The executor **refuses** (fail closed, `[adetailer/contract]` error, no generation POST) a requested pass whose arguments the pinned schema
  rejects, including on replay of a frozen job; the job ends as a failed run (the specific reason is in the log, not the job result).

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

`improvement_claimed` is always false. Prompts are not copied into the record. `acknowledged_by_extension` means the extension echoed that
pass's accepted settings when the request was prepared; it is not proof the pass ran or detected anything. The image-change record states that
the stage's own whole-image img2img pass makes a difference expected.

## Operator review (existing Review tab and feedback record)

For an ADetailer output whose source is **verified** (embedded stage `adetailer`, an artifact input path that exists and differs from the
output), the Review tab enables an **ADetailer Before/After** button (the existing compare viewer, input on the left) and optional **Face** and
**Hands** judgments — Unreviewed (default), Improved, Unchanged, Worsened, Uncertain — plus a short note. The judgment rides in
`feedback["context"]` of the existing `save_review_feedback` call (`review_context` in the Learning record and the stamped portable
metadata), labelled a post-ADetailer assessment by region with operator provenance and the reviewed pair. The overall 1-5 rating stays the
operator's own input and is still required: a judgment-only save writes the default rating and sub-scores into the same Learning feedback
record the Review tab already writes (the recommender does not read the judgment). No numeric quality is derived from the judgment. Undo
removes the Learning line only; the stamped portable review metadata on the image is unchanged (pre-existing behavior). Only the displayed image carries
a judgment (batch saves never inherit it), and the prompt-redaction policy is unchanged.

## Tests

`tests/pipeline/test_adetailer_truth_160.py` (contract against the frozen schema, evidence, executor dispatch), `test_adetailer_canonical_160.py`
(NJR snapshot → `run_njr` → executor → Forge args, adaptive precedence, YuNet states), `tests/gui_v2/test_adetailer_card_truth_160.py`,
`tests/review/test_adetailer_outcome_160.py` and `tests/gui_v2/test_review_adetailer_outcome_160.py`.

## Known limits

* Forge detection counts are unknown by construction; the infotext acknowledgement is not a detection. No reviewed improvement exists until an
  operator provides one; there is no controlled per-pass attribution.
* The effectiveness record lives in the manifest JSON (not the PNG). `review/adetailer_outcome.load_effectiveness` can read it, but no GUI
  surface shows it yet.
* A frozen job whose requested pass carries a schema-invalid value is refused rather than repaired; it needs a new job.
* The infotext regex was checked against the extension source, not a captured Forge response.

## Controller surface assessment

No controller was touched: `AppController` and `PipelineController` are line-for-line unchanged; `PipelineRunner` grew by eight lines (the precedence
fix in a static helper) and `executor.py` by about sixty (evidence, guard); the controller-surface ratchet is unchanged. New logic is in small pure modules
(`adetailer_contract`, `adetailer_effectiveness`, `review/adetailer_outcome`).

## Optional operator acceptance procedure (not executed; needs separate approval)

Run the unchanged workflow on a small, bounded set of real images — one close portrait, one partial-body, one full-body, one multi-subject —
with both passes on. For each result, read `adetailer_effectiveness` in the manifest (acknowledgement, pixel change), open **ADetailer
Before/After**, and record Face and Hands judgments. Tabulate separately: acknowledged passes, measurable change, and operator-rated
improvement. Four images are a smoke check, not a statistic; report counts, not percentages, and make no claim of significance.
