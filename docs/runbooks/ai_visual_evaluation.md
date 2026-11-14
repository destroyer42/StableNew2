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

Import the runtime once for a shared evaluation root. Candidate import publishes the pair and its receipt together. Retry can
reuse existing complete imports after verification. A failed copy cleans its own staging area.

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

`describe-execution` prints the execution digest and the exact runtime identities and limits it binds. `describe`
prints the evaluation plan and its synthetic case and label digests. Use `write-synthetic --dest <empty-folder>` to
materialize the fixed synthetic set. Existing assets require a frozen cases document, a separate human-labelled document,
and PNGs or JPEGs named by asset ID (suffix `.png` or `.jpg`) beside the cases file.

With the exact supervised run authorized, pass the reviewed digests to the operator command. Digest case and label documents
with `tools.qualification.vl220.contract.digest` over parsed JSON, the same canonical encoding used for the synthetic set.

```powershell
python -m tools.qualification.vl220 --candidate $candidate evaluate --evaluation-root $root --acknowledgement $ack --cases $casesPath --labels $labelsPath --execution-sha256 $executionSha --case-sha256 $caseSha --label-sha256 $labelSha
```

The driver passes ordered images and a generated case prompt and schema through private temporary files. It uses the same
closed CPU-only profile for both candidates, with per-case 180-second and 4,096-context-token bounds. LFM has the original
6 GiB working-set ceiling. Gemma uses a provisional 12 GiB ceiling because its artifacts alone exceed 6 GiB. The same figures
cap committed memory in the Windows job object. The adapter reports observed working set, wall time, exit code, validation
code, argv hash, scores and deterministic floors. The report excludes paths, image bytes, prompt text, output text and stderr.

Runtime compatibility is based on pinned source and artifact inspection. Deterministic tests inject a fake bounded child.
Actual loading, prompt rendering, constrained decoding, speed, memory use and output quality require separate supervised
evidence. These candidates carry no qualification or production eligibility.
