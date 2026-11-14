# AI-202: a runtime invocation the pinned builds accept, and an in-app model selector

Status: **AI-202a merged (PR #303); AI-202c implemented (section 10)**; AI-202b (model selector, section 9) follows in its own PR.
Execution class: **Standard**. Model recommendation: Claude Code, Sonnet 5.5, medium effort (bounded, evidence-led,
no architecture change); Codex equivalent per `docs/AI_MODEL_SELECTION.md`.
Controller Surface Assessment: `ai_assist_integration.py` gains one status message and no new responsibility; no ceiling
changes.

## 1. Why

On the owner's machine (first physical activation, 2026-11-13) every Suggest / Advise request ended `UNAVAILABLE` /
`child_exit_nonzero` after about 90 ms with about 0.4 MB peak memory: the child exits during argument parsing. Nothing was
executed to establish the cause; it was read from the llama.cpp source at the two pinned tags (`b11840`, `b11960`, the
files `common/arg.cpp`, `common/arg.h`, `common/log.cpp`, `common/log.h`, `common/console.cpp`,
`tools/completion/completion.cpp`, `tools/cli/cli.cpp`, fetched as text with `gh api`; no binary or model was run).

## 2. Findings (all from upstream source, identical in both tags unless noted)

The three files `tools/completion/completion.cpp`, `tools/cli/cli.cpp` and `common/log.cpp`/`log.h` are byte-identical
between `b11840` and `b11960`. `common/arg.cpp` differs only in download/cache code (`finalize_file`, `--models-memory-margin`,
`--tts-voice`, message text), none of it touching a flag StableNew passes. Line numbers below are `b11840` / `b11960`.

1. **`llama-cli.exe` rejects `--no-conversation`.** It is registered with `.set_examples({LLAMA_EXAMPLE_COMPLETION})` only
   (`common/arg.cpp:1906-1915` / `1914-1923`). `llama_cli()` parses with `LLAMA_EXAMPLE_CLI` (`tools/cli/cli.cpp:40`),
   so the flag is not in its option table and parsing throws `error: invalid argument` (`arg.cpp:1223`) and returns 1.
2. **`llama-completion.exe` parses with `LLAMA_EXAMPLE_COMPLETION`** (`tools/completion/completion.cpp:94`) and accepts
   every flag StableNew passes (table in section 3).
3. **`--log-disable` would leave stdout empty.** The tool prints the generated text through `LOG("%s", token_str)`
   (`completion.cpp:707`), the common log at level NONE, which is written to stdout (`common/log.cpp:100-103`).
   `--log-disable` calls `common_log_pause(common_log_main())` (`arg.cpp:3914-3920` / `3929-3935`), and a paused log
   **discards** what is written to it (`common/log.cpp:245-247`, "discard messages while the worker thread is paused").
   The flag is therefore unsafe for a tool whose output is that log. Production no longer passes it.
4. **A generation that ends on an end-of-generation token is followed by `" [end of text]\n"` on stdout** (`LOG(" [end of
   text]\n")`, `completion.cpp:927-930`; `params.interactive` is false in raw mode) and the tool ends with `LOG("\n\n")`
   (`completion.cpp:949`). Informational lines (`LOG_INF`, `LOG_WRN`, `LOG_ERR`) go to stderr (`log.cpp:102-103`), so no
   banner reaches stdout. `validate_output` parses stdout with strict `json.loads`; the marker would make every successful
   generation `MALFORMED`. `runtime.strip_end_of_text` removes exactly one trailing `[end of text]` (and the whitespace
   around it, including the Windows CR LF) before validation.

## 3. Chosen invocation and per-flag proof

Launch **`llama-completion.exe`** (both builds already hash it and `llama-completion-impl.dll` in their pinned file maps)
with `build_production_argv` = the frozen `build_argv` minus `--log-disable`:

```
--offline -ngl 0 --no-display-prompt --no-conversation --reasoning off --prio -1 -m <model> -f <prompt file>
--json-schema-file <schema file> -c N -n N -t N --temp X --top-p X --top-k N --presence-penalty X --seed N
```

`arg.cpp` filters options with `add_opt` (`arg.cpp:1438-1445`): an option is kept for the tool when its example set holds
that tool **or** `LLAMA_EXAMPLE_COMMON`, which is the default set (`common/arg.h:23`). "COMMON" below means that default.

| Flag | Registration (`b11840` / `b11960`) | Accepted by `llama-completion` | `llama-cli` |
|---|---|---|---|
| `--offline` | `arg.cpp:3973 / 3988`, examples `COMMON, DOWNLOAD, TOKENIZE` | yes (COMMON) | yes |
| `-ngl` | `2803 / 2811`, COMMON | yes | yes |
| `--no-display-prompt` | `1495-1501 / 1503-1509`, `COMPLETION, CLI` | yes | yes |
| `--no-conversation` (`-no-cnv`) | `1906-1915 / 1914-1923`, `COMPLETION` | **yes** | **no (this was the failure)** |
| `--reasoning` | `3731-3747 / 3746-3762`, `SERVER, COMPLETION, CLI` | yes | yes |
| `--prio` | `1567 / 1575`, COMMON | yes | yes |
| `-m` | `3049-3056 / 3057-3064`, `COMMON, EXPORT_LORA, DOWNLOAD, TOKENIZE` | yes (COMMON) | yes |
| `-f` | `1805 / 1813`, COMMON, excludes `SERVER` only | yes | yes |
| `--json-schema-file` | `2293-2307 / 2301-2315`, COMMON (`set_sampling`) | yes | yes |
| `-c`, `-n`, `-t` | `1642 / 1650`, `1661 / 1669`, `1520 / 1528`, COMMON | yes | yes |
| `--temp`, `--top-k`, `--top-p`, `--presence-penalty`, `--seed` | `2019, 2028, 2036, 2108, 1998 / 2027, 2036, 2044, 2116, 2006`, COMMON | yes | yes |
| `--log-disable` (dropped) | `3914 / 3929`, COMMON | accepted, but see finding 3 | yes |

### The five requirements, for both builds

* **(a) Every flag is accepted by the tool launched.** Table above; `llama-completion` is the only one of the two that
  accepts all of them. Not executed; a test (`tests/ai_assist/test_ai202a.py`) pins the emitted flag set to this table.
* **(b) The prompt is read from a file and the process exits after one generation with no interactive wait.** `-f` reads the
  file into `params.prompt` and drops one trailing newline (`arg.cpp:1808-1812`). `--no-conversation` sets
  `COMMON_CONVERSATION_MODE_DISABLED` (`arg.cpp:1913`), so `completion.cpp:171-180` does not auto-enable conversation mode,
  `params.interactive` and `interactive_first` stay at their default `false` (they are set only by `-i`/`-if` or inside
  `params.conversation_mode`, `completion.cpp:365-376`), and the generation loop ends at `n_predict` or the first
  end-of-generation token (`completion.cpp:544`, `927-931`), then returns 0 (`completion.cpp:954`). stdin is never read
  (the only reads are in the interactive branch, `completion.cpp:803-860`), and `run_bounded` closes it anyway.
  `-st`/`--single-turn` is not needed: it only matters inside conversation mode. The Windows console setup
  (`common/console.cpp:90-136`) treats a piped stdout as non-console and switches to simple I/O.
* **(c) Output is constrained by the JSON-schema file.** `--json-schema-file` converts the schema to a grammar and stores
  it as `params.sampling.grammar` (`arg.cpp:2306`); `completion.cpp:143-147` obtains the sampler from
  `common_init_from_params`, and every sampled token is accepted with `accept_grammar=true` (`completion.cpp:669`; prompt
  tokens skip it, `completion.cpp:694`). Once the object is complete only an end-of-generation token is permitted.
* **(d) Only the generation reaches stdout, as far as the source shows.** `--no-display-prompt` clears `params.display_prompt`
  (`arg.cpp:1495-1501`), so the prompt is not echoed (`completion.cpp:513, 704`). Banner, system info, timings and the
  sampler summary are `LOG_INF` (stderr). What the source shows on stdout besides the generation is the end-of-text line and
  blank lines (finding 4), which the runtime strips. `--log-disable` is the one flag that would have emptied stdout
  (finding 3) and is dropped.
* **(e) Chat template.** `framing.py` renders **plain text with no chat markup** (an instruction paragraph, delimiter lines
  and the authored data). With `--no-conversation` the prompt file is tokenized exactly as written
  (`completion.cpp:272-274`, "otherwise use the prompt as is"; `common_tokenize(ctx, prompt, true, true)`, BOS added when the
  model's vocabulary asks for it). The model's own chat template is **not** applied, which is also how the qualification
  corpus was designed. `--reasoning off` sets `params.enable_reasoning = 0` and a template keyword
  (`arg.cpp:3731-3745`); in raw mode nothing renders a template, `completion.cpp` never reads `enable_reasoning`, and the
  keyword reaches only a log line in conversation mode (`completion.cpp:193`). So the flag is accepted and inert here;
  what actually prevents a `<think>` block is the grammar, which admits only the JSON object from the first generated token.
  It is kept because it is harmless, accepted by both tools and part of the vocabulary the frozen plans digest.

## 4. What remains unverifiable without a real run

Nothing was executed, so these are source-derived expectations, not observations. The owner's first run settles them:

1. That the Windows loader resolves `llama-completion-impl.dll`, `llama.dll`, `ggml*.dll` and `libomp.dll` from the runtime
   directory (`PATH` is set to it by `build_environment`; both libraries are hashed in the pinned maps).
2. That a real stdout ends exactly as described in finding 4 (the strip is tolerant of CR LF and of the `\n\n`).
3. That Qwen3.5 and LFM3 follow the one-JSON-object instruction well in raw-prompt mode (no chat markup). The grammar
   guarantees valid structure, not good content; quality remains the qualification package's question.
4. That `b11840` loads the Qwen3.5 GGUFs and `b11960` loads LFM3 (compatibility is architecture-based, AI-201b).
5. That stderr contains the error line of a load failure within the 64 KiB `run_bounded` captures (only its tail,
   at most 2 KiB, is kept for display).
6. Memory/time behaviour of the CPU run; timeouts stay the existing bounds.

## 5. Frozen identities

The AI-111/AI-115 harness digests `ALLOWED_FLAGS`, `FORBIDDEN_FLAGS` and the argv `build_argv` emits (Qwen screening plan
`17814e40...`, final plan `3017c427...`, LFM3 `FROZEN_CONTRACT_SHA256` `41e65d67...`). None of those constants or functions
changed and no digest literal was edited: production gets its own `PRODUCTION_ALLOWED_FLAGS` and `build_production_argv`, and
`AiRuntime` defaults to them; the physical harness now passes `build_argv`/`ALLOWED_FLAGS` explicitly for its default arm
(`_argv_options`), so its behaviour is unchanged. It also re-records its attestation with coverage for its derived build
(section 7). `FORBIDDEN_FLAGS` was not grown for the same reason (the LFM3 contract digests it); the production allow-list is
closed, so every flag not listed is refused, forbidden or not. `tests/tools/test_ai111_final.py` and
`test_ai115_lfm3_contract.py` (digest tests) pass unchanged.

## 6. Diagnosability (privacy-safe)

`RuntimeResult`/`AssistOutcome` carry the child's integer `exit_code` (also in `outcome.details` and as the new content-free
`exit_code` event field) and an in-memory `RuntimeDetail`: the **last** 2 KiB of stderr and, for `MALFORMED` only, the
**first** 2 KiB of stdout. They are never written to `events.jsonl`, a log or a file, are excluded from `repr`, and a
suggestion or model refusal carries none. The AI suggestion review dialog shows them only behind an explicit
"Show runtime detail" button, under the label "Raw runtime output, not reviewed by StableNew ...", and clears them when a new
request starts or the dialog closes. Tests assert the event log holds the integer and no runtime text.

## 7. Attestation binding (owner decision D19)

A firewall rule is bound to one program, so an attestation now lists the `(build id, executable name)` pairs it covers
(`egress_attestation.json` schema 2). The service returns `EGRESS_NOT_ATTESTED` (`operator_attestation_missing`) unless the
active build id and its pinned executable name are covered; a legacy schema 1 free-text record covers nothing. Status
reports `egress` as `attested`, `not_covered` (a record exists but not for the active build/executable) or `not_attested`.
`record-attestation` requires `--build-id` (repeatable), looks the executable up in the pinned manifest and prints what it
recorded. After AI-202a the owner must re-record the attestation and create a firewall rule for **`llama-completion.exe`**
(the old rule was for `llama-cli.exe`); the exact commands are in `docs/runbooks/ai_assist_preview_activation.md`.

## 8. Acceptance and evidence boundary (AI-202a)

Delivered and demonstrated by deterministic tests: pinned executables and impl libraries; production argv; end-of-text
handling; exit code, bounded detail and no-content event log; attestation binding in the service, status and admin tool.
**Held / unverified:** every item of section 4; no binary was executed, the first real run is the owner's. The coordinating session relayed an owner authorization for supervised test runs, but the session's permission layer denied launching the runtime, so the prepared run (3 build/model pairs, every suggestion kind, `--version`/`--help`) was **NOT RUN**; read-only preconditions seen: enabled outbound Block rules exist for both `llama-completion.exe` paths. Nothing here is
qualification, and `qualified` stays `false`.

## 9. AI-202b (planned, separate PR after 202a merges)

In-app model selector in the AI Preview dialog (decisions D20 recorded with that PR): installed and verified models with
trust label and size; an explicit per-model list of compatible pinned builds (LFM3: `b11960-cpu` only) with disabled
reasons; activation through the one shared function the admin tool uses; multi-identity Preview enablement with migration of
the single-identity record; refusal while a request is in flight; the attestation rule of section 7 applied per selection.

## 10. AI-202c: the output schema must force a complete answer

Execution class: **Standard** (one module, pure function, deterministic tests). Model recommendation: Claude Code, Sonnet 5.5,
medium effort. Controller Surface Assessment: none; no controller or coordinator code is touched.

### 10.1 Finding

After PR #303 the owner's first real run reached the model: the last `events.jsonl` record shows kind `plan_proposal`, exit
code 0, 7086 ms, 2.47 GiB peak, `output_chars` 52, outcome `malformed`, reason `kind_mismatch`. The invocation works. 52
characters is exactly `{"schema": "ai_assist.suggestion/1", "status": "ok"}`.

Root cause: `framing.build_json_schema` declared `required = ["schema", "status"]` for every kind, so the grammar admitted an
object with no `kind` and no payload, the small model stopped as soon as the grammar allowed it, and `validate_output`
(`validators.py`, the `kind` comparison) answered `kind_mismatch`. All four kinds were affected. The grammar guaranteed valid
JSON, not a complete answer.

### 10.2 Fix

`build_json_schema` now returns `{"oneOf": [ok_branch, refused_branch]}`:

* **ok branch** - `status` const `ok`; required `schema`, `status`, `kind` and the kind's payload (`positive` + `negative`;
  `target`; `workflow`; `steps`); `changes` stays optional; `additionalProperties: false`; properties ordered `schema`,
  `status`, `kind`, payload, `changes`.
