# Offline visual candidate evaluation

Use an operator-owned local evaluation root with write access limited to the operator. Keep it outside Git, the configured
AI Assist root, and production checkpoint directories. Keep StableNew and generation backends closed during a supervised
evaluation. The harness checks known local runtime processes and refuses when it cannot inspect a relevant process.

## Verified assets

| Candidate ID | Upstream revision | Model and projector bytes |
|---|---|---:|
| `lfm3-vl-2b-q4_k_m-liquidai` | LiquidAI/LFM3-VL-2B-GGUF at `1add221a5ea6c047fcf1eaaf2d247939d7cf8849` | 1,478,623,840 |
| `gemma-4-12b-it-qat-q4_0-google` | google/gemma-4-12B-it-qat-q4_0-gguf at `29d097773436b69ff9feafd636ab4cf873786537` | 7,150,994,912 |

The [visual catalog](../../config/ai_visual_candidates.json) records the individual sizes, SHA-256 values, model and
projector metadata, and license text identities. The files above were staged and checked on November 14, 2026, at
`D:\StableNew-Assets\offline-ai\downloads\lfm3-vl-2b` and
`D:\StableNew-Assets\offline-ai\downloads\gemma4-12b`. The Gemma source is public and its pinned card declares
Apache-2.0. The card and canonical Apache license text are staged beside the Gemma files. The Gemma download used 7.15 GB
of the 9 GiB model/projector allowance.

