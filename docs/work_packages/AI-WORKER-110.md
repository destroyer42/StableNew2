# AI-WORKER-110 — Proxmox resource and model-retrieval qualification

**State:** Proposed research/qualification package; separate explicit authorization required before any configuration change, model download or physical inference. Produces evidence and recommendation, not production integration.
**Parent plan:** [Agent context + AI-worker roadmap](DEVEX-CONTEXT_AI_WORKER_ROADMAP.md).
**Prerequisite:** Deterministic CONTEXT-100 benchmarks and labels exist, or an independently frozen equivalent baseline is supplied.

## Decision question

Can the existing operator-owned Proxmox AI-worker provide **incrementally better and cheaper** semantic code/document retrieval or compact research summaries than StableNew's deterministic context router, without harming host stability, violating data boundaries, or introducing an unnecessary service dependency?

This evaluation is **not** a general LLM leaderboard or a mandate to use every available CPU core. A strong small model and search index may outperform a larger model with poor retrieval.

## Execution profile

- **Class:** Standard read-only design and measurement; classify as Architectural and stop if a proposed production security/runtime ownership or networking change is necessary.
- **Host:** Local Proxmox host + existing operator-approved AI-worker, only when explicitly authorized for live experiments. Research and test-fixture preparation can be completed without running inference.
- **Claude Code:** Sonnet 5.5 High; **Codex:** GPT-6.1 Sol High (confirm per current `docs/AI_MODEL_SELECTION.md`).
- **Expected usage:** planning allowance ~4–12M cache-read / 20–60k output tokens for design, measurements, analysis and bounded repair; model inference GPU load, download size and task tokens are separately measured and not included in agent-token projections.
- **Participation:** One primary assessment session; specialist optional if isolation improves log analysis. Record exact timestamps and session IDs.

## Exact start and authorization gate

Verify branch/HEAD/worktree, latest `AGENTS.md`, `STATUS.md`, current `docs/CODEX_MAP.md`, `docs/AI_MODEL_SELECTION.md`, relevant AI Assist and testing guidance, and the accepted CONTEXT-100 benchmark SHA. Repository rules and current architecture take precedence over this dated contract.

**Before physical steps:** owner must expressly approve the target Proxmox host/container and the precise operation (observing host metrics, changing container resources, downloading named model artifacts, running bounded inference, exposing any interface). Approval of this roadmap is not that authorization. Read-only queries also require that the operator actually has a supported path to the host; this document makes no claim of current access.

Record whether operator state is sensitive, whether any source may be transferred, and whether existing AI Assist remote-preview restrictions apply. Do not inherit AI Assist's user-facing consent/qualification automatically.

## Platform feasibility inventory — read-only first

Operator-reported facts needing verification: Proxmox `pve-g16`, possible container `110` named `ai-worker`, nominal 8 GiB RTX 4070 Laptop VRAM, 16 GiB host RAM, Ollama via operator SSH tunnel. Do not assume the exact hardware, `lscpu` topology, CPU pinning, model residency, memory limits, existing Ollama service permissions or the tunnel identity.

Capture:
- Host `free -h`, `lscpu`, storage pressure and safe operating headroom.
- Relevant `pct config <actual-id>`, cgroup memory/CPU caps, swap, balloon/scheduling assumptions, GPU passthrough visibility.
- Inside container `nvidia-smi`, actual Ollama version, `ollama list` and `ollama ps` if already installed/authorized.
- Baseline idle/busy host CPU/RAM, GPU RAM and temperatures, existing services, thermal throttling, errors, power/restart behavior.
- Whether the operator's SSH-forwarded localhost endpoint is reachable without increasing exposure.

**Allocation hypothesis only:** evaluate 12 GiB container RAM and 12–16 vCPUs **if** the host can retain stable headroom. An alternative 14 GiB/all-core configuration is not preapproved and must be refused if unsafe. Cgroup memory is not GPU VRAM. More cores cannot guarantee faster GPU inference.

If observations show insufficient memory, denied GPU access, unstable thermals, or ambiguity about existing owner work, stop or recommend the lowest-resource design. Never "fix" the host automatically.

## Models and benchmarks (conditional on download/run approval)

