# PR-AI-VL-242: two-tier evaluation contract for real images (`stablenew.vl220.eval/2`)

Status: **specified and tested on synthetic fixtures; no model has been run and no real image has been evaluated.** Gate set
`stablenew.vl242.gates/1`: **proposed, pending owner approval.** `qualified` stays false; this contract promotes nothing.

`eval/1` (`PR-AI-VL-220_Visual_Evaluation_Contract.md`, `contract.py`, the built-in synthetic sets and plan
`15d7ab2e...db536`) is unchanged byte for byte; a test pins its schema, set and plan digests. `eval/2` sits beside it for the
owner's real images. Code: `tools/qualification/vl220/eval2.py` (contract, gates), `review_export.py` (converter),
`eval2_scoring.py` (scorer) and `tools/qualification/vl242/` (statistics, floors, escalation, gates, plan, report, CLI).

## 1. Product use this contract makes testable

Two candidates, two roles, both advisory:

| Tier | Candidate | Role in Review |
|---|---|---|
| Fast | LFM3-VL-2B Q4_K_M + F16 projector (`lfm3-vl-2b-q4_k_m-liquidai`; about 4 s and 2.5 GB per image on CPU) | A cheap first look at the one image the operator selected |
| Deep | Gemma 4 12B QAT Q4_0 (`gemma-4-12b-it-qat-q4_0-google`; about 7 GB, never run) | Consulted on request, or when the fast answer warrants it |

Every answer is a closed list of findings in Review's own taxonomy that the operator confirms or rejects (roadmap Priority 2,
AI-REVIEW-410). The deep tier earns a place only with a measurable advantage over the fast tier on the same images (roadmap
Priority 5, AI-GPU-440). The questions are therefore: does the fast tier find real defects without crying wolf on clean
images; is the deep tier measurably better; and does a two-tier rule buy the deep tier's detection for less of its time?

## 2. Cases and labels from Review

* **Source.** A `stablenew.vl240.review_export/1` document (AI-VL-240) of operator-confirmed Review state. The converter reads
  only `provenance.labeler`, per image `image_id`, `sha256`, `width`, `height`, `clean_confirmed`, `findings[].category`,
  `findings[].region`, `findings[].confirmation` (if present) and `subject_count`, and per pair `pair_id`, the two image ids and
  `judgment`. It copies no other value: observation text, prompts, file names, paths and interventions never reach a case or a
  label. Case and asset ids are derived from SHA-256 digests.
* **Human labels only.** The export is refused unless `provenance.labeler` is `human`; `labels/2` has no other labeler value.
* **Image verdict.** `clean_confirmed` with no finding is a confirmed-clean image; at least one confirmed finding makes it
  confirmed-defective; both at once is refused; neither means not reviewed and the image is excluded (counted). A finding with a
  `confirmation` field counts only when it is `Confirmed`.
* **Prompt adherence findings are dropped** (counted): a real case carries no prompt, so a model cannot judge them, and an image
  whose only findings are prompt adherence is excluded (counted).
* **Regions.** Review's half-open pixel box becomes the 3 x 3 grid zones it occupies: a zone counts when it holds at least 10 %
  of the box's area, and the zone holding the box's centre always counts. A finding without a box (Review's whole-image
  finding) keeps "no region" and matches any answer region.
* **Ignored export content.** Every other key (for example `file`, `roles`, `record_ids`, `severity`, `intervention` and the
  `mixed_pairs` list of pairs whose region judgments disagree) is ignored and never copied.
* **What today's Review can supply.** AI-VL-240 reports that Review cannot yet record a clean confirmation or a subject count:
  `clean_confirmed` is always false and `subject_count` always null, and findings exist only for images the operator queued a
  guided correction for. **A real export today therefore has no confirmed-clean image and no subject reference**: clean false
  alarm, balanced accuracy, the floor gates and multi-subject consistency cannot be computed, and every gate that needs clean
  images reports `INSUFFICIENT_SAMPLE`. The planned set (20 clean, 10 multi-subject) needs Review to record both, a separate
  `src/` package, before the paired run.
* **Pairs.** Both images must be in the export and differ. Presentation alternates by sorted case id (before first, after first,
  ...), so a model that always prefers one position scores at chance; the case lists the two images in display order and only
  the label says which one is the corrected image.
