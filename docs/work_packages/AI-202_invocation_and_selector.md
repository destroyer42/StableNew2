# AI-202: a runtime invocation the pinned builds accept, and an in-app model selector

Status: **AI-202a implemented (PR 1)**; AI-202b (model selector) follows in a second PR after 202a merges.
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