* **refused branch** - `status` const `refused`; required `schema`, `status`, `refusal_reason` (at most 400 characters);
  `additionalProperties: false`.

The two-field document therefore matches neither branch. The schema is deliberately stricter than the validator in two places
(`negative` of a rewrite and `refusal_reason` of a refusal are required by the grammar although the validator would tolerate
their absence); a test names that difference so it cannot grow unnoticed. The runtime also stopped writing the schema file with
`sort_keys=True`: both pinned tags emit properties in file order, so sorting would have moved `kind` ahead of `schema`.

### 10.3 Grammar-support proof (llama.cpp source at both pinned tags; nothing was executed)

Fetched as text with `gh api` from `ggml-org/llama.cpp`: `common/json-schema.cpp` (the schema parser,
`common_chat_schema_builder`), `common/json-schema-to-grammar.cpp` (the converter) and `common/arg.cpp`. Between `b11840` and
`b11960` the two schema files differ **only** in recursion-depth guards (`COMMON_RECURSIVE_LIMIT` is 128 in `b11960`) and in how
rule names are escaped (a hand-written loop instead of `std::regex`); the parse and conversion logic of every construct below
is the same. This schema nests about seven levels and uses no `pattern`, so neither difference applies. Line numbers are
`b11840` / `b11960`.