* **Cases** (`stablenew.vl220.cases/2`) carry case ids, kinds (`image_review`, `pair_review`) and pinned assets (id, SHA-256,
  width, height). No prompt, label or text. **Labels** (`stablenew.vl220.labels/2`) are a separate document keyed by case id.
  Both are written outside Git (`python -m tools.qualification.vl242 convert` refuses a destination inside the repository).

## 3. Response contract (`stablenew.vl220.response/2`)

The earlier packages showed that an under-constrained schema yields invalid or minimal answers. Here every object is closed,
every field is required, every value is an enum and the only free length is a bounded list:

* `image_review`: `verdict` (`clean` or `defective`), `findings` and `subject_count` (`0` .. `4`, `5_or_more`). Two `ok` branches
  tie the verdict to the list: `clean` has exactly zero findings, `defective` one to six. A finding is `category` (Review's
  `Category` values imported from `src/review/findings.py`, minus `Prompt adherence`: `Face`, `Hands`, `Anatomy`,
  `Composition`, `Rendering artifact`, `General / local issue`) and `region` (`top_left` .. `bottom_right`, `whole_image`).
* `pair_review`: `answer` (`first_better`, `no_clear_difference`, `second_better`).
* A refusal is `refusal` from a closed list (`image_unreadable`, `declined`); there is no free-text refusal reason.
* The validator parses strictly (duplicate keys and `NaN` refused, 4 KiB limit), collapses repeated findings and never keeps any
  text. A test runs a minimal JSON Schema check and the validator on the same good answers and near misses.

The question texts are fixed in `eval2.py` and bound into the plan by digest.

## 4. What is measured

| Dimension | Score | Reference | No usable answer counts as |
|---|---|---|---|
| Image-level defect detection | Recall on confirmed-defect images; false-alarm rate on confirmed-clean images; F1; balanced accuracy | Image verdict | A miss on a defective image; "not cleared" (a false alarm) on a clean one |
| Finding-level triage | Precision and recall of findings under a maximum one-to-one matching (same category, compatible region), on confirmed-defect images; category-only figures beside them | Confirmed findings and zones | Every human finding missed |
| Clean-image false alarms (hallucination proxy) | Clean images not cleared; findings per clean image | Confirmed clean | Not cleared |
| Before/after usefulness | Agreement with the human judgment; `no_clear_difference` matches `no_benefit`; `inconclusive` pairs have no reference and are **excluded and counted**; a helped / not-helped agreement is shown beside it | Pair judgment | Disagreement |
| Multi-subject consistency | Subject-count agreement on images with two or more recorded subjects | `subject_count` | Disagreement |
| Prompt adherence | **Not evaluated**: the export carries no prompt and no element reference | none | n/a |
| Structured validity | Valid, refused and invalid rates; invalid reasons by code | n/a | Invalid |
| Seconds per image and peak memory | Mean, median, max; memory and wall-limit violations against the plan's limits | n/a | Measured as is |

Region compatibility: a model zone matches when it is one of the human finding's zones; `whole_image` matches only a finding
covering at least six zones; a human finding with no region matches any zone. Unmatched answer findings on a clean image are
unsupported (hallucinated); on a defective image they are reported separately, because the operator may not have recorded every
defect. Object-level hallucination and per-subject identity are not evaluated (no human reference) and are listed as such in
every report, never guessed.

## 5. Statistics

