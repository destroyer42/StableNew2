# PR-AI-VL-222: why the first LFM3-VL-2B synthetic run scored near zero, and a small diagnostic run

Status: **implemented on a feature branch; PR open; the diagnostic run has NOT been run** (it waits for the owner's approval of
the plan digest below). This is a diagnosis, not a qualification: nothing here says the model is good, bad, qualified or failed
for StableNew's real use. `qualified` stays `false` everywhere.

Plan digest to approve (`python -m tools.qualification.vl220 describe`, field `plan_sha256`; a test fails if this line goes stale):
`ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7`

Digest chain: `23df6fa4...880e` (owner-approved) -> `fa63304d...339a` (the plan the first run executed; differs only by the
approved flag and one comparator reason) -> `ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7` (this package adds exactly one plan section, `diagnostic`, which
pins every prompt and per-case schema of both synthetic sets and the free-text controls; a test removes the section and
reproduces `fa63304d...339a`).

## Objective

- Outcome: find out why `run1-synthetic.json` scored adherence 0.0, defect triage 0.0 / 0.0 / false alarms 1.0, object recall 0.0
  and unsupported mentions 1.0; fix what is the harness's fault; prepare (not perform) a small diagnostic run that can tell
  perception from structured-output behavior from invocation.
- In scope: `tools/qualification/vl220/` (contract, prompts, scoring, synthetic, visual argv, driver, diagnostics, plan, CLI), its
  tests, and this document. Reading llama.cpp source at `b11960` as text.
- Explicit exclusions: `src/` (so `src/ai_assist/argv.py` with `FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`, `build_argv`,
  `build_production_argv`), the text registry, `config/ai_model_registry.json`, `config/managed_ai_runtime.json`, the frozen
  identities (Qwen screening plan `17814e40...`, final plan `3017c427...`, corpus `a89297be...`, LFM3 `FROZEN_CONTRACT_SHA256`
  `41e65d67...`), any new flag, `--jinja`, any model run, GPU work, firewall or attestation changes.

## Execution class and model recommendation

- Execution class: **Standard** (evaluation harness and tests under `tools/`; no architecture, production or runtime-ownership change).
- Execution location: Local.
- Model recommendation: Claude Code Sonnet 5.5, high effort (a diagnosis plus a bounded change to a known harness); Codex
  equivalent per `docs/AI_MODEL_SELECTION.md`.
- Controller Surface Assessment: none. No controller, coordinator, GUI or `src/` file is touched.
- Token-Efficient Validation Plan: the AI-VL-220 tests, the new `tests/tools/test_ai_vl222_diagnostic.py`, then `tests/tools`, then
  the canonical local PR gate in an isolated worktree; the llama.cpp source was fetched once with `gh api` into a scratch folder.

## Part A: findings (nothing here ran a model)

### A1. The scoring path is sound; near-misses score as documented

The by-construction reference answers, fed through `validate_response` and `scoring.score_run`, score every dimension perfectly
for all 13 cases of both sets (tests `test_the_by_construction_answers_score_perfectly...`). What plausible near-misses score
(set 1, `describe-1` and the other cases otherwise perfect; `describe-2` contributes one supported mention):

