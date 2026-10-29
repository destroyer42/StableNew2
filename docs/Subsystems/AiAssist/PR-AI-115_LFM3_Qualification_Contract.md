# AI-QUAL-115: LFM3-1.7B qualification contract

Status: **frozen proposal, unapproved, nothing executed.** LFM3-1.7B is **NOT TESTED**; physical qualification is **BLOCKED**.
No artifact was downloaded, extracted or executed, no model was loaded, no firewall, registry, manifest, runtime or GPU state
changed, and no production flag moved (`qualified` stays `false`, Suggest stays disabled).

**Two contracts, kept apart.** The Qwen contract is the frozen screening plan, final plan and 460-case corpus
(`qwen_preserved`, pinned to llama.cpp b11840 and the Qwen sampling) and is neither edited nor re-pinned here. This LFM3
contract is separate: LFM3 candidates and a runtime floor of **b11960 (or a later build)**. A later build is acceptable only as
its own exact, measured candidate in a new frozen contract version with fresh approvals; b11960 is the pinned selection. Every
arm this contract defines, the matched Qwen comparators included, runs on the LFM3 runtime so the runtime is not a confounder.

**Owner authorization (2026-10-29):** S0 (download) and S1 (licence) were granted in chat; S2 to S4 were not. S0 was executed and
verified (section 3); the S1 acknowledgement and Threshold position are recorded in the evidence directory below, not in the
frozen document, which can never carry a grant.

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
| LFM3 S0 download | `lfm3_contract.py` pins URLs, sizes and hashes | **Granted 2026-10-29** | **Done and verified:** both GGUFs and the b11960 archive match their pinned size and SHA-256; GGUF magic and version 3 read; the archive was hashed in memory, **not extracted or executed** |
| LFM3 S1 licence | recorded in the contract | **Granted 2026-10-29** | Acknowledged by the owner (personal use, below the Threshold); record in the evidence directory |

Result: nothing that runs a model is authorized or possible today, for Qwen or LFM3.

## 2. Findings and blockers

The contract lists them in `KNOWN_BLOCKERS`; `readiness_blockers(stage, evidence)` derives what still blocks a stage from
evidence objects (approval texts, licence record, runtime entry, `--help` report) and counts operator attestations only when
they are exactly `True`.

**Blocking compatibility facts (physical qualification cannot start until each is cleared):**

1. **The accepted runtime cannot load LFM3.** llama.cpp `b11840` (the pinned Qwen runtime) has no `lfm3` architecture in `src/llama-arch.cpp` (only the older LFM2 family).
   The earliest tag with the architecture is `b11938`; the publisher states `b11960` as the minimum.
2. **The harness is single-runtime, single-sampling.** `physical.py` takes its runtime from `plan["runtime_intent"]` (b11840),
   launchable-member hashes from the b11840 table, one `Sampling(**plan["sampling"])` for every arm and the registry from
   `config/`; the execution manifest stamps the **Qwen plan digest**, so an LFM3 session would carry a misleading identity.
   Adapting it is a security-sensitive harness change and needs the member hashes first (item 3). Follow-up package, section 9.
3. **`stage_a_report` and `d12a` defaults are Qwen-pinned.** Both default to the Qwen screening plan and the b11840 archive, so
   an LFM3 run through them would be judged and attributed against the wrong plan.
4. **Member hashes are now measured, but the harness can still skip them.** After S0, all 51 loadable members of the b11960
   archive were hashed in memory and recorded in the contract (`files`; `members` is the launchable subset: `llama-cli.exe`
   `02c8fcdb...932de0`, `llama-completion.exe` `2b4759ec...b35090`). The existing `derive_runtime_build` without a named member
   still does not pin the member hash, and `LAUNCHABLE_MEMBERS` is b11840-only (item 2).
5. **Stage B does not fit one capture.** 460 requests at the allowed 20 s median exceed one 1024 MB capture. The split across
   captures, which request is cold, and how records are merged are undefined; the S4 approval must state them, and no harness
   supports it yet.
6. **Infrastructure abort counts four of the ten infrastructure outcome codes** (recorded, not changed).
7. **Licence is not SPDX and has a revenue threshold** (section 3). The owner acknowledged it and stated a personal-use
   Threshold position (S1); that record lives in the evidence directory and is checked by `license_problems(require_acknowledged=True)`.
