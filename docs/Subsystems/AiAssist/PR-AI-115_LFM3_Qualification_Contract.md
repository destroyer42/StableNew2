# AI-QUAL-115: LFM3-1.7B qualification contract

Status: **frozen proposal, unapproved, nothing executed.** LFM3-1.7B is **NOT TESTED**; physical qualification is **BLOCKED**.
No artifact was downloaded, extracted or executed, no model was loaded, no firewall, registry, manifest, runtime or GPU state
changed, and no production flag moved (`qualified` stays `false`, Suggest stays disabled).

The contract is code, not prose: `tools/qualification/ai111/lfm3_contract.py` (`stablenew.ai115.lfm3.v1`). Regenerate it with
`python -m tools.qualification.ai111.lfm3_contract --out <new empty directory>`. The Qwen corpus, plans and digests are untouched
and re-asserted by the tests (section 7). LFM3 candidates live only in the contract, never in `config/`.

## 1. Reconciled status (observed 2026-10-29, base `origin/main` 7ccb9a8b)

Source capability, owner authorization and measured host evidence are different things; only the third is evidence of a run.

| Item | Source capability | Authorization | Measured host evidence |
|---|---|---|---|
| D12a (extract CPU archive, run `--version`/`--help`) | `d12a.py` exists and is tested; covers `llama-cli.exe` and `llama-completion.exe` of the **b11840** archive only | **Not granted** | **None.** Never run. The b11840 archive is staged and size/SHA-256 verified (2026-10-23), not extracted |
| D12b (model import and CPU inference) | `physical.py` exists and is tested with fakes | **Not granted** | **None** |
| Protected interpreter setup | `capture_control.py` refuses an unprotected runtime | Owner action, not done | `C:\Program Files` holds no Python; `%ProgramData%\StableNewCap` is absent; only per-user Pythons (3.10, 3.11, 3.14) exist |
| Analyzer v3 | On `main` (`8787c286`; `73ef73c1` is an ancestor of `origin/main`) | n/a | The only capture, `ai114e-canary-1` (id `20261025T234245Z-fd783cd8`), was re-analysed: v1 INCONCLUSIVE, v2 PASS, v3 PASS |
| Most recent ETW canary | `capture_session canary` | n/a | `ai114e-canary-1`, 2026-10-25, started from an **unprotected** interpreter. Its proof cannot satisfy the runbook (same tool hashes, a different capture, under 24 h). **No `ai114e-canary-2` exists** on this host. `C:\Users\rob\qual\ai114-canary-2` is the older 113B per-request-provider evidence |
| Active trace sessions | n/a | n/a | `logman query -ets` lists no `StableNewCap-` session |

Result: nothing that runs a model is authorized or possible today, for Qwen or LFM3.

## 2. Findings and blockers

**Blocking compatibility facts (physical qualification cannot start until each is cleared):**

1. **The accepted runtime cannot load LFM3.** llama.cpp `b11840` (the pinned Qwen runtime) has no `lfm3` architecture in `src/llama-arch.cpp` (only the older LFM2 family).
   The earliest tag with the architecture is `b11938`; the publisher states `b11960` as the minimum.
2. **The harness is single-runtime, single-sampling.** `physical.py` takes its runtime from `plan["runtime_intent"]` (b11840),
   launchable-member hashes from the b11840 table, one `Sampling(**plan["sampling"])` for every arm and the registry from
   `config/`; the execution manifest stamps the **Qwen plan digest**, so an LFM3 session would carry a misleading identity.
   Adapting it is a security-sensitive harness change and needs the member hashes first (item 3). Not done here: follow-up
   package, see section 9.