| Candidate | Role | Initial evaluation question |
|---|---|---|
| Existing Qwen3.5 4B (verify installed tag/hash) | Baseline bounded reasoning/reranking | Is compact summarization already sufficient? |
| Existing LFM3 1.7B if installed/allowed | Lightweight classification | Can cheap routing improve latency without recall loss? |
| Qwen3-Embedding 0.6B | Semantic indexing/retrieval | Does retrieval add relevant source hits? |
| Qwen3-Embedding 4B | Quality challenger | Does any recall/precision improvement justify memory cost? |
| MiMo-V2.6-Distill-Qwen-9B, quantized | Deeper code reasoning | Does quality improve enough despite 8 GiB VRAM pressure? |
| Qwen3.5 9B, quantized | Larger-model comparator | Is MiMo actually better on StableNew tasks? |

Candidates and Ollama tags are not pinned deployment choices here. Before each live run, check official model provenance, license restrictions, supported format, exact weight digest, quantization, downloaded bytes, context limit and installed runtime compatibility. Provider performance claims are hypotheses, not StableNew evidence.

Test one GPU request at a time initially. Compare 4K/8K/16K usable contexts first and only test larger contexts if memory headroom permits. Record measured `nvidia-smi`, `ollama ps` residency (fully GPU versus CPU split), transient peak RAM, failure rate, cold/warm first-token latency, tokens/second, GPU power/temperature and the effect on existing AI Assist work. Avoid misleading inference from compressed weight size alone.

## Evidence design

Freeze a representative task set and source labels from Stage 1 before model experimentation, including:
- Simple file/symbol lookup; multi-subsystem bug; reverse dependency; indirect test; low-signal ambiguous request.
- Missing/contradictory source, stale SHA, current code versus historical PR claims.
- Negative prompts asking for unsupported code paths, secrets or private operator data.
- Explicit source-citation fidelity and false-confidence scoring.
- At least one task outside image/video domains to avoid accidental overfitting.

For each candidate pipeline compare deterministic route alone, embedding-only, embedding + small reranker, embedding + larger reranker. Model output must be bounded and include structured evidence references. Preserve identical input/accepted files, source SHA, model parameters and sample seeds where supported; record randomness/variance.

Compute retrieval recall@k and precision@k, index build/update time, offline resource cost, capsule tokens, context duplication, response time, failure/staleness rate and downstream coding-agent result if an authorized matched session study exists. Quantify cost of indexing, inference, context transfer, retries and administration. **Do not equate cached tokens to dollars** or invent missing telemetry.

## Acceptance and final decision

This assessment completes when it delivers a reproducible evidence bundle, hardware headroom table, per-model version/digest and results, qualitative failure review, explicit availability/security limits, and one of:

1. **GO to CONTEXT-120:** material improvement over deterministic routing, bounded host impact, no safety/correctness regression, credible service plan.
2. **HOLD:** evidence incomplete, resource/inference instability, license uncertainty or unsupported host access.
3. **NO-GO:** negligible retrieval gain or too much operational/context overhead; keep CONTEXT-100 standalone.

A proposed >20% downstream cached-token saving is a separate matched-agent benchmark, **not** something the model evaluation alone can claim.

## Scope exclusions / stop conditions

Exclude modifying StableNew production AI Assist, automatic changes to Proxmox resources or networking, model downloads by default, copying full repo/user output to worker, fine-tuning, new public endpoints, remote generation, qualification-promotion or hardware/firmware changes.

Stop on unexpected egress, access beyond owner authorization, excessive CPU/RAM/GPU pressure, ambiguous model identity, unstable inference, non-reproducible quality findings, sensitive content exposure, a materially new architecture decision, or expanded scope beyond the accepted task.

Record full session-based token usage per `docs/AI_MODEL_SELECTION.md` (including support sessions). Report missing data as unavailable, not zero. No push/merge/release or physical experiment without explicit action-level approval.

## Source references

See [research and verification checklist](../research/AGENT_CONTEXT_AI_WORKER_REFERENCES_2026-11-22.md), [AI Assist living contract](../Subsystems/AiAssist/AI_ASSIST.md), [Agent operating model](../AGENT_OPERATING_MODEL.md), [Model-selection rules](../AI_MODEL_SELECTION.md), [Ollama embeddings](https://docs.ollama.com/capabilities/embeddings), [Ollama FAQ](https://docs.ollama.com/faq), [Qwen embeddings](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) and [MiMo 9B model card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B).
