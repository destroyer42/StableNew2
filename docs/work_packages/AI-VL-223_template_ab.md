# AI-VL-223: turn-format A/B for the LFM3-VL-2B visual harness (decision D24)

Status: **run once on 2026-11-14 (run 3, owner-approved by the digest below); result in section 8.** Evaluation-only. `qualified` stays false everywhere; nothing here is a quality claim for
StableNew's real use. The owner approved the run by the plan digest below, in the session that prepared it.

Plan digest (`python -m tools.qualification.vl220 describe`, field `plan_sha256`; a test fails if this line goes stale):
`15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536`

Digest chain: `23df6fa4...880e` (owner-approved) -> `fa63304d...339a` (run 1) -> `ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7`
(run 2, AI-VL-222) -> the digest above. This package adds exactly one plan section, `template_ab`; a test removes it and reproduces
run 2's digest. The `diagnostic` section is untouched.

Execution class: Standard. Touches `tools/qualification/vl220/`, tests and docs only. `src/`, `config/ai_model_registry.json`,
`config/managed_ai_runtime.json`, `src/ai_assist/argv.py` and every frozen identity are untouched.

## 1. Why this A/B (what run 2 left open)

Run 2 (AI-VL-222, plan `ea7f2bb8...`, 30 invocations, all valid, no limit violations) separated the harness faults from the rest:

| Area | 128 px | 512 px |
|---|---|---|
| Valid structured answers | 13 of 13 (run 1: adherence 3 of 3 invalid) | 13 of 13 |
| Free-text controls | both scenes described correctly | both described correctly |
| Describe | `red rectangle` for the red square | exact, no unsupported name |
| Adherence | 3 of 3, **uninformative** (see H7) | same |
| Consistency | 2 of 2 | `consistency-2` wrong |
| Defect triage | near-constant answer (arms and legs `extra_limb`), clean figure flagged | same answers |
| Before/after | `a` or `tie`, never `b`; both images were encoded | same |

So the model sees the images, the schemas and the scoring are sound, and the misses are not harness faults. One invocation
variable was never varied: the turn format. The runtime's stderr confirmed the **legacy ChatML turn** (no BOS, no thinking prefix).
This package runs one bounded A/B on that single variable.

## 2. Source proof (llama.cpp b11960, read as text; no model run)

Files are the b11960 sources of the pinned build, copied for reading. Line numbers are those of that tag.

| Claim | Where |
|---|---|
| `llama-mtmd-cli` parses its arguments as `LLAMA_EXAMPLE_MTMD` | `tools/mtmd/mtmd-cli.cpp:529` |
| Options are filtered per example: an option is only registered if it lists the running example (or the common one) | `common/arg.cpp:1440-1452` (`add_opt`) |
| A token that is not a registered option stops parsing with `error: invalid argument: <flag>` | `common/arg.cpp:838` and `:1231` |
| `--jinja` lists `MTMD`; the MTMD default is `use_jinja = false` | `common/arg.cpp:3727-3732` and `:1409-1411` |
| `--chat-template-kwargs` lists **only** `SERVER` and `CLI`, so `llama-mtmd-cli` rejects it | `common/arg.cpp:3583-3600` |
| `--reasoning`, `--reasoning-budget`, `--reasoning-format` list `SERVER`, `COMPLETION`, `CLI` only (not `MTMD`) | `common/arg.cpp:3735-3790` (`--reasoning-format`, `--reasoning`, `--reasoning-effort`, `--reasoning-budget`, `--reasoning-budget-message`) |
| The real turn is built by the five-argument `common_chat_format_single(tmpls, history, msg, add_ass, use_jinja)`; no kwargs and no reasoning setting reach it (only the printed *example* receives kwargs) | `tools/mtmd/mtmd-cli.cpp:354-362` (call) and `:141` (example) |
| `enable_thinking` is `true` unless a caller sets it, and is passed into the template context | `common/chat.h:274`, `common/chat.cpp:1057` |
| The user message is the media markers (one per image) followed by the prompt text | `tools/mtmd/mtmd-cli.cpp:602-612` |
| Text parts are tokenized with `add_special = false, parse_special = true`; BOS is only added when the vocabulary asks for it | `tools/mtmd/mtmd-cli.cpp:398` and `tools/mtmd/mtmd.cpp:1469` |
| The pinned GGUF has `add_bos_token = false` (BOS id 124894) and its template starts with `{{- bos_token -}}`, defaults `enable_thinking` to true, and ends the generation prompt with `<|im_start|>assistant\n<think>` (true) or `<think></think>` (false) | read from the pinned GGUF's `tokenizer.chat_template` |

