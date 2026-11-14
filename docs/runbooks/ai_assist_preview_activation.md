# AI Assist Preview activation (operator runbook)

Authority: `docs/Subsystems/AiAssist/AI_ASSIST.md` (owner decisions D13 to D17, 2026-11-13). This runbook takes you from
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
python -m tools.ai_assist_admin describe-runtime D:\staging\llama-bNNNN-bin-win-cpu-x64.zip --build-id bNNNN-cpu --upstream-repository https://github.com/ggml-org/llama.cpp --upstream-tag bNNNN --license-spdx MIT --executable llama-cli.exe
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

## 3. Record the firewall attestation

You create and maintain an outbound firewall restriction for the runtime directory yourself; StableNew cannot see or
verify it. Then record that you did:

```bash
python -m tools.ai_assist_admin record-attestation --statement "Windows Firewall outbound block: ManagedAi llama-cli.exe"
```

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

## What each message means

| Where | Message or code | Meaning and next step |
|---|---|---|
| Suggest hint, `status` | needs a pinned runtime build (`missing: pinned_build`) | No build in `config/managed_ai_runtime.json`. Do step 1. |
| Suggest hint, `status` | needs an imported runtime and model (`imported_model`) | Nothing imported and activated. Do step 2. |
| Suggest hint | Preview is not enabled (`enablement`) | A verified unqualified model is installed. Do step 4. |
| Suggest hint, `NOT_INSTALLED` / `preview_not_enabled` | The enablement record is missing, malformed, or names another model or build | Enable again in step 4. |
| `EGRESS_NOT_ATTESTED` | No attestation | Do step 3. |
| `INTEGRITY_FAILED` | Installed files differ from the pins | Re-import from verified files; never edit installed files. |
| `GENERATION_ACTIVE`, `YIELDED_TO_GENERATION` | A job is running, GPU quarantined, or activity unreadable | Retry when generation is idle. AI always yields. |
| `RESOURCE_INSUFFICIENT` | RAM or commit headroom below model size plus 4 GiB, or the memory guard fired | Close other programs; retry. |
| `BUSY` | Another AI request is running | Wait or cancel it. |
| `TIMEOUT`, `CANCELLED` | Time limit or your cancel | Authored work is unchanged. |
| `REFUSED_BY_MODEL` | The model declined | Shown as a refusal; never repaired. |
| `MALFORMED`, `UNAVAILABLE` | Output failed the strict schema, or the process could not start | See the known unverified points below. |
| `import-*`: `hash_mismatch`, `size_mismatch`, `unlisted_executable_content`, `pinned_file_missing` | The file is not what the manifest pins | Nothing was installed. Re-stage the right file or fix the pin by PR. |

## Known unverified points (AI-201)

The first physical activation is the package AI-201. Until it runs, these are unverified against a real pinned build and
surface as `UNAVAILABLE` or `MALFORMED` (they cannot widen what is allowed):

- the exact llama.cpp flag spellings emitted by `argv.py` (a rejected flag ends as `UNAVAILABLE`);
- whether the one-shot binary stays quiet on stdout with `--no-display-prompt` (a banner, prompt echo or `[end of text]`
  line makes the output `MALFORMED` by design);
- whether `--json-schema-file` is accepted, and how `--reasoning off` interacts with constrained decoding.

Report the refusal code and `status` output; do not edit installed files or the argv to work around them.