| Construct | Parser (`json-schema.cpp`) | Converter (`json-schema-to-grammar.cpp`) |
|---|---|---|
| `oneOf` (and `anyOf`) | `234-235 / 253-254`: either key makes an `any_of` node of the children; **a sibling keyword is never read**, so the root holds only `oneOf` | `884 / 916`: the children become alternatives of one rule; `oneOf` is not exclusive-or here, which is harmless because the `status` constants are disjoint |
| `const` | `257 / 276`, checked before `enum` and `type` | `888 / 920`: a literal of the JSON text |
| `enum` with `null` | `260 / 279`: a non-empty array, each value kept as JSON (an empty one is an error, which is why request validation requires non-empty closed lists) | `890 / 922`: each value dumped as a literal, so `null` becomes the literal `null` |
| `required` | `137 / 149`: a property is required when named | `910 / 942`: required properties first, in property order, then the optional ones |
| `additionalProperties: false` | `155-162 / 167-174`: no extra-property rule is built | `910 / 942`: only the declared keys can be emitted |
| `minItems` / `maxItems` | `192-193 / 204-205` | `931 / 963`: bounded repetition of the item rule |
| `maxLength` | `208 / 220` | `948 / 980`: bounded repetition of the `char` rule |
| integer `minimum` / `maximum` | `214, 219 / 226, 231` | `959 / 991`: `build_min_max_int` |

