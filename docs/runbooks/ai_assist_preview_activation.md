# AI Assist Preview activation (operator runbook)

Authority: `docs/Subsystems/AiAssist/AI_ASSIST.md` (owner decisions D13 to D19, 2026-11-13). This runbook takes you from
staged files to a first **Suggest** in the Prompt tab. It uses only local files: StableNew never downloads, updates or
resolves anything, and none of the steps below runs the runtime or the model except the final Suggest request.

**What Preview means.** The model is registered but **not qualified**. It runs on this computer only, on the CPU, offline,
and only suggests. Every Preview surface says "AI Assist Preview: unqualified model". Nothing changes in your prompt until
you review a suggestion and press Accept. Preview does not set `qualified` anywhere; it is revocable at any time.

Run all commands from the repository root with the project interpreter, for example
`C:\Users\rob\projects\StableNew-main\.venv\Scripts\python.exe -m tools.ai_assist_admin ...`. Add `--root <dir>` before the
sub-command to use a different AI directory (default: `STABLENEW_AI_DIR`, else `%LOCALAPPDATA%\StableNew\ManagedAi`).

## 1. Pin the runtime build (reviewed pull request)

`config/managed_ai_runtime.json` pins two unqualified builds today (`b11840-cpu` for the Qwen models, `b11960-cpu` for LFM3; AI-201a/b); to pin another, compute the entry from the staged archive; this only **reads** the zip
(archive SHA-256 plus the SHA-256 of every loadable `.exe`, `.dll`, `.so`, `.dylib`, script file) and extracts nothing:

```bash
python -m tools.ai_assist_admin describe-runtime D:\staging\llama-bNNNN-bin-win-cpu-x64.zip --build-id bNNNN-cpu --upstream-repository https://github.com/ggml-org/llama.cpp --upstream-tag bNNNN --license-spdx MIT --executable llama-completion.exe
```

Paste the printed JSON into the `builds` array of `config/managed_ai_runtime.json` in a reviewed PR. Leave
`"qualified": false`. The reviewer must check the archive hash against what you staged and the executable path.

## 2. Import the runtime and a registered model

The LFM3-1.7B models (D18) need build `b11960-cpu`; activating one with `b11840-cpu` fails closed as `UNAVAILABLE` (no `lfm3` architecture). The b11960 archive also contains `ggml-rpc.dll` and `ggml-rpc-server.exe`: `--rpc` stays forbidden and the server is never launched.

```bash
python -m tools.ai_assist_admin import-runtime D:\staging\llama-bNNNN-bin-win-cpu-x64.zip --build-id bNNNN-cpu
python -m tools.ai_assist_admin import-model D:\staging\Qwen3.5-9B-Q4_K_M.gguf --model-id <model_id from config/ai_model_registry.json>
python -m tools.ai_assist_admin activate --build-id bNNNN-cpu --model-id <model_id>
```

`activate` also voids any earlier Preview enablement; enable it again in step 4.