| Answer | Result |
|---|---|
| `red square`, `yellow circle` (also `A Red Square.`, `yellow-circle`, `RED_SQUARES`) | unsupported 0.0, recall 1.0 |
| `square`, `circle` (the first run's likeliest answer to "one short name each") | **before this package:** unsupported 1.0 (counted as hallucinations), recall 0.0. **Now:** unsupported 0.0, recall 1/3, reported as `describe_detail.generic_mentions` = 2 (true, but the question asked for the color too) |
| `red rectangle`, `blue square`, `red` | unsupported 1/3 (a different word or a different property is a hallucination), recall 2/3 |
| a defect list for the clean figure | false-alarm rate 1.0, precision 3/4 |
| correct verdicts under other ids (`a`, `b` for `e1`, `e2`) | invalid `answers_do_not_match_elements`, adherence 4/6 (never guessed by position) |
| right ids, wrong order | invalid `answers_out_of_order` |

Floors on the same set (`dry-run`): all-yes adherence 0.5, consistency 0.75, before/after 0.5, defect precision 0.0 / recall 0.0 /
false alarms 1.0; all-no adherence 0.5, consistency 0.25, before/after 0.0; seeded random adherence 0.167. Read against the first
run: its defect numbers equal the all-yes floor, its before/after 0.5 equals a constant answer, its consistency 1.0 beats every
floor (so not a constant), and its adherence 0.0 is the three **invalid** answers, not three wrong ones.

### A2. Exactly what the model received in the first run

`prompts.render_visual_prompt` rendered, for each case, a header, `Request: <case prompt>`, one guidance sentence, the elements
(`- e1: a red square is visible`) and `Answer shape: {...}`. So the case prompt, the elements **and their ids** and the JSON
shape were all there; the defects were in the details:

1. The adherence shape was `"answers":[{"id":"<element id>","value":true}]`: a placeholder for the id (a model may copy it) and a
   literal `true` as the value example (a bias toward yes), and no statement of how many answers or in which order.
2. The response schema for adherence/consistency was one generic schema (`id`: any string up to 64 characters, 1 to 12 items),
   so the grammar could not force the case's own ids.
3. The describe prompt said "one short name each" and the label expected `red square` / `yellow circle` (synonyms only
   `red-square`, `yellow-circle`). Nothing told the model to name the color, and the scorer counted `square` as a hallucination.
4. The defect prompt never said what `extra_limb`, `missing_limb` and the other categories mean.
5. Nothing mentions an image marker, a chat template or a system prompt, correctly: `mtmd-cli` supplies both (A3).

Rendered prompts after this package, one per kind (synthetic content only; the first line of every prompt is the same header):

**adherence (case `adherence-1`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: For each element, say whether it is visible in the image.
For every listed element give true if it is clearly visible in the image, otherwise false. Answer every element, once, in this order, using exactly these ids: e1, e2.
Elements:
- e1: a red square is visible
- e2: a green circle is visible

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"adherence","answers":[{"id":"e1","value":<true or false>},{"id":"e2","value":<true or false>}]}
```

**defect_triage (case `defect-1`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: List every anatomical defect of the figure. An empty list means none.
List every anatomical defect you can see. Use an empty findings list when there is none. Categories: extra_limb means more arms or legs than a person has, missing_limb means fewer, fused_limb means limbs joined together, distorted means a badly shaped body part, wrong_count means a wrong number of fingers or toes, other is anything else.

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"defect_triage","findings":[{"region":"<one of: face, hands, arms, legs, torso, background, other>","category":"<one of: extra_limb, missing_limb, fused_limb, distorted, wrong_count, other>","severity":"<one of: minor, major>"}]}
```

**consistency (case `consistency-1`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: The image has a left and a right panel. Say whether each subject is unchanged.
For every listed subject give true if it looks unchanged between the two panels, otherwise false. Answer every subject, once, in this order, using exactly these ids: s1, s2.
Elements:
- s1: subject 1 looks the same in both panels
- s2: subject 2 looks the same in both panels

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"consistency","answers":[{"id":"s1","value":<true or false>},{"id":"s2","value":<true or false>}]}
```

**before_after (case `before-after-1-complete-first`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: Image a and image b were made for: red square, blue circle, green square. Which one is more useful, or is it a tie?
You are given two images: image a is the first and image b is the second. Choose the one that is more useful for the request, or tie.

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"before_after","preferred":"<one of: a, b, tie>","reason":"<one of: more_complete, fewer_defects, closer_to_prompt, no_difference>"}
```

**describe, first set, free names (case `describe-1`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: List the objects you can see, one short name each.
List only the objects you can actually see. Do not guess at hidden or unclear things. Name each object with its color and its kind, for example "blue car", in lower case.

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"describe","objects":["<object name>"]}
```

**describe, second (512 px) set, closed vocabulary (case `describe-1`)**

```text
You are reviewing a generated picture for quality control. Look only at the image and answer with one JSON object and nothing else. If you cannot judge the image, answer with status "refused" and a short refusal_reason.

Request: List the objects you can see, one short name each.
List only the objects you can actually see. Do not guess at hidden or unclear things. Name each object with its color and its kind, for example "blue car", in lower case. Use only names from this list: blue circle, blue square, green circle, green square, red circle, red square, yellow circle, yellow square.

Answer shape: {"schema":"stablenew.vl220.response/1","status":"ok","kind":"describe","objects":["<object name>"]}
```

**free-text control (both sets; unscored, no schema)**

```text
Describe this image in two or three plain sentences. Say what shapes or figures you see, their colors and where they are.
```

### A3. llama.cpp `b11960`, read as text (nothing was run)

Fetched with `gh api` from `ggml-org/llama.cpp` at tag `b11960`: `tools/mtmd/mtmd-cli.cpp`, `mtmd.cpp`, `mtmd-image.cpp`, `clip.cpp`,
`clip-model.h`, `common/arg.cpp`, `chat.cpp`, `sampling.cpp`, `log.cpp`, `json-schema.cpp`, `json-schema-to-grammar.cpp`,
`src/llama-chat.cpp`; plus the pinned model and projector headers read as data (the GGUF key/value block).

- **How the turn is built from `-f` with `--image`.** The prompt file is `params.prompt`. In single-turn mode
  (`is_single_turn = !prompt.empty() && !image.empty()`, `mtmd-cli.cpp:546`) the CLI prepends one `<__media__>` marker per image
  when the prompt contains none (`mtmd-cli.cpp:600-608`), so **the image is placed at the very start of the user message and the
  marker is added for us**; a prompt that already has the marker keeps its own placement. It builds one `user` message
  (`:610-612`), formats it with the chat template (`chat_add_and_format`, `:354-362`), splits the formatted text on the marker
  (`:373-392`, refusing a count mismatch), and tokenizes the parts around the image chunks (`mtmd_tokenize_from_parts`, `:412`).
  For `lfm3vl` each image is wrapped in `<|vision_start|>` ... `<|vision_end|>` (`mtmd.cpp:811-819`). Two images (before/after)
  give two markers, in file order.
- **Chat template without `--jinja`.** `--jinja` is off by default for MTMD (`arg.cpp:1409-1411`), so the **legacy** engine is used
  (`chat.cpp:1612-1660`, `:1680-1682`). It matches the template string by substring: anything containing `<|im_start|>` (and not
  `<|im_sep|>` or `<end_of_utterance>`) is ChatML (`src/llama-chat.cpp:99-104`), rendered as
  `<|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n` (`:250-256`). An unrecognized template makes the CLI throw ("try using
  --jinja", `chat.cpp:1651-1653`); all 13 first-run cases exited 0, consistent with the ChatML match.
- **The model's own template differs (found in the pinned GGUF, `tokenizer.chat_template`).** It begins with `{{ bos_token }}`,
  defaults `enable_thinking` to true and ends the generation prompt with `<|im_start|>assistant\n<think>` (or
  `<think></think>` when thinking is off); the GGUF has `tokenizer.ggml.add_bos_token = false`, so `mtmd` adds no BOS either
  (`mtmd.cpp:1469`, only when the vocabulary asks for one). **So the legacy turn lacks the BOS token and the `<think>` /
  `<think></think>` prefix the model's own template would have produced.** Whether that matters is the one thing the source cannot
  say; it is the leading *invocation* suspect and it is listed as decision D24 below, not changed here.
- **`--json-schema-file`.** It is honored by `mtmd-cli`: it sets `params.sampling.grammar` to the converted schema
  (`arg.cpp:2301-2315`), `common_sampler_init(model, params.sampling)` builds the grammar sampler (`mtmd-cli.cpp:115`,
  `sampling.cpp:268-274`), and `generate_response` samples through it (`mtmd-cli.cpp:226`). With the legacy engine the template
  does not touch the grammar (`chat.cpp:1670-1674` only converts a `json_schema` input, which `mtmd-cli` does not set) and the
  grammar applies from the **first generated token** (no lazy trigger, no generation-prompt prefill: `sampling.cpp:298-309` only
  prefills a non-empty `generation_prompt`). The first token is therefore forced to `{` whatever the model "wanted" to start with
  (for example `<think>`). The schema is converted by the b11960 converter, which supports `prefixItems` as a fixed-length
  tuple (`json-schema.cpp:188-199`, `json-schema-to-grammar.cpp:944-955`), `enum` and `const`.
- **stdout versus stderr.** Generated pieces are printed with `LOG(...)` (level NONE, `mtmd-cli.cpp:235`), which `common_log`
  routes to **stdout**; every other message (`LOG_INF`, `LOG_WRN`, `LOG_ERR`, the loader, the perf summary) goes to **stderr**
  (`log.cpp:100-104`). stdout also carries a blank line after the prompt is evaluated (`mtmd-cli.cpp:515`), a newline at the end
  of generation (`:231`) and `\n\n` at the exit (`:705`), all stripped by the harness. The end-of-generation token is not printed (`:230`).
- **Image tokens for a 128 x 128 input under `--image-min-tokens 64 --image-max-tokens 256`.** The projector (`clip.vision.patch_size
  16`, `spatial_merge_size 2`, `image_min_pixels 65536`, bicubic resize) gives a patch area of 16 x 16 x 2 x 2 = 1024 pixels per
  token. The custom bounds replace the GGUF's (`clip.cpp:206-211`, `clip-model.h:225-228`): floor 64 x 1024 = 65536 pixels,
  ceiling 256 x 1024 = 262144. `smart_resize` (`mtmd-image.cpp:826-851`) rounds to multiples of 32; 128 x 128 is 16384 pixels,
  below the floor, so it is **stretched to 256 x 256** (`:844-848`) -> (256/16)/2 = 8 per side (`clip.cpp:4681`, `:4714`) =
  **64 tokens**. The two-panel 256 x 128 images become 384 x 192 = **72 tokens**; a before/after case carries 2 x 64. For the
  second set, 512 x 512 sits exactly on the ceiling and stays 512 x 512 = **256 tokens**, and the 1024 x 512 panels are scaled to
  704 x 352 = **242 tokens**. (A test reimplements this arithmetic.) Image tokens are far below the 4096-token context.
- **Flags.** `--image`, `-mmdev none`, `--no-mmproj-offload`, `--image-min-tokens`, `--image-max-tokens`, `--json-schema-file`
  and `-f` are accepted by `mtmd-cli` exactly as the AI-VL-220 contract table says (`arg.cpp:2301`, `:2614-2662`).

### A4. Defect list (harness or invocation), with evidence and disposition

| # | Defect | Whose | Evidence | Disposition |
|---|---|---|---|---|
| H1 | Adherence answer ids unconstrained: the decoder could emit any id, any count, repeats | harness | run 1: 3 of 3 adherence cases `invalid` / `answers_do_not_match_elements`; generic schema `id: string` | **Fixed:** per-case schema, a fixed-length `prefixItems` tuple whose ids are `const` in element order; the validator also requires element order (never looser than the schema) |
| H2 | Answer-shape example showed a literal `"value":true` and the placeholder `<element id>` | harness | `prompts._shape` before this package | **Fixed:** the real ids in order and `<true or false>` |
| H3 | "one short name each" vs a label of `<color> <shape>`; exact-match scoring counted `square` as a hallucination | harness | describe score 0.0 recall / 1.0 unsupported | **Fixed:** the prompt states the naming rule; scoring normalizes case, punctuation, articles, plurals and separators and treats a bare kind as a (reported) generic mention, not a hallucination; the 512 set carries a closed vocabulary enforced by schema and validator |
| H4 | Category words never explained | harness | prompt had only the names | **Fixed:** one-sentence glossary in the defect prompt |
| H5 | The driver kept no answer text or runtime output, so none of this could be checked | harness | run 1 evidence | **Fixed (Part B):** diagnostic capture for built-in synthetic sets only |
| H6 | 128 x 128 flat shapes are stretched 2x by the runtime and carry 64 image tokens | harness (fairness of the check) | A3 | **Addressed (A5):** a second set at 512 x 512 |
| I1 | The legacy ChatML turn lacks the BOS token and the `<think>` / `<think></think>` generation prefix of the model's own template, and the grammar forces `{` as the first token | invocation | A3, from the pinned GGUF and `b11960` source | **Not changed.** `--jinja` stays refused (this package adds no flag). Decision D24 below |
| ok | Image marker placement, per-image marker count, image encoding, grammar honored, stdout/stderr split | invocation | A3 | verified correct, nothing to fix |
| ok | Two-image cases took ~0.6 s longer than one-image cases in run 1 | - | the source encodes every image chunk (`mtmd-cli.cpp:425-513`) | consistent with an image being encoded; says nothing about perception |

How the orchestrator's five leads came out: (1) yes, an image is encoded; (2) the CLI adds the marker and a ChatML template, and
the model's real template differs (I1); (3) adherence ids were not constrained and the elements are rendered in the prompt (H1);
(4) correct, and fixed (H3); (5) a 128 x 128 input is stretched to 256 x 256 and carries 64 tokens (H6, A5).

What the first run does **not** show, and this package does not claim either: that the model is blind, or that it sees well.

### A5. A second synthetic set

The first set is unchanged (`vl220-synthetic-1`: images, cases and labels byte-identical, case digest `9c11172f...` as in the
first run's evidence; a test pins it). A second set, `vl220-synthetic-512-1`, draws the same 13 scenes four times larger
(512 x 512 per cell, 1024 x 512 for panels), uncompressed PNG, deterministic, with its own pinned digests and a closed object
vocabulary on its two describe cases. Its images total about 13 MB (the largest 1.6 MB, under the 8 MiB driver limit). It exercises
the same wiring on input the projector does not have to stretch; it is still flat shapes and says nothing about real generated images.

## Part B: diagnostic mode (decision D23)

- **Capture.** `diagnostics.DiagnosticCapture` records, per request, the raw answer (at most 16 KiB), the first 12 KiB and last
  8 KiB of the runtime's stderr and up to 48 selected informative stderr lines (template, image, token, grammar, warning,
  error). It can only be constructed for a case set that is **exactly** a built-in synthetic set: the same case document and label
  document digests, labeler `synthetic_by_construction` (so every asset digest is the pinned one). Anything else raises
  `DiagnosticsRefused` before a launch; the driver then has nothing to record into and the earlier rule stands (no answer text and
  no runtime output reach a file). Tests prove the refusal for a human-labeled set, an edited prompt, an edited asset digest, edited
  labels, an unknown set id and non-documents, through the class and through the CLI.
- **Where it goes.** `--diagnostics-out PATH`, a separate JSON document next to the evidence file, outside Git
  (`D:\StableNew-Assets\offline-ai\vl220-evidence\`); `write_diagnostics` refuses a Git working tree or the AI Assist root and never
  overwrites. The evidence file itself still carries no answer text (a test scans it).
- **Control request.** `--controls` (needs `--diagnostics-out`) adds, after the scored cases, an unconstrained free-text
  "describe this image" for the synthetic scenes `des-1` and `des-2` of the set being run: same executable, same admission, same
  CPU-only limits, `-n 256`, **no `--json-schema-file`**. It is not a case, has no label and is never scored. It is the only
  thing that differs in its command line (a test proves it).
- **Everything else is unchanged:** CPU only, the contained child, the attested `llama-mtmd-cli.exe` of `b11960-cpu-vision`, no
  network, the existing time and memory limits, `--generation-idle`, and no new flag (`VISUAL_ALLOWED_FLAGS` is the same 22
  flags; `--jinja` is refused by name).

## The run that needs the owner's approval (not run)

Approve by this digest: `ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7`.

| What | Count | Detail |
|---|---|---|
| Invocations | 30 | 2 sets x (13 scored cases + 2 free-text controls); one contained CPU-only child each, one at a time |
| Set 1 (128 px) | 15 | same cases as run 1, with the fixed prompts and per-case schemas; plus 2 controls |
| Set 2 (512 px) | 15 | new pinned set; plus 2 controls |
| Expected time | 5 to 10 minutes | run 1 took 2.5 to 3.8 s per case (about 3 s model load included) plus the per-case re-hash; 512 px images and the controls (up to 256 generated tokens) run longer |
| Resources | as run 1 | about 2.4 GB peak, CPU only, no GPU, no network |
| Saved (outside Git) | 2 evidence files, 2 diagnostics files | `D:\StableNew-Assets\offline-ai\vl220-evidence\run2-synthetic-128.json` / `.diagnostics.json` and `run2-synthetic-512.json` / `.diagnostics.json`: per case the raw answer, a bounded stderr head and tail and selected lines |
| Prerequisites | already in place | firewall rule and attestation for `b11960-cpu-vision`, license acknowledgement, imported pair; the 512 set's 15 PNGs are written once with `write-synthetic --set vl220-synthetic-512-1` to `D:\StableNew-Assets\offline-ai\vl220-synthetic-512` (synthetic content only, 13 MB) |

```bash
python -m tools.qualification.vl220 write-synthetic --set vl220-synthetic-512-1 --dest D:\StableNew-Assets\offline-ai\vl220-synthetic-512
python -m tools.qualification.vl220 evaluate --builtin-set vl220-synthetic-1 --evaluation-root D:\StableNew-Assets\offline-ai\vl220-eval --assets D:\StableNew-Assets\offline-ai\vl220-synthetic --acknowledgement D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b\license_acknowledgement.json --evidence-out D:\StableNew-Assets\offline-ai\vl220-evidence\run2-synthetic-128.json --diagnostics-out D:\StableNew-Assets\offline-ai\vl220-evidence\run2-synthetic-128.diagnostics.json --controls --i-have-the-plan-digest ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7 --generation-idle
python -m tools.qualification.vl220 evaluate --builtin-set vl220-synthetic-512-1 --evaluation-root D:\StableNew-Assets\offline-ai\vl220-eval --assets D:\StableNew-Assets\offline-ai\vl220-synthetic-512 --acknowledgement D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b\license_acknowledgement.json --evidence-out D:\StableNew-Assets\offline-ai\vl220-evidence\run2-synthetic-512.json --diagnostics-out D:\StableNew-Assets\offline-ai\vl220-evidence\run2-synthetic-512.diagnostics.json --controls --i-have-the-plan-digest ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7 --generation-idle
```

After an approved run the report gives, per case, the raw answer next to the reference, the stderr facts that matter (image
tokens, template, grammar) and one plain conclusion: **harness defect**, **invocation defect** or **the model does not handle
these images**. It does not call the model qualified or failed for StableNew's real use; real assets with human labels are a
separate step.

## Decision D24 (for the orchestrating session or the owner; nothing was changed)

The one remaining *invocation* suspect (I1) cannot be fixed inside the closed vocabulary: the model's own template (BOS, then
`<think>` or `<think></think>` after `assistant`) is only used with `--jinja`, and `--chat-template-kwargs '{"enable_thinking":false}'`
would be the way to select the no-thinking form. The AI-VL-220 contract left `--jinja` open (section 5, item 2) and this package
leaves it refused. If the free-text controls and the corrected structured answers still look wrong while the controls show the
model does describe the scenes (or the opposite), the next step is a diagnostic-only builder variant that adds `--jinja` (and
`--chat-template-kwargs`, with the same source proof) behind its own plan digest. That is a new flag and a new owner approval; it
is not part of this PR.

## Acceptance and evidence boundary

- Accepted outcome: the harness defects found are fixed and tested; the diagnostic mode, the control request, the second set and
  the plan digest exist; the run is prepared and **not performed**.
- Evidence mode: deterministic tests; documentation inspection of llama.cpp `b11960` source and of the pinned GGUF headers.
- Qualification claim: N/A. Nothing here sets `qualified`.
- Not demonstrated: any model behavior; whether the legacy turn (I1) matters; anything about real generated images.
- Owner decision or blocker: approval of the plan digest for the run; decision D24 if the run points at the turn.