| Quantity | Method | Why |
|---|---|---|
| Proportions (validity, recall, false alarm, agreements) | Wilson score interval, 95 % | Near-nominal coverage at n = 10..62, stays in [0, 1], defined at 0 and n |
| F1, balanced accuracy, finding precision | Percentile bootstrap, 2000 resamples, fixed LCG seed 242, stratified by verdict (finding precision: resampled by image, which keeps each image's findings together) | No closed form; findings cluster within images |
| Deep vs fast on the same images | Exact McNemar test (binomial on discordant images), one-sided for "deep better", two-sided also shown; on all images, defective only and clean only | Paired binary outcomes |
| F1 and balanced-accuracy gain | Paired stratified bootstrap (same resampled images for both tiers) | Keeps the pairing |

Limits at the planned sizes: with 20 clean images the false-alarm interval at the threshold (5 of 20) is [0.11, 0.47]; with 30
defective images recall at 15 of 30 is [0.33, 0.67]; 59 of 62 valid answers is [0.87, 0.98]. McNemar can reach p <= 0.05 only
with at least five discordant images all favouring the deep tier (8 vs 1 gives p = 0.020; 6 vs 2 gives 0.145), so the test can
only detect a large, consistent advantage. Bootstrap percentiles on 50 images are approximate; treat the third decimal as noise.

## 6. Gates (proposed, pending owner approval)

Fixed in `eval2.GATES` before any run and bound into the plan digest; changing any value needs a new contract version (a new
gate set id) and a new owner approval. `min n` is the sample a full run needs to PASS; below it the verdict is
`INSUFFICIENT_SAMPLE`. A gate **fails clearly** at any stage when its 95 % interval lies entirely on the wrong side of the
threshold (count gates: when a violation was observed). On the full sample a value that is undefined (for example a deep tier that never names a
finding) fails; nothing passes by abstaining.

| Gate | Tier | Question | Pass rule | min n | Basis and support | Pilot can fail it when |
|---|---|---|---|---|---|---|
| F1 | fast | structured validity | >= 0.95 | 50 cases | point | Wilson upper < 0.95 |
| F2 | fast | clean false alarm | <= 0.25 | 20 clean | point | Wilson lower > 0.25 |
| F3 | fast | image-level defect recall | >= 0.5 | 30 defective | point | Wilson upper < 0.5 |
| F4 | fast | above every deterministic floor | > 0.5 | 20 clean, 30 defective | one-sided 95 % lower bound of balanced accuracy above the best floor (0.5) | one-sided upper <= best floor |
| F5 | fast | memory and time | <= 0 | 50 cases | count: no case over the memory limit, median seconds within budget | any violation |
| D1 | deep | structured validity | >= 0.95 | 50 cases | point | Wilson upper < 0.95 |
| D2 | deep | clean false alarm | <= 0.15 | 20 clean | point | Wilson lower > 0.15 |
| D3 | deep | finding-level precision | >= 0.6 | 30 defective | point, and above the best floor's finding precision | bootstrap upper < 0.6 |
| D4 | deep | image-level F1 over the fast tier | >= 0.15 | 20 clean, 30 defective | point gain, and exact McNemar one-sided p <= 0.05 with more images favouring deep | paired bootstrap upper < 0.15 |
| D5 | deep | above every deterministic floor | > 0.5 | 20 clean, 30 defective | as F4 | as F4 |
| D6 | deep | memory and time | <= 0 | 50 cases | as F5 | any violation |
| T1 | two-tier | a conditional rule reaches deep detection at half its time | <= 0.05 | 20 clean, 30 defective | recall shortfall vs deep alone, with that rule's clean false alarm <= 0.15 and seconds per image <= 0.5 x deep alone; applies only when every D gate passes | never (`NOT_DECIDED`) |

Reasoning:

* **F1, D1 (0.95).** On 62 requests this allows at most three invalid answers. An advisory feature that silently fails one in
  twenty is already noticeable; with a true rate of 0.95 the gate passes about 62 % of the time, at 0.98 about 96 %, at 0.90
  about 12 %, so it separates a working decoder from a struggling one. Kept from the starting point.
* **F2 (0.25).** A cheap first look may cry wolf on one clean image in four: the operator dismisses it in one click. 5 of 20
  passes. A true rate of 0.10 passes 99 % of the time, 0.25 about 62 %, 0.40 about 13 %. The earlier synthetic result (the clean
  stick figure always flagged) would fail it.
* **F3 (0.50).** Half the confirmed defects is the least that makes a first look worth running; below it the operator learns to
  ignore it. 15 of 30 passes; true recall 0.6 passes 90 %, 0.4 passes 18 %.
* **F4, D5 (floors).** A floor that wins one side of the detection trade-off loses the other (always-clean has no false alarms,
  always-defect has full recall), so comparing single rates with floors is meaningless and F1 favours always-defect (0.75 on a
  set with 60 % defective images). Balanced accuracy is 0.5 for every floor, so the gate requires the one-sided 95 % lower bound
  above 0.5: the tier demonstrably looks at the image. A tier exactly at the F2 and F3 thresholds has balanced accuracy 0.625 and
  a lower bound of 0.517 on the planned set, so F4 is consistent with them rather than stricter. Validity and resources have no
  floor (floors are valid and instant by construction). Finding precision is also compared with the floors (D3).
* **D2 (0.15).** The deep look is slower and asked for deliberately, so it must be more trustworthy than the fast one: 3 of 20.
  True 0.05 passes 98 %, 0.15 about 65 %, 0.25 about 23 %.
* **D3 (0.60).** When the deep tier names a finding, it should usually be one the operator confirmed, with a region close
  enough to act on. Precision is computed on confirmed-defect images only (false alarms have D2) and must also beat the
  most-frequent-finding floor (the modal category and zone on every image). Human labels may be incomplete, which only lowers
  measured precision, so the gate errs strict.
* **D4 (+0.15 F1 and McNemar).** The deep tier costs roughly ten times the time and three times the memory; a gain smaller than
  0.15 F1 would not justify it, and with 50 images smaller differences are not resolvable anyway. A fast tier at the F2/F3
  thresholds has F1 0.60, so the deep tier needs about 0.75 (for example recall 24 of 30 with 3 of 20 false alarms gives 0.84).
  The McNemar condition prevents a gain driven by a handful of images in both directions from passing.
* **F5, D6.** Resource safety is a hard gate, reported apart from quality: any case over the plan's memory limit fails, as does a
  median over the tier's time budget. Proposed limits: per-case wall 180 s for both tiers, peak working set 6 GiB fast and 12 GiB
  deep (the values the VL-220 plan already uses), median budgets 20 s fast and 120 s deep. **These are placeholders until AI-VL-241
  reports Gemma's measured time and memory**; the plan records `limits_source` and the owner approves the actual values with the
  digest. A timed-out case also counts as invalid under F1/D1.
* **T1.** The pre-registered candidates are the two conditional rules; "never", "always" and "deep alone" are reported for
  context only. A rule passes when its recall is within 0.05 of the deep tier alone, its clean false alarm meets D2, and its
  expected seconds per image are at most half the deep tier's. Time depends on the share of defective images the operator sends,
  which the test set fixes at 60 % by design; the plan binds `operator_defect_share` (proposed 0.5) and the gate uses class means
  weighted by it, with 0.25 / 0.5 / 0.75 shown as sensitivity. With two candidate rules the selection effect is small but real:
  the report names every rule that meets the gate and the owner chooses among them.

**What a PASS licenses:** for this exact model, projector, runtime build and scope, "usable for advisory review under Preview":
operator-selected images, closed findings the operator confirms in Review. **What it does not license:** promotion, a qualified
label, a production entry point, a default GPU mode or any automatic action. Those are separate owner decisions under the
roadmap (AI-REVIEW-410, AI-GPU-440) and the qualification authority.

**The pilot.** A 30-image pilot (about 12 clean and 18 defective) may come first. Its intervals are wide (12 clean images:
two-sided [0.09, 0.53] at 3 of 12), so it **can stop a clearly failing tier but cannot pass one**: every gate is `FAIL` or
`NOT_DECIDED`. Examples on 12 clean / 18 defective: F2 fails at 6 or more false alarms, D2 at 5 or more, F3 at 4 or fewer
detections, and a tier that flags every image (the LFM3 synthetic pattern) fails F4. A pilot plan is a different digest
(`stage: pilot`); its evidence cannot be reused as the full run.

## 7. Floors and comparators

| System | Answer | Dimensions |
|---|---|---|
| always-clean | `clean`, no findings, one subject; pairs: no benefit | detection, triage, subjects, before/after |
| always-defect | `defective`, one `General / local issue` over `whole_image`; pairs: helped | same |
| most-frequent | the majority verdict, the most frequent human (category, zone), the most frequent subject count; pairs: the most frequent conclusive judgment | same (it knows the label distribution: the strongest image-blind answer) |
| always-worse | pairs only | before/after |
| Florence-2 Base FT (Smart Review caption and object labels), optional | per image a subject-count token derived outside this package from its object labels (`stablenew.vl242.comparator_evidence/1`, nothing else accepted) | multi-subject consistency only |

Florence-2 cannot answer image-level detection, finding triage or before/after, and is not a structured-answer system; the
report lists those as "not addressable" and invents no answer. Using it needs `florence_in_scope` in the plan and its catalog
resource verified (state unverified today).

## 8. Escalation simulation

The paired run answers every image with both tiers, so each rule is simulated on the same images from the real answers and
measured seconds. An escalated image shows the deep answer; if the deep tier gave no usable answer, the fast one stands. A fast
answer that is unusable escalates under every conditional rule.

| Rule | Final answer | Time per image | Expected to show |
|---|---|---|---|
| never | fast | fast | The fast tier alone (also the operator who never asks) |
| always | deep | fast + deep | Whether chaining costs more than it adds over deep alone |
| on defect (fast says defective) | deep on flagged images, fast clean otherwise | fast + deep on flagged | Confirmation: deep withdraws fast false alarms, but cannot recover fast misses, so recall is at most the fast tier's |
| on clean (fast says clean) | deep on cleared images, fast flags stand | fast + deep on cleared | Second look: deep catches fast misses, but fast false alarms stay |
| deep only | deep | deep | The deep tier alone (the operator asks for it directly) |
| operator-requested only | reported as `never` and `deep only` | | The two single-tier results |

Each row reports recall, clean false alarm, F1, balanced accuracy, finding precision, escalation rate, mean seconds on this
set, seconds at the plan's defect share, time relative to deep alone and recall shortfall relative to deep alone.

## 9. Persistence (real sets)

Per case, an `evidence/2` file (`stablenew.vl220.evidence/2`) holds exactly `case_id`, `status`, `reason` (a code matching
`[a-z0-9_]{0,64}`; for a refusal one of the closed refusal codes), `wall_seconds`, `peak_working_set_bytes` and `answer`: the
closed structured answer for a valid case, otherwise `null`. **Never free text, prompts, paths, image bytes or the raw response.**
`eval2.evidence_record` builds a record from a validated answer and never receives the raw text; `eval2.validate_evidence`
re-validates every stored answer through the response validator and refuses any unknown key, non-enum value or text-shaped
reason. Evidence, cases, labels and reports live outside Git (the evaluation root, e.g. `D:\StableNew-Assets\offline-ai\`);
the CLI refuses to write any of them inside the repository. The report shows aggregate numbers only, with no case id.

The driver (`driver.py`, owned by AI-VL-241) does not yet run `eval/2` cases or write `evidence/2`; that integration is a
separate package and must use `evidence_record`.

## 10. The plan digest the owner approves

`python -m tools.qualification.vl242 plan --cases <cases.json> --labels <labels.json> --stage pilot|full [--limits <json>]
[--florence]` prints `plan_sha256`. It binds: the contract section (vocabularies, response schema and question digests, gate set
and values, interval methods and seed), the stage, the planned set, the case-set and label-set digests with content-free counts,
both candidates' identities (model, projector, build, tool, licence text digests), each tier's limits and their source, whether
Florence-2 is in scope, the escalation rules and `operator_defect_share`. Any change to any of them changes the digest, and
`report` refuses evidence naming another plan, case set, tier or candidate.

Before the paired real-image run the owner approves: (1) the gate values in section 6, or changes to them (a new gate set id);
(2) the case set: the export, its conversion counts and the case/label digests, labeled by a person; (3) each tier's limits,
replacing the placeholders with AI-VL-241's measurements; (4) `operator_defect_share`; (5) whether Florence-2 is in scope; and
(6) the resulting `plan_sha256`, separately for a pilot and for the full run. The run itself also needs the existing
invocation gates (licence acknowledgement, firewall attestation, evaluation-root import) and the driver integration.

## 11. Roadmap evidence rules this contract does not yet cover

* **Confirmed-clean images and subject counts** cannot be recorded in Review today (section 2), so the clean-image and
  multi-subject dimensions have no real reference until that is added.
* **Prompt adherence** is not evaluated: the export carries no prompt or element reference (the owner's prompts stay private).
  Covering it needs an export field the owner approves and a new contract version.
* **Object-level hallucination** (naming things that are not there) has no human reference; the clean-image false alarm and
  unsupported findings are the only hallucination measures.
* **Multi-subject consistency** is measured as subject-count agreement only; whether each subject stays the same across images
  is not in the export.
* **Severity** is not scored (Review records no severity in `findings.py`).
* **Label completeness**: operators confirm what they noticed; unmatched findings on defective images may be real. Measured
  finding precision is therefore a lower bound.
* **Resource safety beyond time and memory** (contention refusal, cancellation, teardown with queue activity) stays with the
  invocation contract and AI-VL-241; this contract reports time and memory only.
* **Comparator floor for Florence-2** covers subject counts only; there is still no existing structured visual comparator.
* **Before/after (12 pairs) and multi-subject (10 images) are reported but not gated**: their 95 % intervals are about +-0.3 wide.

## 12. Commands

    python -m tools.qualification.vl242 convert --export <export.json> --out <dir outside the repository>
    python -m tools.qualification.vl242 plan --cases <dir>/cases.json --labels <dir>/labels.json --stage pilot|full
    python -m tools.qualification.vl242 report --cases ... --labels ... --stage ... --fast <fast.json> --deep <deep.json> [--florence --comparator <florence.json>] [--out <file>]

None of them runs a model, opens a network connection or starts a process (a test runs them with sockets and process creation
disabled).