3. **b11960 member hashes are unknown.** Only the archive hash is public (GitHub's asset `digest`, not a signature). The per-member
   SHA-256 needed for `LAUNCHABLE_MEMBERS` requires the archive, so S0 (download) must precede them.
4. **Licence is not SPDX and has a revenue threshold** (section 3). It needs the owner's recorded acknowledgement (S1).
5. Protected system Python, protected `capture_control.py` copy, a current canary PASS and the firewall attestation are absent.

**Resolved in scope:** the closed argument vocabulary lacks two flags the vendor sampling needs (`--min-p`, `--repeat-penalty`).
They exist in `common/arg.cpp` at b11938 and b11960 (static source evidence). The contract owns a closed superset;
the only production change is a default-preserving `allowed` parameter on `assert_argv_allowed` (Qwen argv is asserted
byte-identical). D12a for b11960 must still show both flags in the real `--help`.

**Not blockers, but unknown (measured by the contract rather than assumed):** whether a template-less raw frame is a fair way to
drive a chat-tuned model; whether the grammar constrains LFM3 as it does Qwen; how the repetition penalty interacts with
protected-token copying.

## 3. Provenance (public metadata only)

| Item | Value |
|---|---|
| Publisher | `LiquidAI/LFM3-1.7B` at `ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7` (model card: 1.7B, 256K context, hybrid conv/attention, thinking on by default) |
| Packager | `LiquidAI/LFM3-1.7B-GGUF` at `bad5729bba61d076fff20d2548e62526665af215` (same organisation as the publisher; first-party) |
| Converter | not stated in repository metadata |
| `LFM3-1.7B-Q4_K_M.gguf` | 1,099,627,808 bytes, `3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4` |
| `LFM3-1.7B-Q8_0.gguf` | 1,846,238,496 bytes, `8f6b24182258205e9e01e21f1f24a1f208c1e8115578825d202ce39976af20b6` |
| Source of hashes | Hugging Face LFS object ids (SHA-256) and sizes from the tree API at the pinned packager commit; **not yet verified against local bytes** |
| Licence | LFM Open License v1.0 (`LicenseRef-LFM-Open-License-1.0`), `LICENSE` 10,574 bytes, SHA-256 `4d28ca14dedc0b3d0fcc2b3339f0e79931faa33874f3d24f522183a8fc70068c`, identical in both repositories |
| Licence terms that matter | Commercial Use by a Legal Entity with annual revenue of USD 10,000,000 or more is not licensed (section 5); non-profit research exempt; redistribution must carry the licence; terminates on non-compliance. StableNew ships no weights |
| Sampling (vendor) | temperature 0.1, top_k 50, repetition penalty 1.1 (model card and `generation_config.json`) |

| llama.cpp tag | Commit | Asset | Bytes | SHA-256 (GitHub asset digest) | LFM3 |
|---|---|---|---:|---|---|
| **b11960** (selected) | `8642541b255bfb5dc39cd351a178be09013a55d6` | `llama-b11960-bin-win-cpu-x64.zip` | 24,407,745 | `73f962f82850d244db47eaacb9d913637027b82399124324298576d58c5f4287` | publisher-stated minimum |
| b11938 (evaluated, not selected) | `19cce6919992fdffd92e0ac152caaf1e2b8f254e` | `llama-b11938-bin-win-cpu-x64.zip` | 24,260,998 | `9e2fc62604446d86809ca09094d3c7a7329b723bda636e4bbd23c3ce62cb77dc` | arch commit (#31252), below the stated minimum |
| b11840 (Qwen runtime) | `36e36e63a54fc8f85b95e9c499a022b597e478dd` | `llama-b11840-bin-win-cpu-x64.zip` | 24,156,518 | `f805935d...da034` | none |

The three releases inspected are marked pre-release upstream (as every build this project has pinned); the llama.cpp licence is MIT. b11938 was not selected because nobody can show that the shipped GGUFs
load on a build older than the publisher's own floor; it stays a fallback needing its own decision.

## 4. The frozen contract

Contract SHA-256 (the digest every approval must quote): `8119804fa062308a11c5bf55c2b9812bc20dff04016eab50b64095781268fad5`.
Stage A case-id list SHA-256: `d0bbf7feabc5bd533130d2ab044cbe351218a47b2a0c7dd7edbbc5eb8e97d030` (30 cases of the final corpus, seed 11502).

- **Arms** (all on b11960, so the runtime is not a confounder): `lfm3-1.7b-q4_k_m@lfm3_vendor` vs matched
  `qwen3.5-4b-q4_k_m@qwen_frozen`; `lfm3-1.7b-q8_0@lfm3_vendor` vs `qwen3.5-4b-q8_0@qwen_frozen`; Stage A only, the
  pre-registered sensitivity arm `lfm3-1.7b-q4_k_m@lfm3_no_repeat` (repeat penalty 1.0); `B1_engine` as the preference reference.
  Qwen keeps its own frozen sampling (sampling is a model attribute, not a controlled variable).
- **Sampling:** vendor profile pins `top_p 1.0` and `min_p 0.0` explicitly because llama.cpp's defaults (0.95, 0.05) would otherwise
  apply silently; `presence_penalty 0.0`; seed 321.
- **Structured output:** `ai_assist.frame/1` unchanged, raw frame through `-f` with `--no-conversation` (no chat template, as for
  Qwen), `--json-schema-file` grammar. `--reasoning off` is passed but is inert for a raw frame; the grammar is what excludes
  thinking text. Stdout must be exactly one JSON object; anything else, a `<think>` block included, is `MALFORMED` and never repaired.
  A report-only ungrammared probe (10 cases, Stage A) cannot influence a gate.
- **Limits:** identical to the frozen plan (context 4096, 768 new tokens, 8 threads, 90 s, 256 KiB stdout).
- **Closed argv:** the production flags plus `--min-p` and `--repeat-penalty`; every forbidden flag stays forbidden.

## 5. Stage A (compatibility, integrity, monitoring smoke; never a qualification)

**Admission:** S0-S3 approvals each naming the contract digest and artifact hashes; licence acknowledged; D12a for the b11960
members PASS with launched-member hashes equal to the recorded ones; protected capture runtime and a live canary PASS from a different
capture under 24 h with unchanged tool hashes; one 1024 MB capture per arm with a start and end canary and analysis v3 PASS with zero
lost events; quiet host; per-arm memory preflight; firewall attestation recorded in the evidence-local root.

**Stop immediately on:** any hash mismatch, unpinned loadable file or identity change between arm start and end; any ownership
violation, connection attempt (loopback included), write outside the write root or read outside the read roots; an owned tree not
proven gone after a request, or a trace session left running; GPU memory attributable to the owned tree or global VRAM growth above
the probe limit; three consecutive infrastructure failures, a host-memory abort or the capture deadline; capture analysis
INCONCLUSIVE or FAIL (a retrospective violation invalidates the arm).

**Recommendation:** `stage_a_report.judge_arm` unchanged. REJECT on a hard gate, a security FAIL or a model that never ran;
ADVANCE only when compatibility, integrity and security all PASS and no measured threshold is missed; otherwise INCONCLUSIVE.
Stage A can never produce GO. **Sensitivity rule (decided now):** the no-repeat profile replaces the vendor profile for Stage B only
if the vendor arm records strictly more accepted protected-token changes on the Stage A slice and the no-repeat arm records zero.

## 6. Stage B (selection evidence) and monitoring

**GO** needs, per arm: `evaluate_final_gates` over all 460 cases of the frozen corpus (`a89297be...774d5`) with zero hard-gate
violations; teardown verified, zero egress, no ownership violation and analysis v3 PASS for every capture; at least 100 decisive blind
judgments versus `B1_engine` with the lower 95% bound above 0.5; every record carrying the contract digest, the arm's sampling
profile and the runtime asset hash (`record_problems`). **NO-GO:** any hard gate violated or measured threshold missed on complete
evidence. **INCONCLUSIVE:** incomplete cases, missing capture analysis, fewer than 100 decisive judgments or any abort.
LFM3 vs its matched Qwen comparator is a paired blind preference reported separately and never a gate; LFM3 is called preferred only
with a lower 95% bound above 0.5 over at least 100 decisive judgments. Stage B is never pooled with Stage A, a subset, or a hermetic run.

| Concern | Rule |
|---|---|
| ETW read roots | `<evidence>/ai-root` and `<SystemRoot>`; any extra root must be named in the owner approval and recorded |
| ETW write roots | `<evidence>/ai-root/work` only |
| Zero egress | zero observed connections, loopback included; scrubbed child environment; `--offline`; the preventive barrier is the operator-attested firewall restriction |
| Teardown | process record complete and `active_after_teardown == 0` after every request; no `llama-*.exe` survivor and no `StableNewCap` session at session end |
| VRAM | `-ngl 0`, `CUDA_VISIBLE_DEVICES=-1`, no `ggml-cuda/vulkan/hip/sycl/opencl` member; owned tree holds no GPU memory; global growth under 2048 MiB (existing probe) |
| Memory | admission needs model GiB + 4 (RAM and commit); abort below 0.25 GiB RAM or 1 GiB commit headroom for two samples; tree private cap 1.5 x model GiB + 2; peak private/working set and host minima recorded per arm |
| Latency | median at most 20 s; cold first, warm median, p95, max and output characters per second recorded. Prefill/decode rates are **not** measurable under the closed vocabulary |

## 7. Approval boundary

Five independent steps, none implied by another: `S0_download` (the three named files only), `S1_license` (acknowledgement and the
Threshold position), `S2_d12a_b11960`, `S3_stage_a`, `S4_stage_b`. Each approval must name its step, quote the contract digest and
carry the SHA-256 of every artifact it covers (`approval_problems`); that binds identity, not the owner's intent. Promotion
(registry/manifest `qualified=true`, enabling Suggest) is outside this contract. `authorization` is all `false` in the frozen document.

## 8. Critical review

Review of lifecycle escapes, licensing, corpus drift, wrong executable, malformed output and misleading PASS (findings and
dispositions are kept current by the test file `tests/tools/test_ai115_lfm3_contract.py`):

| Risk | Finding | Disposition |
|---|---|---|
| Lifecycle escape | No new process path is added; every arm still runs through `run_bounded`'s job object and the owned-session monitor | unchanged; the contract only adds stop rules |
| Licence | Non-SPDX, revenue-thresholded, termination clause; the registry accepts any free-text `license_spdx` | acknowledgement is a readiness blocker; promotion must add a licence check |
| Corpus drift | Final plan and corpus reached only through code; Qwen digests asserted in tests; contract digest in every record | enforced by `validate_contract`, `record_problems` |
| Wrong executable | `LAUNCHABLE_MEMBERS` is b11840-only; with a different archive the harness refuses, and with no member named it would not re-check the member hash | `members_hashed` false blocks S3; harness delta in section 9 |
| Malformed output | `<think>` or prose is `MALFORMED`; grammar excludes thinking; repetition penalty may disturb token copying | pre-registered sensitivity arm and rule |
| Misleading PASS | A 30-case slice cannot meet coverage; the execution manifest stamps the Qwen plan digest; sampling or runtime could silently differ | Stage A can never be GO; `record_problems` rejects mismatched digest, sampling or runtime hash; harness delta |

## 9. Next explicit owner decisions

1. Authorize **S0** (download the two LFM3 GGUFs and the b11960 CPU archive, 2,970,274,049 bytes in total) and **S1** (licence position). Or decline LFM3.
2. A follow-up package (proposed AI-QUAL-115B) to make `physical.py`/`d12a.py` contract-driven: per-arm runtime, sampling and registry,
   member hashes for b11960, the contract digest in the execution manifest, and `record_problems` enforcement. It needs the S0 hashes.
3. The operator-side prerequisites that block Qwen as well: system-wide Python, protected `capture_control.py` copy, a fresh canary.

No physical work, promotion or merge is requested or implied.