What follows from it:

* **Legacy turn (default, as in runs 1 and 2).** Built-in ChatML: `<|im_start|>user\n<__media__>{prompt}<|im_end|>\n<|im_start|>assistant\n`.
  No BOS (the vocabulary does not ask for one), no thinking prefix. The response grammar then forces `{` as the first generated token.
* **`jinja` turn (`--jinja`).** The turn is rendered from the pinned GGUF's own template with its defaults:
  `<bos><|im_start|>user\n<__media__>{prompt}<|im_end|>\n<|im_start|>assistant\n<think>`. BOS comes from the template's `bos_token`
  (parsed as a special token, so exactly one). The thinking block is **open**, and the grammar still forces `{` as the first token
  after it.
* **A "no thinking" turn (`<think></think>`) cannot be requested through `llama-mtmd-cli` b11960.** The orchestrating session's
  decision D24 named `--chat-template-kwargs '{"enable_thinking":false}'`. Source proof shows that flag is rejected by this tool
  and would be ignored by the turn builder even if it were accepted, and the `--reasoning` family is not registered for it either.
  The only way to set it would be a template file or string flag (explicitly out of scope) or a different binary.
  So this package implements the variant D24 allowed (`--jinja`), refuses the flag that cannot work, and records the limit here.

## 3. What is added (and what is not)

* `tools/qualification/vl220/visual_argv.py`: the argument builder reuses the existing `use_jinja: bool` switch of the Gemma package
  (PR-AI-VL-230). `use_jinja=False` (default for the LFM candidate) is byte-for-byte the earlier command line; `use_jinja=True`
  adds exactly one switch, `--jinja`, **at the end of the argument list**. `VISUAL_ALLOWED_FLAGS` keeps its 22 flags; `--jinja`
  stays in `VISUAL_REFUSED_FLAGS` and is accepted only when the check is asked for `use_jinja=True` and the switch appears exactly
  once. `--chat-template-kwargs`, `--reasoning`, `-rea`, `--reasoning-budget`, `--reasoning-format`, `--chat-template`,
  `--chat-template-file` are refused by name in every mode. No template file or template string is accepted; the template comes
  only from the hash-pinned GGUF. The names `legacy` and `jinja` (`TURN_LEGACY`, `TURN_JINJA`) are only labels in evidence, plan and CLI.
* `driver.py`: `VisualDriver(use_jinja=...)`. Gemma always renders its own template and keeps the strict containment checks of
  PR-AI-VL-230; those checks stay Gemma-only, so the two LFM variants run under identical conditions. For the LFM candidate,
  `use_jinja=True` is **refused unless a diagnostic capture exists**, i.e. unless the case set is exactly a built-in synthetic set
  (`turn_format_needs_diagnostic_capture`). The evidence document and the diagnostics document record which turn format ran.