`common_json` keeps object keys in insertion order in both tags (`common/json.h`: "object keys keep the order in which they are
added"), which is what makes the property order in the schema file meaningful. `--json-schema-file` feeds
`json_schema_to_grammar(json::parse(...))` (`arg.cpp:2306 / 2314`). `tests/ai_assist/test_ai202c.py` carries the closed keyword
list above and fails on any schema node that uses another keyword, so an unproven construct cannot slip in later.

### 10.4 Frozen identities

Determined before editing: nothing in `tools/qualification/ai111/` (the Qwen screening plan `17814e40...`, the final plan
`3017c427...`, the corpus `a89297be...`, `lfm3_contract.py` and its `FROZEN_CONTRACT_SHA256` `41e65d67...`) digests the output of
`build_json_schema`, the text of `render_prompt` or the source of `framing.py`. They digest corpus cases, the argv vocabulary
(`ALLOWED_FLAGS`, `FORBIDDEN_FLAGS`, `build_argv`) and sampling profiles; `execution_evidence` calls `render_prompt` only to
reproduce the reserved-marker refusal. So `build_json_schema` was edited in place (no second schema authority), `render_prompt`
and `argv.py` are untouched, and the four digests are unchanged (the digest tests pass unmodified). One consequence to know:
the physical qualification harness builds its runtime from `AiRuntime`, so a future run of it constrains decoding with the new
schema. The frozen plans do not pin the grammar, and the new schema is the one production uses, which is what a qualification
should measure; any earlier harness result was measured against the weaker grammar.

### 10.5 Review dialog

"Show runtime detail" now begins with the exit code and the validation reason code (for example `kind_mismatch`), then shows the
stdout head, then the stderr tail. The reason is the same fixed token the event log already records. In the owner's screenshot
the box showed five stderr lines and no model output; the stdout head was placed after the long stderr tail, so it was at best below the visible part (inferred from the layout, not observed). Nothing else changed: the
text is in memory only, never saved, bounded to 2 KiB per stream, and cleared on a new request and on close.

### 10.6 Acceptance and evidence boundary

*Implemented and demonstrated by deterministic tests:* the two-field document is rejected by the production schema (and by the
validator) for all four kinds; one validator-accepted document per kind, with and without `changes`, and a refusal satisfy the
schema; the schema's required fields are measured against the validator so the two cannot drift; property order and the closed
keyword list; the runtime writes the schema in declared order; the reason code and the stdout-before-stderr order in the detail
text; the reason reaches the dialog text for malformed and failing outcomes and never reaches the event log with runtime text.

*Held / unverified without a real run:* that the pinned `llama-completion.exe` binaries accept this exact schema file (the proof
is from source; the binaries were not run); that Qwen3.5 and LFM3 now produce a complete, well-formed answer for every kind
within the token budget (`-n`) when they cannot stop early, including whether the alternation slows grammar sampling noticeably
on CPU; and answer quality, which stays the qualification package's question. A model that fills the grammar badly still ends
as `malformed` with its reason, never as a suggestion. Nothing here is qualification and `qualified` stays `false`.
