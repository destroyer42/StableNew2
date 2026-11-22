# Agent context intelligence and AI-worker research roadmap

**Status:** Approved product direction; implementation not started by this documentation package.
**Scope:** Developer-experience support for StableNew, with optional read-only Proxmox AI-worker assistance and a separately gated image-analysis experiment.
**Authority:** This is a supporting sequencing and decision record. `docs/StableNew Roadmap v2.6.md` remains the one active roadmap; `STATUS.md` remains current-state truth; `AGENTS.md` is the sole operating-rule authority. Current checkout/branch/SHA/diff and living subsystem docs supersede this plan.
**Planning snapshot:** 2026-11-22; verify all hardware, software, model, and repository facts anew at each phase.

## Product problem and outcome

StableNew's coding agents spend substantial context on re-orienting to source ownership, repeated broad searches, long source/log outputs, and re-reading context across turns. A task-specific navigation layer may reduce these costs while preserving correctness. A local AI-worker may subsequently provide semantic retrieval and bounded source-grounded summaries without making remote inference a prerequisite to development.

**Success outcome:** Given a scoped work-package objective and a current checkout, a Claude Code/Codex session receives a small, verifiable list of authoritative sources, concrete code/test relationships, and reasons for each recommendation. The agent still inspects current source, validates work, and obeys `AGENTS.md`. Optional remote augmentation may be adopted only if measurements show additional benefit.

**Not the outcome:** Replacing the repository with a super-repo, stuffing the entire repository into an LLM prompt, treating a generated summary as engineering authority, auto-applying local model judgments, or training a model to memorize changing code.

## What already exists — reuse first

- `docs/CODEX_MAP.md`: manually curated short task-to-code routing (60-line gate).
- `tools/generate_code_map.py` and `docs/CODE_MAP.md`: generated map using each `src/` module's leading docstring; `tests/tools/test_code_map.py` verifies freshness.
- `docs/AGENT_OPERATING_MODEL.md`: small always-loaded context, one primary session per coherent package, read-only specialists only when worthwhile, evidence capsules rather than transcripts.
- `docs/AI_MODEL_SELECTION.md` and `tools/usage_report.py`: timestamp- and session-bounded token accounting, separate cached reads/fresh input/cache writes/output.
- `docs/Subsystems/AiAssist/AI_ASSIST.md`: existing local and approved SSH-forwarded inference boundaries; remote research must not silently extend production AI Assist authorization.
- `docs/Subsystems/Testing/TESTING_AND_CI.md`: docs-only CI and executable-code validation contracts.