* `__main__.py`: `evaluate --turn-format {legacy,jinja}`. `jinja` needs `--diagnostics-out` and refuses `--cases`.
* `synthetic.py` / H7: a third built-in set, `vl220-synthetic-512-2`.
* `plan.py`: the `template_ab` section (variants, refused flags, the set's pins and per-request prompt and schema digests, request counts).

Unchanged: CPU only, contained child, the attested `llama-mtmd-cli.exe` of `b11960-cpu-vision`, no network, the existing limits,
greedy sampling, `--generation-idle`, the response schemas, the prompts and the scoring.

## 4. H7: the first two sets could not tell a constant answer from a correct one

In `vl220-synthetic-1` and `vl220-synthetic-512-1` all three adherence cases have the reference `e1 = true, e2 = false`, so a
model that always answered "true, false" scored 1.0 (run 2 did exactly that and scored 1.0 on both sets). A test records that
fact. `vl220-synthetic-512-2` keeps the 512-pixel scenes and every non-adherence case as in `vl220-synthetic-512-1` and asks
four adherence cases that cover every answer pattern once: (true, false), (false, true), (true, true), (false, false). No constant
answer can score above one half on adherence there (tested for all four constants). The two earlier sets are byte-identical
(their case-document digests are pinned by earlier tests, unmodified). The new set has its own pinned case and label digests:
case document `1306b33d2f17...` (full digest in the plan), 16 images, 14 cases.

## 5. The run (prepared, not performed)

Approve by this digest: `15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536`.

| What | Count | Detail |
|---|---|---|
| Invocations | 32 | 2 turn formats x (14 scored cases + 2 free-text controls); one contained CPU-only child each, one at a time |
| Set | `vl220-synthetic-512-2` | 512-pixel scenes only; the 128-pixel set is left out because the runtime stretches it to 256 pixels, which would add a second variable |
| Variants | `legacy`, then `jinja` | the same set, the same prompts and schemas, the same limits; only `--jinja` differs |
| Expected time | 3 to 6 minutes | run 2 took a median of 3.9 s and at most 5.2 s per case at 512 px, and about 3 minutes for its 30 invocations; the controls generate up to 256 tokens |
| Resources | as run 2 | about 2.4 GB peak, CPU only, no GPU, no network |
| Saved (outside Git) | 2 evidence files, 2 diagnostics files | `D:\StableNew-Assets\offline-ai\vl220-evidence\run3-512v-legacy.json` / `.diagnostics.json` and `run3-512v-jinja.json` / `.diagnostics.json`: per request the raw answer, a bounded stderr head and tail and selected lines, and the turn format |
| Prerequisites | in place | firewall rule and attestation for `b11960-cpu-vision`, license acknowledgement, imported pair. The 16 PNGs of the new set (synthetic content only, about 14 MB) are written once with `write-synthetic --set vl220-synthetic-512-2` |

Run only after the owner approves by digest, only with no generation running, and only with the attestation in place.

```bash
python -m tools.qualification.vl220 write-synthetic --set vl220-synthetic-512-2 --dest D:\StableNew-Assets\offline-ai\vl220-synthetic-512-2
python -m tools.qualification.vl220 evaluate --builtin-set vl220-synthetic-512-2 --evaluation-root D:\StableNew-Assets\offline-ai\vl220-eval --assets D:\StableNew-Assets\offline-ai\vl220-synthetic-512-2 --acknowledgement D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b\license_acknowledgement.json --evidence-out D:\StableNew-Assets\offline-ai\vl220-evidence\run3-512v-legacy.json --diagnostics-out D:\StableNew-Assets\offline-ai\vl220-evidence\run3-512v-legacy.diagnostics.json --controls --turn-format legacy --i-have-the-plan-digest 15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536 --generation-idle
python -m tools.qualification.vl220 evaluate --builtin-set vl220-synthetic-512-2 --evaluation-root D:\StableNew-Assets\offline-ai\vl220-eval --assets D:\StableNew-Assets\offline-ai\vl220-synthetic-512-2 --acknowledgement D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b\license_acknowledgement.json --evidence-out D:\StableNew-Assets\offline-ai\vl220-evidence\run3-512v-jinja.json --diagnostics-out D:\StableNew-Assets\offline-ai\vl220-evidence\run3-512v-jinja.diagnostics.json --controls --turn-format jinja --i-have-the-plan-digest 15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536 --generation-idle
```

## 6. What the report will say, and what it cannot

Per kind and per case: the legacy answer, the jinja answer and the reference, side by side; the stderr facts that show the turn
actually used (the runtime prints a rendered chat-template example into its log, so the jinja run's log shows whether BOS and the
open thinking prefix were applied); and a plain statement whether the turn format changed defect triage and before/after.

Limits the report keeps:

* The jinja turn changes two things at once, BOS and the open `<think>`; the A/B cannot say which one mattered. A "no thinking"
  turn is unreachable with this tool (section 2).
* The scenes are drawn shapes and stick figures. A result here says little about real generated images; real assets with human
  labels are a separate step. A model that handles these scenes is not thereby qualified, and one that does not is not thereby
  rejected for StableNew's real use.
* Greedy decoding with a forced first token: a difference between the variants is a difference in the turn, not noise, but two
  runs per variant would be needed to claim the answers are stable.

## 7. Acceptance and evidence boundary

Deterministic tests only: the closed argv list (one new switch, only in the named turn format, never by default; the template and
thinking arguments refused by name), the gate on the driver and the CLI, the varied set (pins, constant-answer ceiling, oracle
score), the plan (the new section, and run 2's digest reproduced by removing it), the documents. Qualification: not applicable. The
model run is reported in section 8.

## 8. Run 3 result (2026-11-14; plan digest `15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536`)

Two variants of `vl220-synthetic-512-2` (14 cases plus 2 free-text controls each), CPU only, one contained child at a time. All 32
invocations exited 0; all 28 scored answers were structurally valid in both variants (valid rate 1.0, no limit violations). Median
wall time 4.6 s (legacy) and 4.2 s (jinja), at most 6.1 s per case, controls up to 9.0 s with `--jinja`; peak working set 2.46 GB.
An earlier attempt was refused before any invocation (`commit_headroom_below_requirement`, the machine's free commit was low
while Forge and the app were running); its `not_run` stub files are kept as `run3-512v-legacy.refused-attempt1*.json`. Evidence:
`D:\StableNew-Assets\offline-ail220-evidence
un3-512v-{legacy,jinja}.json` and `.diagnostics.json`.

| Score | legacy | jinja |
|---|---|---|
| prompt adherence (4 cases, varied references) | 1.0 | 1.0 |
| describe object recall / unsupported mentions | 1.0 / 0.0 | 1.0 / 0.0 |
| multi-subject consistency (2 cases) | 0.75 | 0.75 |
| defect triage recall / precision | 0.67 / 0.22 | 0.33 / 0.20 |
| defect triage false-alarm rate on the clean case | 1.0 | 1.0 |
| before/after usefulness (2 cases) | 0.5 | 0.0 |

Per kind, answer against reference:

* **adherence (4 of 4, both variants identical):** every answer equals the reference, including the (T,F), (F,T), (T,T), (F,F)
  patterns. Run 2's perfect adherence was uninformative (every reference and every answer was `e1 = true, e2 = false`); with
  references that vary, a constant answer cannot score this, so H7 is closed for this set and the model demonstrably reads
  these two-object scenes.
* **describe (2 of 2, identical):** `red square, yellow circle` and `green circle`, exactly the references.
* **consistency:** both variants answer true/true for case 1 (correct) and true/true for case 2 (reference true/false): the same
  miss in both.
* **defect triage (reference: clean; one arms extra limb; one legs missing limb; one arms extra limb):**
  * defect-1 (clean): legacy reported 4 findings, jinja reported 4 findings, so both false-alarm.
  * defect-2: legacy found the arms extra limb and added a false legs finding; jinja reported nothing (a miss).
  * defect-3 (legs missing limb): both reported an arms extra limb: a miss and a false finding in both.
  * defect-4: both found the arms extra limb and then added several false findings (jinja more of them).
* **before/after:** reference a, b. Legacy answered a (right) and tie (wrong); jinja answered tie (wrong) and a (wrong).

**Did the template change defect triage and before/after? Not usefully.** The two turns agree on every case where the model is
already good (adherence, describe, consistency). Where it is poor (defect triage, before/after) neither turn fixes it, and
jinja scored the same or lower on both (recall 0.67 to 0.33; before/after 0.5 to 0.0). With 3 positive defect cases and 2
before/after cases, those differences are one or two answers each and are not evidence that jinja is worse; they are certainly not
evidence that it is better. The rendered turn is not what limits defect triage here. Because the grammar forces `{` as the first
token, the open `<think>` never gets to produce reasoning in the scored answers; it only shows in the free-text controls, where the
jinja turn writes visible reasoning ("The user wants a concise description ... Let me look carefully") and the legacy turn answers
directly. The log's own rendered-template line did not survive the bounded stderr capture, so the jinja turn is confirmed by the
different argument-shape digest (one switch) and by that behaviour, not by a logged template.

**Run 2 against run 3 (legacy turn, 512 px):** the structured scores are unchanged on a different, varied set: defect triage
precision 0.22 and recall 0.67 with the clean case flagged, before/after 0.5, consistency 0.75 with the same `s2` miss, describe
exact. Only adherence moved from uninformative to informative (1.0 on varied references). So defect triage and before/after were
poor before this run, are poor in both turns, and are the open question; the stick-figure scenes may simply be too unlike what
the model was trained to triage.

Caveats, unchanged: drawn shapes and stick figures say little about real generated images; one greedy sample per case and per
variant, so stability is untested; `qualified` stays false; no change to the product, the registry or the managed runtime follows
from this run.
