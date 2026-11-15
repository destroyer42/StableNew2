# PR-AI-VL-220: image invocation contract (approved by the owner 2026-11-14; implemented, never run)

## Owner decision (2026-11-14, recorded from the chat)

Owner statement (verbatim): "A: Approve. B: Approve. C: Authorize" - answering decisions A (approve this contract), B (approve
the separate `b11960-cpu-vision` build entry, a firewall Block rule and attestation) and C (authorize a first supervised, CPU-only
run on the synthetic set, then existing assets, naming plan digest
`23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e`). Recorded as given, with no change to section 3.

What this does **not** do, and what is still missing before any run is possible:

1. **Implemented since (section 7), never run.** The `b11960-cpu-vision` manifest entry, the visual argument builder and the
   driver are in the follow-up package, and `contract.INVOCATION_APPROVED` is now `True` (as is the plan field; the comparator
   reason `image_invocation_not_approved`, which read "approved and implemented", is gone). The plan digest the owner named,
   `23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e`, therefore changed by exactly that flag and that reason text
   (section 7 proves it); the digest the first supervised run executed is `fa63304dc98e6aeb0eeb8e7d922cc61d23507ef58fb4994232bd723e9e66339a`,
   after PR-AI-VL-222 (a diagnostic plan section, no change to this contract) the plan the second run executed is
   `ea7f2bb8afbeb40450561e10648a5dc1abc868322a829326555187add7d6aea7`, and after PR-AI-VL-223 (a template A/B plan section; the
   `--jinja` variant below is evaluation-only and pending the owner's approval by digest) the current digest is
   `15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536`. The owner's
   authorization (decision C) named the old digest, so the driver's `evaluate` command asks the owner to name the current one
   (`--i-have-the-plan-digest`); no run is possible until the prerequisites in items 2 to 4 exist and the owner confirms.
2. **The license acknowledgement is still the owner's act and has not been made** (record `license_acknowledgement.json`, text
   `30adf9d6...`); admission refuses without it.
3. **The firewall Block rule for `llama-mtmd-cli.exe` and the attestation for `b11960-cpu-vision`** are the owner's acts; the
   session that implements this creates no rule and records no attestation.
4. The authorization in C is for the first supervised run only (synthetic set, then existing assets once the owner has chosen
   them and a labeler); each run still needs the implementing package's own gates to pass, and it does not extend to any
   change of the plan, the invocation, the model or the projector.

Status of the text below: approved as the specification to implement. `FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`,
`build_argv`, `build_production_argv`, the runtime process authority, the firewall attestation and the protected-token
validators are unchanged by this package; the owner's wish to use LFM3-VL-2B as a comparator does not approve this contract.
A visual evaluation run is impossible until the pieces listed under the owner decision exist.

## 1. Why a separate contract

Production launches `llama-completion.exe` in raw-prompt mode with no multimodal input, and its argument vocabulary refuses
`--mmproj`, `--mmproj-url`/`-mmu` and `--rpc` (frozen: the LFM3 contract digests `FORBIDDEN_FLAGS`). Looking at an image needs a
projector file, an image file and a different executable. That crosses a security boundary (a new loadable file role, an image
decoder fed by files, a second executable to attest), so it needs an owner decision and its own, narrower path that production
cannot reach.

## 2. Findings from the llama.cpp source at the pinned tags (read as text; no binary was run)

* **Runtime.** The model needs a build with the `lfm3vl` projector: tag `b11960` has it, tag `b11840` does not
  (`tools/mtmd/clip-impl.h`); the publisher's card also says b11960 or newer. Only `b11960-cpu` qualifies.
* **Executable.** `llama-mtmd-cli.exe` is already hashed in the pinned `b11960-cpu` file map (with `mtmd.dll`, `llama.dll`,
  `ggml*.dll`, `llama-common.dll`, `libomp.dll`). `llama-completion.exe` has no multimodal code path. `llama-cli.exe` in
  b11960 is split into `cli-client`/`cli-server`/`cli-context` sources that were **not** reviewed for a listening socket, so it
  is not proposed.
* **Single turn.** `mtmd-cli` is single-turn only when both a prompt and at least one `--image` are given
  (`is_single_turn = !prompt.empty() && !image.empty()`); otherwise it enters an interactive chat that reads stdin. The builder
  must therefore refuse an empty prompt file or a missing image, and the child's stdin stays closed (`run_bounded` already does).