8. **The b11960 archive ships a network backend.** It holds `ggml-rpc.dll` and `ggml-rpc-server.exe`, and the backend scan may load
   a `ggml-*.dll` from the runtime directory. `--rpc` stays forbidden, the child environment is scrubbed and the server is never
   launched, but D12a and every capture must show zero connections (loopback included); this is a monitoring rule, not an assumption.
   The archive also uses `*-impl.dll` launcher pairs (for example `llama-completion.exe` loads `llama-completion-impl.dll`), so
   pinning only the executable would be insufficient: the full `files` map is the pin.
9. Protected system Python, protected `capture_control.py` copy, a current canary PASS, the firewall attestation and every owner approval are absent.

**Resolved in scope:** the closed argument vocabulary lacks two flags the vendor sampling needs (`--min-p`, `--repeat-penalty`).
They exist in `common/arg.cpp` at b11938 and b11960 (static source evidence). The contract owns a closed superset;
the only production change is a default-preserving `allowed` parameter on `assert_argv_allowed` (Qwen argv is asserted
byte-identical). D12a for b11960 must still show both flags in the real `--help` (`help_flag_report`: a truncated or empty help
is INCONCLUSIVE, a missing flag FAIL).

**Not blockers, but unknown (measured by the contract rather than assumed):** whether a template-less raw frame suits a chat-tuned
model (both LFM3 and the matched Qwen arm receive it, so the comparison shows relative robustness and cannot isolate the template
effect); whether the grammar constrains LFM3 as it does Qwen; how the repetition penalty interacts with protected-token copying;
llama.cpp defaults outside the closed vocabulary (for example the repetition window) are not pinned.

## 3. Provenance (public metadata only)