The 2026-11-22 checked-in `CODE_MAP.md` reported **787 of 942** modules with docstrings (155 without). The latest 50 PRs (#331–#380) were reviewed for changed-file shapes; these show repeated code/test/documentation co-changes but **not** the complete set of files agents actually read. PR token totals cannot be reconstructed without valid session telemetry. Recount at the future implementation SHA.

## Sequencing and decision gates

| Stage | Work package / evidence | Output | Decision gate |
|---|---|---|---|
| 0. Baseline | Included in CONTEXT-100 discovery, not a mandatory separate PR | Representative task labels; existing-map retrieval baseline; measured agent traces only where authentic | Refuse unsupported PR-level usage attribution |
| 1. Deterministic retrieval | [PR-DEVEX-CONTEXT-100](PR-DEVEX-CONTEXT-100.md) | Static AST/index, task routing, bounded capsules; complete eligible module docstrings; deterministic tests | Accept only with no behavioral changes, source freshness, explainable source links and no weakening of repo gates |
| 2. AI-worker qualification | [AI-WORKER-110](AI-WORKER-110.md), independent read-only assessment first | Actual host/container/gpu measurements, approved model comparison, retrieval-quality/latency/VRAM report | Separate explicit owner authorization before container changes, model downloads, live inference or network alterations |
| 3. Optional semantic augmentation | [PR-DEVEX-CONTEXT-120](PR-DEVEX-CONTEXT-120.md) | Opt-in embedding/reranking behind read-only transport with deterministic fallback | Require meaningful incremental retrieval and end-to-end cost benefit without safety regression |
| 4. Image-analysis evaluation | Conditional, separate product work package after Stages 2–3 | Advisory caption/tag/quality inspection on consented copies of images | No production flow change or Learning authority without design, privacy and qualification approval |
| 5. Fine-tuning / distributed generation | Not approved; research only if evidence warrants | Go/no-go decision | Reject by default unless retrieval/benchmarks demonstrate an unmet need and scope is separately authorized |

Stages 2 and 3 may be halted without compromising Stage 1. Do not expand Stage 1 to include embeddings, model weights, RPC services, process managers, hardware changes or GPU activity. A single primary editing session/worktree per coherent work package remains the normal workflow.

## Stage 1 — minimum reliable context service

Route task text using the short task map, verified module docstrings, Python AST imports/exports, symbol names and tests. Report confirmed relationships separately from lexical/co-change guesses. Output a compact, source-version-bound capsule with reading order, reasons, important invariants, test suggestions, uncertain edges and explicit escalation to source inspection. Keep generated indices reproducible and invalidate them on source changes. Prefer a read-only local CLI, not a daemon or production app integration.

**Default capsule budget:** approximately 1,200 tokens. Exact cap/format is an implementation choice, validated on representative narrow and cross-boundary tasks. Never inject complete source, PR discussions or AGENTS content by default.

**Docstring completion:** include every eligible missing `src/` module docstring, accurately derived from code, without changing behavior beyond the module `__doc__` value. Regenerate `docs/CODE_MAP.md`; test AST equivalence after removing the new docstring from the after-version. Incomplete or ambiguous cases are surfaced, not filled with fictitious boilerplate.

**Baseline dataset:** historical PR files are seeds, not exhaustive labels. Curate independent task → necessary-code/test labels and negative/unrelated cases, prevent historical-future leakage, and report recall plus irrelevant-context burden. A 90% top-k primary-area recall target is aspirational, not a substitute for valid ground truth.

## Stage 2 — AI-worker hardware and model qualification

**Reported, not live-verified:** the Proxmox host `pve-g16`, container `ai-worker` (possibly CT 110), a laptop RTX 4070-class 8 GiB GPU, 16 GiB physical system RAM, Ollama and an operator-controlled SSH-forwarded endpoint. Container RAM and vCPU allocations and exact model inventory **must be measured**, not assumed from a conversation.

**Resource hypothesis:** subject to `free -h`, `lscpu`, `pct config`, actual GPU visibility, host safety/thermal observations and uptime, evaluate 12 GiB container RAM and 12–16 vCPUs, not a blanket 14 GiB/all-core allocation. Increased system RAM does not increase VRAM. No resource or network mutation is authorized by this plan.

**Candidate roles (benchmarks, not endorsements):**
- Baseline compact reasoning/classification: installed Qwen3.5 4B if verified; LFM3 1.7B if installed and license permits use.
- Embeddings: Qwen3-Embedding 0.6B first; 4B if its added recall warrants memory/time.
- Deep reranking/code reasoning: MiMo-V2.6-Distill-Qwen-9B and Qwen3.5 9B; 8 GiB GPU residency and context length are **unproven**, so measure actual loaded memory, CPU spills, thermal behavior and latency.
- Optional multimodal comparison: only after text retrieval gate; image-related candidates need a separate evaluation protocol.

Do not infer VRAM use from downloaded weight size or advertised context size. Start with measured short-context/single-flight runs; record `nvidia-smi`, `ollama ps`, observed token throughput, cold/warm latency, error/refusal rate, GPU/system memory and quality against the same tasks. Model names, tags, hashes, quantization and Ollama versions must be pinned in each evidence record.

## Stage 3 — remote retrieval without new authority

The primary code index and capsule builder stay local and deterministic. A local client may send only **explicitly selected, bounded, allowlisted source excerpts** to the operator-approved AI-worker for embedding, reranking or summarization. Do not send secrets, environment files, private operator outputs, PromptPacks, credentials or raw complete-repository archives. Keep canonical code/text available locally and do not rely on the model to regenerate source truth. Model responses are untrusted advisory data and must be schema-validated; preserve cited source path/fingerprint and reject hallucinated references. A failed tunnel/model must leave the deterministic result usable.

The remote endpoint must remain under an owner-approved local/SSH access model, with timeouts, cancellation, request bounds, no unsolicited downloads/egress, and no production generation or AI Assist service takeover. Treat a new network/data-sharing boundary as a material security/owner decision.

## Stage 4 — separate image-analysis hypothesis

Evaluate whether remote vision captioning, embeddings, duplicate/near-duplicate grouping, visual defects or experiment summaries help the operator. Restrict pilots to explicitly selected copies of non-sensitive generated artifacts and never replace canonical artifacts. Any resulting tags or findings are advisory; no automatic selection, discard, queue submission, model-policy update, Learning evidence promotion or qualification claim. Reuse current Review/Learning ownership and established AI-visual qualification work rather than creating a second judgment authority.

## ROI measurement and stop thresholds

**Primary:** end-to-end measured agent tokens for comparable tasks (cache read, fresh input, cache write, output individually) plus success, repair passes and correct source recall. **Secondary:** number of file/search reads, capsule size, elapsed discovery and task time, false negatives, irrelevance burden, network latency and AI-worker load. Compare at equivalent SHA, task, host/model/effort and acceptance standards; include context-service overhead and all participating sessions. Missing logs are `unavailable`, never zero or extrapolated from a commit.

The initial **20% median cached-read reduction** is a proposed pilot hurdle, not a guaranteed effect or a dollar-savings estimate. Reject or revise if savings arise through missed dependencies, weakening checks, broader reading recommendations, or higher defect/repair rates. Report cache volume separately from financial cost. Review whether savings come from retrieval or existing fresh-session discipline before adopting a new service.

**Stage 2 go/no-go:** semantic retrieval adds measurable source recall/precision or substantial reduced context cost over Stage 1 and remains stable within available VRAM/host budgets. If it does not, keep deterministic routing and do not add a network dependency.

## Reference starting points (read relevant portions only)

### Repository authority and current architecture
- [AGENTS.md](../../AGENTS.md)
- [STATUS.md](../../STATUS.md)
- [Task map](../CODEX_MAP.md) / [generated code map](../CODE_MAP.md)
- [Agent operating model](../AGENT_OPERATING_MODEL.md) / [model and token measurement](../AI_MODEL_SELECTION.md)
- [Code-map generator](../../tools/generate_code_map.py) / [verification tests](../../tests/tools/test_code_map.py)
- [AI Assist living document](../Subsystems/AiAssist/AI_ASSIST.md)
- [Testing/CI living document](../Subsystems/Testing/TESTING_AND_CI.md)

### External model and API documents (background, not executable approval)
- [Ollama embeddings](https://docs.ollama.com/capabilities/embeddings)
- [Ollama FAQ: context, residency and concurrency](https://docs.ollama.com/faq)
- [Qwen3 Embedding 0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) and [4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B)
- [MiMo V2.6 Distill Qwen 9B](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B)
- [LFM3 1.7B](https://huggingface.co/LiquidAI/LFM3-1.7B)
- [Research/qualification reference and evidence checklist](../research/AGENT_CONTEXT_AI_WORKER_REFERENCES_2026-11-22.md)

External pages and model claims may change; reverify versions, licenses, requirements and provenance before any physical experiment.

## Documentation and completion discipline

This documentation change approves a **plan** only; it does not implement the phases, operate the AI-worker, download weights, expose a service, change production code, publish downstream branches or merge protected refs. Each implementation package uses the current `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, current model-selection guidance, current SHA and separate explicit authorization for any protected/physical action. Keep `STATUS.md` a state summary, not a progress diary.