* **Flag acceptance** (parsed from `common/arg.cpp` at `b11960`; "COMMON" means the default set every example accepts):

| Flag | Accepted by `mtmd-cli` | Proposed |
|---|---|---|
| `--offline`, `-ngl`, `-f`, `--json-schema-file`, `-c`, `-n`, `-t`, `--temp`, `--top-p`, `--top-k`, `--min-p`, `--presence-penalty`, `--repeat-penalty`, `--seed`, `--prio` | yes (COMMON) | yes, values from typed parameters |
| `-m`, `--mmproj` | yes (`mmproj_examples`) | yes: **the only place `--mmproj` would ever appear**; path inside the evaluation root, hash-verified |
| `--image` | yes (`MTMD, CLI`) | yes: one file per case (two for before/after), copied to a private work directory |
| `--no-mmproj-offload`, `-mmdev none` | yes (`mmproj_examples`) | yes: keep the projector on the CPU |
| `--image-min-tokens`, `--image-max-tokens` | yes (`mmproj_examples`) | yes: bound image memory (values set from the first supervised measurement) |
| `--jinja` | yes | **refused by default**; a named, evaluation-only turn-format variant adds exactly this switch (section 7, PR-AI-VL-223). The legacy engine's use was confirmed by run 2's log; whether `--jinja` changes answers is the A/B, pending the owner's digest approval |
| `--log-disable` | accepted | **no**: it pauses the log that prints the generation, so stdout would be empty |
| `--no-conversation`, `--no-display-prompt`, `--reasoning` | **not accepted** | no (not needed; single-turn is implied) |
| `-p` | yes | **no**: the prompt goes in a file (`-f`), never on a command line other processes can read |
| `-hf`, `-mu`, `--mmproj-url`/`-mmu`, `--rpc`, `--host`, `--port`, `--lora`, `--control-vector`, `--media-path` | (various) | **never**; stay forbidden |

Raw prompt mode does not exist here: `mtmd-cli` applies the model's chat template to a user message that carries the image
marker. The text models' "prompt exactly as written" property therefore does not hold for the visual arm, and a visual result
must not be compared with a text result as if it were raw-prompt equivalent.

## 3. Proposed shape (for approval)

