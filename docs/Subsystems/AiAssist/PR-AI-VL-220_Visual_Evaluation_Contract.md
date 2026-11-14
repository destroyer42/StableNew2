# PR-AI-VL-220: visual evaluation contract (specification and harness scaffolding)

AI-VL-230 adds the operator-only driver and the Gemma candidate. The [operator runbook](../../runbooks/ai_visual_evaluation.md)
covers staging, readiness, and supervised evaluation.

The original LFM plan digest was
`23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e`.
The LFM plan printed by `python -m tools.qualification.vl220 describe` changes only the invocation approval bit and has digest
`9d6fbdfd6d2fa2dd5af7edb37ef7810286b3fed9dc7a598685db7d3f6223d5b5`.
The plan retains the original upstream archive identity and comparator snapshot. `describe-execution` binds the exact visual
build, executable, launch profile, and resource limits for a supervised run.

## 1. Purpose and boundary

Compare the vision-language candidates with existing capabilities on StableNew-shaped questions. The operator tool validates
the frozen cases and labels, runs the pinned CPU adapter when admitted, and scores the responses against the reference
labels and deterministic floors. The application has no entry point to the adapter.

## 2. What is measured

| Dimension | Case kind | Question put to a system | Deterministic score |
|---|---|---|---|
| Prompt adherence | `adherence` | For each listed element, is it visible? | Fraction of element answers equal to the label |
| Anatomical defect triage | `defect_triage` | List every anatomical defect (region, category, severity); empty means none | Precision and recall of `(region, category)`; false-alarm rate on clean cases |
| Multi-subject consistency | `consistency` | Two panels: is each subject unchanged? | Fraction of per-subject answers equal to the label |
| Before/after usefulness | `before_after` | Which of images a and b is more useful for the prompt, or a tie | Agreement with the human preference |
| Hallucination | `describe` | List the objects you can see | Unsupported-mention rate (mentions neither in the reference objects nor their listed synonyms) and object recall |
| Structured output | all | Answer in the closed response schema | Valid, refused and invalid rates, invalid reasons by stable code; an invalid answer scores as wrong, never skipped |
| Memory and runtime limits | all | (measured, not asked) | Per-case wall time, peak working set, context tokens, CPU-only, against `ResourceLimits` (proposed 180 s, 6 GiB, 4096 tokens, CPU only; owner-tunable) |

Closed vocabularies live in `contract.py` (regions, defect categories, severities, preferences and reasons). Free text is
limited to element texts in a case and object names in an answer (at most 40 characters).

## 3. Cases, labels and assets

* **Cases** (`stablenew.vl220.cases/1`) carry the question and pinned assets (asset id, SHA-256, size, origin, media type) and
  **no reference data**: a recursive key check refuses `reference`, `label`, `answer`, `answers`, `expected`, `preferred`,
  `solution`, `ground_truth` and `truth` anywhere in a case.
* **Labels** (`stablenew.vl220.labels/1`) are a separate document keyed by case id, covering exactly the cases. The labeler is
  `human` or `synthetic_by_construction`; **any case set that uses an existing (non-synthetic) asset is refused unless the
  labels are human-written.** Labels are stored apart from the images and never sent to a model.
* **Synthetic assets** (`synthetic.py`): a fixed table of squares, circles and stick figures with wrong limb counts, encoded as
  uncompressed PNG so every byte and hash is identical on every machine; 13 cases covering every kind. Their labels follow from
  how the scene was drawn. They exercise the wiring only; **they say nothing about real generated images.**
* **Existing assets** (the owner's generated outputs) are the real test. Which images and who labels them is an owner decision
  (section 7); the contract only fixes the format and the refusal rules.

## 4. Response contract

One schema id (`stablenew.vl220.response/1`) with two branches, like the AI-202c suggestion schema: an `ok` branch with the kind
and its payload (all fields required, closed objects) and a `refused` branch with `refusal_reason` (at most 400 characters). The
document that stalled the text models, a bare `schema` and `status`, matches neither branch. `build_response_schema(kind)` emits
the JSON Schema a constrained decoder would receive; it uses only keywords the AI Assist grammar proof already covers (`oneOf`,
`const`, `enum`, `required`, `properties`, `additionalProperties: false`, `type`, `items`, `minItems`, `maxItems`, `maxLength`).
`validate_response` is the authority and is never looser than the schema; a test checks both on the same documents. The grammar
guarantees structure, not truth: a well-formed wrong answer is scored as wrong.

## 5. Comparators

| Comparator | Eligible | Dimensions | Why |
|---|---|---|---|
| Deterministic floors (all-yes, all-no, seeded random) | yes | all except resources | The minimum any system must beat |
| Smart Review caption adapter (Florence-2) | yes, partly | hallucination | Existing PR-IMG-REVIEW-320 child process (torch/transformers, CPU, offline). Free-text captions only: no structured output, no defect triage. Needs its catalog resource verified |
| Smart Review segmentation (SAM2) | no | none | No text output |
| Qwen3.5 text GGUFs | no | none | Registered as text models; no projector is registered and `--mmproj` is in `FORBIDDEN_FLAGS` |
| LFM3-1.7B text GGUFs | no | none | The language model has no vision encoder |
| LFM3-VL-2B candidate | not yet | all | Operator prerequisites apply. See the evaluation runbook. |

The audit found **no existing eligible vision-language capability that answers structured questions**; the Qwen3.5 models may be
multimodal upstream, but StableNew registers and runs them as text only, so a Qwen visual arm would need its own projector pin,
license review and the same invocation approval. That is a possible later comparator, not part of this package.

## 6. Reporting rules

A report states per dimension the number of cases, the score, and the floors beside it; never an aggregate "quality" number.
Hallucination, structured-output validity and resource violations are hard gates reported separately, not averaged into
quality. A result is evidence for StableNew only on existing assets with human labels; the synthetic set is a wiring check.
Nothing in a report sets `qualified`.

## 7. Owner decisions this contract needs before a real run

1. Review the exact supervised execution, case and label digests.
2. Acknowledge the exact license text (`30adf9d6...`; section 3 of the work package).
3. Choose the existing assets and the person who labels them (minimum suggested: 30 cases per kind).
4. Confirm the proposed limits and whether the Florence-2 comparator is in scope.