StableNew launches **`llama-completion.exe`** from the runtime directory (`%LOCALAPPDATA%\StableNew\ManagedAi\runtimes\<build id>\`). It is not `llama-cli.exe`: that tool rejects the flag StableNew needs and was the cause of the first run's `child_exit_nonzero`.

## 3. Record the firewall attestation

A firewall rule applies to one program, so the attestation is bound to the runtime builds and the executable it covers (D19).
You create and maintain the outbound block yourself; StableNew never creates, changes or checks it. From an **elevated**
PowerShell, create one rule per pinned build for the executable StableNew launches, `llama-completion.exe`
(a rule for the old `llama-cli.exe` covers nothing now):

```powershell
New-NetFirewallRule -DisplayName "StableNew AI Assist b11840-cpu llama-completion.exe outbound block" -Direction Outbound -Action Block -Profile Any -Program "$env:LOCALAPPDATA\StableNew\ManagedAi\runtimes\b11840-cpu\llama-completion.exe"
New-NetFirewallRule -DisplayName "StableNew AI Assist b11960-cpu llama-completion.exe outbound block" -Direction Outbound -Action Block -Profile Any -Program "$env:LOCALAPPDATA\StableNew\ManagedAi\runtimes\b11960-cpu\llama-completion.exe"
```

Create the rule only for the builds you use (b11960 is the one LFM3 needs). Then record that you did, naming the same
builds; the tool looks the executable name up in the pinned manifest and prints what it recorded:

```bash
python -m tools.ai_assist_admin record-attestation --statement "Windows Firewall outbound block: StableNew AI Assist llama-completion.exe" --build-id b11840-cpu --build-id b11960-cpu
```

The service refuses with `EGRESS_NOT_ATTESTED` when the active build id or its executable name is not covered; a record
made before AI-202a (free text only) counts as not attested, so re-record it. `status` shows what is covered.

Preview still requires this (D16): `strict_offline` is the preventive egress barrier that stands in for ETW evidence.

## 4. Enable Preview

Start the application, open the **Prompt** tab, press **AI Preview...**. Read the statement, then **Enable AI Assist
Preview**. The record binds the exact model SHA-256 and runtime build id and holds no prompt content. **Revoke Preview** in
the same dialog removes it. Any change of the active model or runtime also voids it.

Check the whole chain at any time (no hashing, nothing is run):

```bash
python -m tools.ai_assist_admin status
```

## 5. First Suggest

Select a PromptPack slot with an authored positive prompt and a target with verified compatibility, make sure no job is
running, then press **Suggest... (Preview)**, choose **Rewrite Prompt**, review the proposal and the deterministic
compatibility, and press **Accept rewrite** only if you want it. Accept edits the editing buffer only; save and Preview
as usual.

**More values for matrix slots (Suggest variety, AI-212).** With a pack whose prompt uses `[[slot]]` markers and whose
Matrix tab lists the slots, open the same dialog, type a goal in **Matrix slot variety** (for example "more variety in the
lighting and the locations") and press **Suggest variety**. Only the goal and the slot names and values are sent; no
prompt, model or stage list. Each proposed value is listed as *can add* or *rejected* with the reason (already in the slot,
comma, brackets, `<...>` token, `__` wildcard, line break, too long, empty or hidden). Select one *can add* value and press
**Add selected value**: it is appended to that slot exactly as if you had typed `,value` at the end of its Values entry in
the Matrix tab, so the pack becomes modified and unsaved. Nothing is saved, previewed, queued or generated; no slot is
created and no existing value or prompt is changed. If you edit the matrix or switch pack after the request, adding is
refused; request again. A slot whose values contain a comma or are not plain text, or whose name is shared or padded, is not
offered (the status line counts them). Whether the suggestions are any good is unverified until you try it.

## What each message means

| Where | Message or code | Meaning and next step |
|---|---|---|
| Suggest hint, `status` | needs a pinned runtime build (`missing: pinned_build`) | No build in `config/managed_ai_runtime.json`. Do step 1. |
| Suggest hint, `status` | needs an imported runtime and model (`imported_model`) | Nothing imported and activated. Do step 2. |
| Suggest hint | Preview is not enabled (`enablement`) | A verified unqualified model is installed. Do step 4. |
| Suggest hint, `NOT_INSTALLED` / `preview_not_enabled` | The enablement record is missing, malformed, or names another model or build | Enable again in step 4. |
| `EGRESS_NOT_ATTESTED` | No attestation, a pre-AI-202a one, or one that does not cover the active build and its executable (`status` shows `egress: not_covered`) | Do step 3 for the active build. |
| `INTEGRITY_FAILED` | Installed files differ from the pins | Re-import from verified files; never edit installed files. |
| `GENERATION_ACTIVE`, `YIELDED_TO_GENERATION` | A job is running, GPU quarantined, or activity unreadable | Retry when generation is idle. AI always yields. |
| `RESOURCE_INSUFFICIENT` | RAM or commit headroom below model size plus 4 GiB, or the memory guard fired | Close other programs; retry. |
| `BUSY` | Another AI request is running | Wait or cancel it. |
| Suggest variety: "changed since the request" | The pack or a matrix slot changed after the request (including your own edit) | Request again; nothing was added. |
| Suggest variety: "unfinished edit in that slot" | The slot's Values entry holds text its handler has not stored yet | Finish or undo the typing in the Matrix tab, then add again. |
| `TIMEOUT`, `CANCELLED` | Time limit or your cancel | Authored work is unchanged. |
| `REFUSED_BY_MODEL` | The model declined | Shown as a refusal; never repaired. |
| `MALFORMED`, `UNAVAILABLE` | Output failed the strict schema, or the process could not start or exited non-zero | In the review dialog press **Show runtime detail**: it shows the exit code and the end of the runtime's own error output (and, for `MALFORMED`, the start of its output). That text is raw runtime output, kept in memory only, never saved; it can contain fragments of your own prompt. Report the exit code and the error line. |
| `import-*`: `hash_mismatch`, `size_mismatch`, `unlisted_executable_content`, `pinned_file_missing` | The file is not what the manifest pins | Nothing was installed. Re-stage the right file or fix the pin by PR. |

## Known unverified points (AI-202a)

AI-202a settled the invocation from the llama.cpp source of both pinned tags (`docs/work_packages/AI-202_invocation_and_selector.md`);
no binary was run, so the first real Suggest is the check. Still unverified, and surfacing as `UNAVAILABLE` or `MALFORMED`
(they cannot widen what is allowed):

- that `llama-completion.exe` finds its `llama-completion-impl.dll` and the ggml libraries in the runtime directory;
- that stdout is exactly the generation plus the tool's own trailing `[end of text]` line (which StableNew removes);
  a banner or prompt echo makes the output `MALFORMED` by design;
- that the models follow the JSON instruction without chat markup (the prompt is read raw; the schema grammar fixes the
  structure, not the quality);
- that `b11840` loads the Qwen3.5 files and `b11960` loads LFM3.

Report the outcome code, the exit code and the error line from **Show runtime detail**, and the `status` output; do not edit
installed files or the argv to work around them.