| Item | Value |
|---|---|
| Publisher | `LiquidAI/LFM3-1.7B` at `ac2586a34f1a1c03329dbdcdefabd8b6478ddaa7` (model card: 1.7B, 256K context, hybrid conv/attention, thinking on by default) |
| Packager | `LiquidAI/LFM3-1.7B-GGUF` at `bad5729bba61d076fff20d2548e62526665af215` (same organisation as the publisher; first-party) |
| Converter | not stated in repository metadata |
| `LFM3-1.7B-Q4_K_M.gguf` | 1,099,627,808 bytes, `3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4` |
| `LFM3-1.7B-Q8_0.gguf` | 1,846,238,496 bytes, `8f6b24182258205e9e01e21f1f24a1f208c1e8115578825d202ce39976af20b6` |
| Source of hashes | Hugging Face LFS object ids (SHA-256) and sizes from the tree API at the pinned packager commit; **verified against the local downloaded bytes on 2026-10-29: exact match** |
| Evidence (outside the repo) | `C:\Users\rob\qual\ai115-s0-evidence\`: `downloads/` (the three files, 2,970,274,049 bytes in total), `s0_verification.json`, `s0_runtime_files.json`, `s1_license_acknowledgement.json`, `owner_authorization.md` |
| Licence | LFM Open License v1.0 (`LicenseRef-LFM-Open-License-1.0`), `LICENSE` 10,574 bytes, SHA-256 `4d28ca14dedc0b3d0fcc2b3339f0e79931faa33874f3d24f522183a8fc70068c`, identical in both repositories |
| Sampling (vendor) | temperature 0.1, top_k 50, repetition penalty 1.1 (model card and `generation_config.json`) |

Licence terms that bind the owner (recorded in the contract as `clauses_that_bind_the_owner`):

- Commercial Use of the Work by a Legal Entity above the Threshold (USD 10,000,000 annual revenue) is not licensed (section 5).
  The text is internally inconsistent: Section 1 defines the Threshold as revenue of that amount "or more", Section 5(b) says
  "exceeds"; the stricter reading (at or above) is assumed. A Qualified Non-Profit is exempt for non-commercial or research use.
- "Legal Entity" aggregates the acting entity with everything that controls it, it controls or shares common control with (Section 1).
- Commercial Use includes any use for **indirect** commercial advantage (Section 1).
- Redistribution must carry the licence and notices of modification (Section 4); patent licences end if You sue over the Work (Section 3).
- The licence terminates automatically on non-compliance and use must cease with every copy deleted (Section 11).

StableNew ships no weights. The owner's S1 acknowledgement must state a position on the Threshold; an empty one blocks. Recorded
position: personal, non-commercial use by an individual, below the Threshold under either reading.

| llama.cpp tag | Commit | Asset | Bytes | SHA-256 (GitHub asset digest) | LFM3 |
|---|---|---|---:|---|---|
| **b11960** (selected) | `8642541b255bfb5dc39cd351a178be09013a55d6` | `llama-b11960-bin-win-cpu-x64.zip` | 24,407,745 | `73f962f82850d244db47eaacb9d913637027b82399124324298576d58c5f4287` | publisher-stated minimum |
| b11938 (evaluated, not selected) | `19cce6919992fdffd92e0ac152caaf1e2b8f254e` | `llama-b11938-bin-win-cpu-x64.zip` | 24,260,998 | `9e2fc62604446d86809ca09094d3c7a7329b723bda636e4bbd23c3ce62cb77dc` | arch commit (#31252), below the stated minimum |
| b11840 (Qwen runtime) | `36e36e63a54fc8f85b95e9c499a022b597e478dd` | `llama-b11840-bin-win-cpu-x64.zip` | 24,156,518 | `f805935d...da034` | none |

The three releases inspected are marked pre-release upstream (as every build this project has pinned); the llama.cpp licence is MIT.
b11938 was not selected because nobody can show that the shipped GGUFs load on a build older than the publisher's own floor; it
stays a fallback needing its own decision. Each runtime candidate carries a `files` map (every loadable member to SHA-256) and a
`members` map (the launchable subset). For b11960 both are measured and pinned (an entry that differs is refused); b11938 was never
downloaded and stays empty. A launched member must be one of the recorded hashes.

## 4. The frozen contract

Contract SHA-256 (the digest every approval must quote): `41e65d6769cd4090dc0e8f978014c97e82fd23c3351261f3ff276efd8a129f60`.
It is pinned in code as `FROZEN_CONTRACT_SHA256`; `validate_contract` refuses any document that differs, so changing any value
needs a deliberate second edit and fresh approvals.
Stage A case-id list SHA-256: `d0bbf7feabc5bd533130d2ab044cbe351218a47b2a0c7dd7edbbc5eb8e97d030` (30 cases of the final corpus, seed 11502).

- **Arms** (all on b11960, so the runtime is not a confounder): `lfm3-1.7b-q4_k_m@lfm3_vendor` vs matched
  `qwen3.5-4b-q4_k_m@qwen_frozen`; `lfm3-1.7b-q8_0@lfm3_vendor` vs `qwen3.5-4b-q8_0@qwen_frozen`; Stage A only, the
  pre-registered sensitivity arm `lfm3-1.7b-q4_k_m@lfm3_no_repeat` (repeat penalty 1.0); `B1_engine` as the preference reference.
  Qwen keeps its own frozen sampling (sampling is a model attribute, not a controlled variable).
- **Sampling:** vendor profile pins `top_p 1.0` and `min_p 0.0` explicitly because llama.cpp's defaults (0.95, 0.05) would otherwise
  apply silently; `presence_penalty 0.0`; seed 321.
- **Structured output:** `ai_assist.frame/1` unchanged, raw frame through `-f` with `--no-conversation` (no chat template, as for
  Qwen), `--json-schema-file` grammar. `--reasoning off` is passed but is inert for a raw frame; the grammar is what excludes
  thinking text. `validate_output` accepts exactly one JSON object; other text, a `<think>` block included, is `MALFORMED`
  (`not_json`) and never repaired, except that text opening like a refusal is classed `REFUSED_BY_MODEL` by the existing rule.
  An ungrammared probe is not part of this contract.
- **Limits:** identical to the frozen plan (context 4096, 768 new tokens, 8 threads, 90 s, 256 KiB stdout).
- **Closed argv:** the production flags plus `--min-p` and `--repeat-penalty`; every forbidden flag stays forbidden.

## 5. Stage A (compatibility, integrity, monitoring smoke; never a qualification)

**Admission:** S0-S3 approvals, each quoting the contract digest and its artifact hashes (the Qwen comparators' included), and the
licence acknowledgement with the owner's Threshold position; D12a for the b11960 members PASS with launched-member hashes equal to the
recorded ones; protected capture runtime and a live canary PASS from a different capture under 24 h with unchanged tool hashes;
one 1024 MB capture per arm with a start and end canary and analysis v3 PASS with zero lost events; quiet host; per-arm memory
preflight; firewall attestation recorded in the evidence-local root; the previous capture STOPPED and VERIFIED and no
`StableNewCap` trace session listed before each arm's capture starts.

**Stop criteria**, split by what can actually act on them:

*Real time (the harness stops the arm or session):* owned tree not proven gone after a request; a request hitting its timeout,
output cap or memory cap (the runner kills the whole tree); identity changed since the arm preconditions or a loadable file beyond
the pinned set; three consecutive TIMEOUT, UNAVAILABLE, RESOURCE_INSUFFICIENT or YIELDED_TO_GENERATION outcomes; host-memory abort
(checked between requests) or the capture deadline; global VRAM growth above the probe limit or the GPU unreadable (checked before each arm).

*Retrospective (found only in the stopped capture; invalidates the arm, stops nothing):* any connection attempt (loopback included),
write outside the write root or read outside the read roots; capture analysis INCONCLUSIVE or FAIL, or a trace session left running.
The independent barrier against egress is the operator-attested firewall restriction.

**Recommendation:** `stage_a_report.judge_arm` unchanged. REJECT on a hard gate, a security FAIL or a model that never ran;
ADVANCE only when compatibility, integrity and security all PASS and no measured threshold is missed; otherwise INCONCLUSIVE.
Stage A can never produce GO.

**Sensitivity rule (decided now):** for the Q4_K_M model only, the no-repeat profile replaces the vendor profile for Stage B only if
the vendor arm records strictly more `MALFORMED` outcomes with reason `protected_tokens_changed` on the Stage A slice and the no-repeat
arm records zero. (The validator turns a protected-token change into `MALFORMED`, so the accepted-change count is structurally zero
and cannot decide.) The Q8_0 arm uses the profile chosen for Q4_K_M. Otherwise the vendor profile stands. Not tuned afterwards.

## 6. Stage B (selection evidence) and monitoring

**GO** needs, per arm: `evaluate_final_gates` over all 460 cases of the frozen corpus (`a89297be...774d5`) with zero hard-gate
violations and the coverage minimums met; teardown verified, zero egress, no ownership violation and analysis v3 PASS for every
capture; at least 100 decisive blind judgments versus `B1_engine` with the lower 95% bound above 0.5; every record attributable
to the contract digest, the arm's model, sampling profile, runtime asset and a recorded launched-member hash, from a host (not
hermetic or cooperative) monitor, once per case (`record_problems`). `stage_b_verdict` wraps all of that: any missing proof is
INCONCLUSIVE and GO only comes from `evaluate_final_gates`. **NO-GO:** any hard gate violated or measured threshold missed on
complete evidence. **INCONCLUSIVE:** incomplete cases, missing capture analysis, fewer than 100 decisive judgments or any abort.
LFM3 vs its matched Qwen comparator is a paired blind preference reported separately and never a gate; LFM3 is called preferred only
with a lower 95% bound above 0.5 over at least 100 decisive judgments. Stage B is never pooled with Stage A, a subset, or a hermetic run.

The capture split for Stage B is undefined (section 2, item 5); until a harness supports it Stage B cannot run.

| Concern | Rule |
|---|---|
| ETW read roots | `<evidence>/ai-root` and `<SystemRoot>`; any extra root must be named in the owner approval and recorded |
| ETW write roots | `<evidence>/ai-root/work` only |
| Zero egress | zero observed connections, loopback included; scrubbed child environment; `--offline`; the preventive barrier is the operator-attested firewall restriction |
| Teardown | process record complete and `active_after_teardown == 0` after every request (real time, from the job object); no `llama-*.exe` survivor at session end (harness); trace sessions stopped and proved gone between arms by the operator, because the standard-user harness can neither stop nor prove an elevated session |
| VRAM | `-ngl 0`, `CUDA_VISIBLE_DEVICES=-1`, no `ggml-cuda/vulkan/hip/sycl/opencl` member. No per-process GPU attribution exists in the repository; the only control is the existing nvidia-smi probe (global growth under 2048 MiB since its first reading, read before each arm; unreadable means stop) |
| Memory | admission needs model GiB + 4 (RAM and commit); abort below 0.25 GiB RAM or 1 GiB commit headroom for two samples; tree private cap 1.5 x model GiB + 2; peak private/working set and host minima recorded per arm |
| Latency | median at most 20 s; cold first, warm median, p95, max and output characters per second recorded. Prefill/decode rates are **not** measurable under the closed vocabulary |

## 7. Approval boundary

Five independent steps: `S0_download` (the three named files only), `S1_license` (acknowledgement and the Threshold position),
`S2_d12a_b11960`, `S3_stage_a`, `S4_stage_b`. Each approval must name its step, quote the contract digest and carry the SHA-256 of
every artifact it covers (`approval_problems`); `S3`/`S4` also cover the two Qwen comparator models they would execute. Each step
declares its prerequisites, which `readiness_blockers` checks (a later stage needs every earlier approval, not just its own). That
binds identity, not the owner's intent. Promotion (registry/manifest `qualified=true`, enabling Suggest) is outside this contract.
`authorization` is all `false` in the frozen document and a document carrying a granted authorization is refused: the S0 and S1
grants of 2026-10-29 are recorded as evidence bound to the previous digest (`b06fe2d7...fe706b`, which differed only by the measured
member and file maps, the runtime-floor and separation fields, the RPC monitoring rule and two known-blocker entries). Approvals for S2 onwards must quote the digest above.

## 8. Critical review

An independent review of lifecycle escapes, licensing, corpus drift, wrong executable, malformed output and misleading PASS found ten
defects in the first draft of the contract; all were repaired before this version and are pinned by the tests in
`tests/tools/test_ai115_lfm3_contract.py`:

| Risk | Finding | Disposition |
|---|---|---|
| Frozen but editable | `validate_contract` did not compare against any anchor, so editing a threshold left the contract "valid" | `FROZEN_CONTRACT_SHA256` anchor; a tamper table in the tests |
| Wrong executable | A `members_hashed` boolean could be set without any hash; a launched member was not tied to a record | `members` map of name to SHA-256; `record_problems` requires the launched-member hash to be a recorded one |
| Misleading PASS | Readiness took self-asserted booleans | `readiness_blockers` judges approvals, licence, runtime entry and help report from evidence objects; the rest count only as exactly `True` |
| Misleading PASS | `record_problems` did not bind the model file, member or monitor kind, or completeness | it checks contract, arm, sampling, runtime asset, model SHA-256, member, `monitor_kind == host`, duplicates and the case list |
| Stage B GO | GO was not computable from the contract | `stage_b_verdict` returns INCONCLUSIVE on any missing proof and defers GO to `evaluate_final_gates` |
| Corpus drift | Qwen digests asserted from the module's own copy | independent literal copies in the tests; the real plan, final plan and corpus are recomputed |
| Malformed output | The sensitivity rule keyed on a count that is structurally zero | rule re-based on `MALFORMED`/`protected_tokens_changed`; validator behaviour pinned by tests that call the real `validate_output` |
| Licence | Acknowledgement alone did not engage the Threshold; ambiguity and affiliate/indirect clauses were unrecorded | owner Threshold position required; clauses recorded; ambiguity stated |
| Lifecycle / monitoring | Stop criteria mixed real-time and retrospective, claimed per-process GPU memory and an operator capture check the harness cannot make | stop criteria split; VRAM rule restated to the real probe; capture-state gate added between arms |
| Loadable-file pinning | The archive has `*-impl.dll` launcher pairs and an RPC backend; pinning two executables would leave the loaded code unpinned | `files` pins all 51 loadable members; RPC rule added to monitoring and to the known blockers |
| Comparison | Qwen comparators were not covered by approvals | S3/S4 quote the Qwen model hashes; prerequisites enforced |

Remaining accepted limits: ETW file evidence classes a plain open as a read and sees no truncate or memory-mapped write of an
existing file; only job-object members are attributed; findings from the capture are retrospective.

## 9. Next explicit owner decisions

1. Done: **S0** and **S1** (2026-10-29).
2. Authorize **S2** (extract the b11960 archive into an evidence-local root and run `--version`/`--help` of `llama-completion.exe` and `llama-cli.exe` under the monitor): it needs the operator prerequisites in item 4 and a contract-driven D12a (item 3).
3. A follow-up package (proposed AI-QUAL-115B) to make `physical.py`/`d12a.py`/`stage_a_report` contract-driven: per-arm runtime,
   sampling and registry, member hashes for b11960, the contract digest in the execution manifest, `record_problems` enforcement, and a
   Stage B capture-split design. The S0 hashes now exist.
4. The operator-side prerequisites that block Qwen as well: system-wide Python, protected `capture_control.py` copy, a fresh canary, the firewall attestation.

No physical work, promotion or merge is requested or implied.