Both pairs match the catalog in byte count, SHA-256, GGUF architecture, vision projector type, base model name and projection
width. The Gemma GGUFs identify `gemma4` and `gemma4uv` with projection width 3,840. LFM identifies `lfm3` and
`lfm3vl` with projection width 2,048. The exact llama.cpp source revision
[8642541](https://github.com/ggml-org/llama.cpp/tree/8642541b255bfb5dc39cd351a178be09013a55d6) implements both
model/projector paths. The matching [CPU x64 release archive](https://github.com/ggml-org/llama.cpp/releases/tag/b11960)
used the separate 24,407,745-byte runtime allowance. Its SHA-256 and all 51 loadable file hashes were verified. The
vision entry uses the same archive as the text build, with its own executable identity and install directory.

## Verify and import

Run the following in PowerShell from the PR worktree with StableNew's Python environment active. Select one pair each time.
Use an acknowledgement path unique to that candidate.

```powershell
$root = 'D:\StableNew-Assets\offline-ai\visual-evaluation'
$downloads = 'D:\StableNew-Assets\offline-ai\downloads'
$candidate = 'lfm3-vl-2b-q4_k_m-liquidai'
$staged = Join-Path $downloads 'lfm3-vl-2b'
$ack = Join-Path $staged 'license_acknowledgement.json'

python -m tools.qualification.vl220 --candidate $candidate verify-staging --staging $staged
```

For Gemma, use `gemma-4-12b-it-qat-q4_0-google` and the `gemma4-12b` staging directory. `pair_verified` confirms
the bytes and headers. An absent acknowledgement produces `import_ready: false` and exit code 1 even when verification
passes. The owner reviews the catalog-linked license text and creates the acknowledgement record with `candidate_id`,
`license_text_sha256` from the candidate's license entry, and `owner_acknowledged` set to the JSON boolean `true`.
For LFM, use the template in the staging directory as a starting point.

```powershell
python -m tools.qualification.vl220 --candidate $candidate import --staging $staged --evaluation-root $root --acknowledgement $ack
python -m tools.qualification.vl220 --candidate $candidate import-runtime --evaluation-root $root --archive (Join-Path $downloads 'llama-b11960-bin-win-cpu-x64.zip')
```

Import the runtime once for a shared evaluation root. Reuse the verified runtime installation when it already exists. Candidate import publishes the pair and its receipt together. A retry can reuse existing complete imports after verification. A failed copy cleans its own staging area.

## Firewall and attestation

After runtime import, the owner runs this outbound Block command in elevated PowerShell. Use the same root as the runtime
import. Inspect the installed hash before applying the rule.

```powershell
$exe = Join-Path $root 'runtimes\b11960-cpu-vision\llama-mtmd-cli.exe'
$expected = '5073109b15d7d19fd3cc4c23bdbdc2f3dfdae39a6410d80ea6e7b6929eb30b3a'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash -ne $expected) {
    throw 'Visual executable SHA-256 mismatch'
}
New-NetFirewallRule -DisplayName 'StableNew llama.cpp b11960 CPU vision outbound block' -Direction Outbound -Action Block -Profile Any -Program $exe
```

After setting and checking the rule, the owner records the existing version-2 attestation in the evaluation root. Reapply
and reattest the rule for the new absolute executable path if the installation moves.

```powershell
python -m tools.ai_assist_admin --root $root record-attestation --build-id b11960-cpu-vision --statement "Outbound Block rule verified for $exe"
python -m tools.qualification.vl220 --candidate $candidate status --evaluation-root $root --acknowledgement $ack
```

`launch_prerequisites_met` reflects installed file integrity, the receipt, the acknowledgement, and the operator's
attestation for the exact build and executable. StableNew does not inspect firewall policy. Each child also needs a quiet
host, RAM and commit headroom, verified images, and OS containment.

## Supervised evaluation

Use `describe` to obtain the candidate's plan digest and the fixed synthetic case and label digests. To materialize the
synthetic images, run `write-synthetic --dest <empty-folder>` and use that folder as `--assets`. The default evaluation reads
the synthetic case and label documents in memory. For existing assets, pass `--cases` and `--labels` together and point
`--assets` at the PNG or JPEG files named by asset ID. Existing assets require human labels.

The LFM3-VL-2B invocation, sampling defaults and owner plan from VL-220 still apply. Its current plan digest is
`15d7ab2ee6d5b5f21db3798dee3390ed6a8c4086dc973ce5593ee91a043db536` (run `describe` for the live value; earlier packages' digests
are listed in the image invocation contract). Follow the
[LFM staging runbook](ai_vl_candidate_staging.md) for the original LFM command. Pass `--ai-root $root` to use the isolated
runtime installed above.

For Gemma, record the plan digest printed by `describe`, the execution digest from `describe-execution`, and the canonical
case and label digests. Use `tools.qualification.vl220.contract.digest` over parsed JSON for custom case and label documents.
If the approved plan changes `--min-image-tokens` or `--max-image-tokens`, specify the same reviewed limits for
`describe-execution` and `evaluate`.

After review of the exact supervised run, set the corresponding variables and run the Gemma command from the operator shell.

```powershell
python -m tools.qualification.vl220 --candidate $candidate evaluate --evaluation-root $root --ai-root $root --assets $assetsPath --acknowledgement $ack --evidence-out $evidencePath --i-have-the-plan-digest $planSha --generation-idle --execution-sha256 $executionSha --case-sha256 $caseSha --label-sha256 $labelSha
```

The driver passes ordered images, the rendered case prompt, and the schema through private temporary files. Gemma uses
its bundled Jinja template, 180 seconds and 4,096 context tokens per case by default. Its provisional 12 GiB ceiling also
caps committed memory in the Windows job object. LFM retains the original 6 GiB evaluation ceiling and VL-220 invocation.
The evidence records a path-free argv hash, wall time, observed working set, exit code, validation code and scores.
Gemma evidence includes deterministic floors. The `dry-run` command also prints the synthetic floors.

Gemma's envelope on the reference machine (`docs/work_packages/AI-VL-241_gemma_readiness.md`): about 7.9 GiB private memory per child (planned upper bound 9.0 GiB), a working set of 8-14 GiB, and an estimated 25-75 s per case. Admission requires 11.0 GiB available RAM and 12.0 GiB commit headroom, so close Forge and the application first; a short reading is a `not_run` refusal, not a failure. The default per-case kill is 300 s (`--timeout-seconds` changes it and the execution digest). Image tokens are `--min-image-tokens 64 --max-image-tokens 256` (one token is a 48 x 48 pixel cell for the `gemma4uv` projector; the model's own range is 70-1120). `evidence.cleanup_complete: false` means a work directory under the evaluation root could not be removed: delete `_work` yourself before another run.

Runtime compatibility is based on pinned source and artifact inspection. Tests use fake children. Model loading, prompt
rendering, constrained decoding, speed, memory use and output quality require supervised evidence. Both candidates remain
unqualified and operator-only.