1. **A separate pinned build entry, not a second executable on the existing one.** Runtime build entries carry one
   `executable`, and the firewall attestation binds `(build id, executable)`. Propose a new manifest entry `b11960-cpu-vision`:
   the same archive and the same per-file hashes as `b11960-cpu`, `executable: llama-mtmd-cli.exe`, `qualified: false`, listed
   in **no** model's `compatible_builds`, so the selector, Preview and `import-model` can never reach it. The operator records
   an attestation for it (`record-attestation --build-id b11960-cpu-vision`) after creating an outbound Block rule for
   `llama-mtmd-cli.exe` (the owner's act; this package creates no rule).
2. **A closed visual vocabulary and builder in the harness package**, never in `src/ai_assist/argv.py`: its own allow-list
   (the "yes" rows above), a refusal of every forbidden flag, a check that the model, projector and image paths resolve inside
   the evaluation root or the private work directory, and an assertion that exactly one `--mmproj` appears.
3. **The existing contained-child launcher.** The driver calls `run_bounded` (own OS container, wall-clock timeout, output
   cap, cooperative cancellation that kills the tree, scrubbed environment from `build_environment`, `PATH` set to the runtime
   directory). It adds no `subprocess` call of its own, starts no thread beyond what `run_bounded` already uses, opens no
   socket.
4. **Admission, fail-closed, before every launch**: candidate admitted by `check_admission` (pinned bytes, matching header,
   required build, license acknowledgement), attestation covers `(b11960-cpu-vision, llama-mtmd-cli.exe)`, single-flight,
   no generation activity, memory headroom, image pre-checks in Python (PNG/JPEG signature, at most 8 MiB, at most 4096 x 4096,
   header read only). A refusal is a stable code and runs nothing.
5. **Output handling**: stdout only, bounded; strip exactly one trailing end-of-text marker as production does; strict
   `json.loads`, then `validate_response`. stderr is bounded and never persisted; it is shown only in memory, as production does.
6. **Evidence**: per-case wall time and peak working set from the container, the argv hash (never the paths or prompt text),
   exit code, the validation reason. No image, prompt or answer text is written to an event log.
7. **No GPU**: `-ngl 0`, `--no-mmproj-offload`, `CUDA_VISIBLE_DEVICES=-1`, and the CPU-only `b11960-cpu` archive. No ETW capture is
   proposed; the AI-114 containment evidence is a separate qualification question.

## 4. What this contract would not allow

Any use of the visual candidate by the application; any entry in the text registry or `compatible_builds`; any download or
network access; `--mmproj` anywhere in `src/`; an unattested or unhashed executable; a projector other than the pinned file
(Q8_0 and BF16 are listed but not approved); video or audio input; more than one process at a time; any change to
`FORBIDDEN_FLAGS`, `ALLOWED_FLAGS`, `build_argv` or the frozen AI-111/AI-115 identities.

## 5. Unverified without a supervised run (held)

1. That `llama-mtmd-cli.exe` of `b11960-cpu` loads the Q4_K_M model with the F16 projector at all, and its CPU memory and speed.
2. Whether the legacy template engine renders the LFM3 chat template or `--jinja` is needed (and whether `--jinja` is
   accepted together with the grammar). Run 2's log showed the legacy ChatML turn in use; the `--jinja` A/B of PR-AI-VL-223 is
   prepared and not run.
3. That a trailing end-of-text marker and blank lines behave as with `llama-completion` (the strip is tolerant).
4. That `--json-schema-file` constrains `mtmd-cli` decoding as the source suggests (`common_sampler_init` is used).
5. The right `--image-max-tokens`.

## 6. Owner decisions

* **A.** Approve this contract, approve it with changes, or decline (then the harness stays a specification). **Approved 2026-11-14.**
* **B.** Approve the separate `b11960-cpu-vision` build entry and its firewall rule and attestation (a follow-up package would
  add the manifest entry, the driver and its tests). **Approved 2026-11-14.**
* **C.** Authorize a first supervised, CPU-only run on the synthetic set, then on existing assets, naming the plan digest
  (`PR-AI-VL-220_Visual_Evaluation_Contract.md`). **Authorized 2026-11-14** for the first supervised run only (see the owner
  decision above for the conditions still unmet).

## 7. Implementation (delivered; nothing was run)

* **Build entry.** `config/managed_ai_runtime.json` pins `b11960-cpu-vision`: the same archive and per-file hashes as
  `b11960-cpu`, `executable: llama-mtmd-cli.exe`, `qualified: false`, listed in no model's `compatible_builds`. Tests prove the
  selector, Preview, activation (`build_incompatible`) and `import-model` cannot reach it, and that the frozen AI-111/AI-115
  identities (Qwen screening plan `17814e40...`, final plan `3017c427...`, corpus `a89297be...`, LFM3
  `FROZEN_CONTRACT_SHA256` `41e65d67...`) did not move: their digest tests pass unmodified. The only existing assertion changed is
  the list of shipped build ids in `tests/ai_assist/test_manifests.py`. The operator reaches the entry through
  `ai_assist_admin import-runtime --build-id b11960-cpu-vision` and `record-attestation`; the attestation file is one record, so
  name **every** build you attest in the same command (a new record replaces the old one).
* **Vocabulary and builder.** `tools/qualification/vl220/visual_argv.py`: exactly the "yes" rows of the section 2 table, one
  `--mmproj` inside the evaluation root, images and the prompt/schema files inside a private work directory, refusal of an empty
  prompt file, a missing image, `-p`, `--log-disable`, `--jinja`, `-hf`/`-mu`/`--mmproj-url`/`--rpc` and every other flag, a
  check of the finished command line (`check_visual_argv`), and a path-free argv hash for evidence. `src/ai_assist/argv.py` is
  byte-identical. Image values `--image-min-tokens 64` / `--image-max-tokens 256` are conservative starting points, owner-tunable
  and bounded, because section 5 item 5 (the right value) is still unverified.
* **Driver.** `tools/qualification/vl220/driver.py` launches through `run_bounded` only (an AST scan proves no `subprocess`,
  thread or socket code), with `build_environment` (no proxy, `CUDA_VISIBLE_DEVICES=-1`, `PATH` = the runtime directory,
  `TEMP` = the per-case work directory). Admission, before every launch and in this order: the contract flag; the evaluation
  root is neither the AI Assist root nor a Git tree; single-flight (an exclusive `vl220.lock` file in the evaluation root; a
  stale lock after a hard crash is removed by the operator, never by killing anything); generation idle (an injected reading,
  absent or unreadable means refuse); the vision build is pinned, hash-identical to `b11960-cpu`, unqualified and unreachable
  from any model, the unpacked runtime re-hashes, and the attestation covers `(b11960-cpu-vision, llama-mtmd-cli.exe)`; memory
  headroom for model, projector and a 4 GiB margin; every image matches its pin and its PNG/JPEG header (at most 8 MiB and
  4096 x 4096); then `check_admission` (pinned bytes, GGUF headers, required build, license acknowledgement). Each refusal is a
  stable code and runs nothing. The model and projector are re-hashed for every case (a few seconds each).
* **Output and evidence.** stdout only and bounded; one trailing end-of-text marker stripped; strict `json.loads` (no duplicate
  keys, no `NaN`); then `validate_response`. Evidence per case: wall time, peak working set and private bytes, the path-free argv
  hash, exit code, reason code. The prompt and images exist only in a per-case work directory that is removed when the case ends;
  raw answers stay in memory to be scored. A test scans every file under the evaluation and AI roots and the evidence for prompt,
  element, answer and image bytes. A failed case in a set is scored as a wrong answer, never skipped; the first admission refusal
  stops the set.
* **CLI.** `python -m tools.qualification.vl220 evaluate ...` refuses unless `--i-have-the-plan-digest` equals the current plan
  digest and `--generation-idle` is given (a separate process cannot read the application's queue); it never overwrites an
  evidence file. It is the only command that can launch the runtime and is never run by tests, CI or any gate against the real
  runtime.
* **The plan digest.** Flipping the flag and dropping the comparator reason changed the plan digest from `23df6fa4...880e` to
  `fa63304dc98e6aeb0eeb8e7d922cc61d23507ef58fb4994232bd723e9e66339a`. A test rebuilds the plan, sets
  `image_invocation.approved` back to `false`, restores the reason `image_invocation_not_approved` to the candidate comparator and
  reproduces `23df6fa436f4e4292b4421e5155ee232729ea1b4942ff8b6807b50dbc755880e` exactly, so those two edits are the only difference.

* **Diagnostic mode (PR-AI-VL-222, decision D23 of the orchestrating session under the owner's delegation).** One narrow exception to "no
  answer text and no runtime output persisted": for a case set that is exactly a built-in synthetic set (same case and label document
  digests, labeler `synthetic_by_construction`, every asset digest the pinned one) the driver may capture the raw answer and a bounded
  head and tail of the runtime's stderr into a separate diagnostics document next to the evidence file, outside Git. For any other case
  set the capture cannot be constructed and the rule above stands (a test proves the refusal). The same package adds an unscored
  free-text control request (no `--json-schema-file`, same executable, admission and limits) and **no flag**; `--jinja` stays refused.
  See `docs/work_packages/AI-VL-222_visual_diagnostic.md`.

* **Template A/B (PR-AI-VL-223, decision D24; evaluation-only, pending the owner's approval by plan digest, not run).** The visual
  argument builder's existing `use_jinja` switch (used by the Gemma candidate) may also be set for the LFM candidate. Without it the
  command line is exactly the one above. With it the single switch `--jinja` is appended at the end, so the turn is rendered from
  the pinned GGUF's own template (BOS first, generation prompt ending in an open `<think>`); `--jinja` stays in the refused list for
  every other use and is accepted only when the check is asked for `use_jinja=True` and it appears exactly once. For LFM the driver
  refuses it unless a diagnostic capture exists (so only for a built-in synthetic set); the strict containment checks stay Gemma-only. `--chat-template-kwargs`, the `--reasoning` family and every template or template-file flag stay
  refused: b11960's `llama-mtmd-cli` does not register the first two (`common/arg.cpp`), so a no-thinking turn cannot be requested.
  Nothing is promoted and `qualified` stays false. See `docs/work_packages/AI-VL-223_template_ab.md`.

Still missing before any run (none is created by the implementing package): the license acknowledgement
(`license_acknowledgement.json`, text `30adf9d6...`), the owner's outbound Block rule for `llama-mtmd-cli.exe` and the attestation
for `b11960-cpu-vision`, the import of the pair into an evaluation root, and for existing assets the owner's chosen images and a
human labeler. The first supervised CPU-only run is not started; the owner confirms in chat once each exists.
