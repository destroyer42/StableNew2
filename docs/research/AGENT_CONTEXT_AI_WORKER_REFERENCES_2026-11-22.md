# Agent context / Proxmox AI-worker — research references and evidence checklist

**Type:** Dated supporting research and verification notes, **not** an engineering authority, model approval, system-state attestation or executable plan.
**Research cut:** 2026-11-22.
**Decision supported:** Implement deterministic, source-fingerprint-bound task routing first. Experiment with a local AI-worker only after comparing to that baseline and explicitly approving physical model/data operations.

## Authority and repository evidence

At the planning cut, remote `destroyer42/StableNew2` `main` was `6cc6f95916fa5f0105f114a245c2987550518fd3`. Current checkout/branch/diff have precedence; do not freeze this SHA as a future implementation base.

| Question | Current repository entrypoint | What it establishes / does not |
|---|---|---|
| What governs coding agents? | [AGENTS.md](../../AGENTS.md), [operating model](../AGENT_OPERATING_MODEL.md) | Authority and session procedure; context summaries may not override rules |
| What is current project state? | [STATUS.md](../../STATUS.md) | Short current-state account; no PR diary |
| Where should a task start? | [CODEX_MAP.md](../CODEX_MAP.md) | Hand-maintained short navigation (60-line guard), not architecture authority |
| What modules exist? | [CODE_MAP.md](../CODE_MAP.md), [generator](../../tools/generate_code_map.py) | Module-first-sentence map generated from docstrings, not a semantic dependency graph |
| How is map freshness validated? | [tests/tools/test_code_map.py](../../tests/tools/test_code_map.py) | Existing committed-map check and 60-line task map/path controls |
| How is agent usage measured? | [AI_MODEL_SELECTION.md](../AI_MODEL_SELECTION.md), `tools/usage_report.py` | Timestamp/session-bound usage; `--since-commit` is post-commit only |
| What remote AI rules already apply? | [AI_ASSIST.md](../Subsystems/AiAssist/AI_ASSIST.md) | Existing app-bound local and operator-approved forwarded inference; independent developer research is **not** automatically qualified/authorized |
| What is the docs-only lane? | [TESTING_AND_CI.md](../Subsystems/Testing/TESTING_AND_CI.md) | Documentation-only cheap checks; no production test/physical proof |

`docs/CODE_MAP.md` on this cut reported **787 of 942 modules** with module docstrings; the actual starting inventory must be re-counted. The last 50 PRs (#331–#380) provide changed-file cohorts and possible task labels, but they do **not** show every source a coding agent read. Exact context waste cannot be deduced from PR changes or token totals without complete session telemetry.

## Why deterministic navigation first

A repo-wide language-model prompt can exceed effective GPU/context budgets and create repetitive input. A code-index and narrow source retrieval path can be audited for freshness and correctness, works offline, and can form the baseline for testing generative reranking. Fine-tuning weights to contain changing repository facts causes stale knowledge and adds training/data-governance cost. Reconsider adaptation only if retrieval+prompt changes demonstrably fail on stable task categories.

This is a design hypothesis; it is not a measured savings claim. Prompt caching may reduce input unit cost, but cached reads still consume metered tokens and share the context budget. A smaller context capsule does **not** guarantee cheaper end-to-end work when the agent must recover missing dependencies.

## Existing module-map and docstring mechanics

`tools/generate_code_map.py`:
- Walks `src/**/*.py`, skipping `__pycache__`.
- Parses module source via Python `ast` without importing application code.
- Takes the first paragraph/sentence of the module-level docstring, capped at 110 characters.
- Prints `(no docstring)` or `(could not be parsed)` as applicable.
- Regenerates `docs/CODE_MAP.md`; `--check` refuses stale committed output.

A module docstring must be semantically accurate, not a tautology. Preserve initial comment/license/shebang/encoding and `from __future__` semantics. Source AST before versus after (after excluding newly inserted leading docstring node) should match, with expected `__doc__` metadata differences reviewed. Because code can inspect `__doc__`, test/document any exceptional import-time consequences. Do not format or rewrite unrelated source in a mass-docstring package.

A future dependency index should distinguish:
- **Proven by static parse:** resolvable imports, locally defined symbols.
- **Heuristic:** related names, test path resemblance, PR co-changes.
- **Unknown:** dynamic import, reflection, runtime registry/dispatch, unexecuted conditional import, external plugin.
- **Current/expired:** matching source fingerprint versus stale snapshot.
Do not convert heuristic relevance into a claim of runtime control, data ownership or required tests.

## Remote AI-worker hypothesis and verification

The operator has described `pve-g16`, a Proxmox `ai-worker` container (possibly CT 110), a mobile RTX 4070 with nominal 8 GiB VRAM, Ollama, and a previously SSH-forwarded localhost endpoint. These have **not** been inspected through this document-writing session; resource and endpoint details must be reverified live by an explicitly authorized operator.

**Initial read-only command suggestions, after access approval:**

```sh
free -h
lscpu
pct list
pct config <verified-CT-ID>
pct exec <verified-CT-ID> -- nvidia-smi
pct exec <verified-CT-ID> -- ollama list
pct exec <verified-CT-ID> -- ollama ps
```

No command above adjusts memory, CPU, GPU, network or installed models. If tool availability/access differs, do not infer state from an error. Avoid placing addresses, SSH private keys, passwords or full environment variables in PR evidence.

**RAM/CPU:** 12 GiB and ~12–16 vCPUs are a provisional trial for a host believed to have 16 GiB RAM and a high-core-count CPU. Confirm host reserved headroom, filesystem cache, temperature, swap and actual core topology before proposing any adjustment. A 14 GiB container cap or "almost all cores" may starve the host. Container CPU count is scheduling availability, not GPU capacity; GPU VRAM stays approximately 8 GiB.

**Model candidates, by workload, not a blanket replacement:**

| Model family | Role | Qualification risk |
|---|---|---|
| Qwen3.5 4B (existing if verified) | Compact general reasoning and source summarization | Inference context and prompt grounding |
| LFM3 1.7B (existing if verified) | Fast lightweight classification | License and more limited complex coding capacity |
| Qwen3-Embedding 0.6B | Lowest-resource semantic retrieval | Recall/semantic miss rate |
| Qwen3-Embedding 4B | Quality/recall candidate | Extra memory, latency and GPU residency |
| MiMo-V2.6-Distill-Qwen-9B | Harder code-oriented reranking | 8 GiB GPU headroom, CPU spills, large context KV cache |
| Qwen3.5 9B | Larger-model comparator | Same VRAM/context/latency challenge |

Check specific model tags/digests/licenses at experiment time. Published 9B weight sizes and vendor advertised maximum contexts do not establish full-GPU residency at 8 GiB. Document actual context, KV-cache use, `ollama ps` residency and token throughput.

## External source bibliography — verify again at qualification time

1. [Ollama embeddings capability / API](https://docs.ollama.com/capabilities/embeddings) — embedding requests for semantic text indexing; API shape and compatible models require version check.
2. [Ollama FAQ](https://docs.ollama.com/faq) — memory residency, keep-alive, parallel requests, context and loading; the on-host Ollama version can differ.
3. [Qwen3-Embedding 0.6B model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) — embedding sizes, intended retrieval task, release and licensing.
4. [Qwen3-Embedding 4B model card](https://huggingface.co/Qwen/Qwen3-Embedding-4B) — higher-capacity embedding comparator.
5. [MiMo V2.6 Distill Qwen 9B model card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B) and [Ollama library page](https://ollama.com/library/mimo-v2.6) — code-agent candidate, available quantizations/tags; vendor benchmark claims are not StableNew acceptance.
6. [Liquid AI LFM3 1.7B model card](https://huggingface.co/LiquidAI/LFM3-1.7B) — lightweight specialized local inference; read the actual license for intended use.
7. [Python ast documentation](https://docs.python.org/3/library/ast.html) — static module/docstring parsing without executing imported application code.
8. [Aider repository map documentation](https://aider.chat/docs/repomap.html) — external design comparison for small code maps and relevance-ranked context; not a required dependency.
9. [Anthropic prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) and [OpenAI prompt caching](https://platform.openai.com/docs/guides/prompt-caching) — caching pricing/behavior concepts; applicable rates and API details depend on model/host.

No external model documentation, model-card benchmark or example command grants permission to execute physical inference, download weights, expose a service, transfer user data or promote a model to a production qualified tier.

## Study design and measurement-quality checklist

- [ ] Freeze exact repo SHA, code-index schema, corpus inclusion/exclusion set and task labels.
- [ ] Include narrow, cross-subsystem, ambiguous, negative and stale-version tasks.
- [ ] Independently validate relevant source areas; historical changed files are insufficient labels.
- [ ] Compare deterministic route, lexical-only baseline, embedding-only and embedding+reranker under the same task/corpus budget.
- [ ] Report recall@k **and** precision/irrelevance; higher recall from dumping dozens of files is not improvement.
- [ ] Report capsule bytes/tokens, source/path citation correctness and source-fingerprint freshness.
- [ ] Report worker cold/warm latency, output tokens, GPU VRAM, total RAM, thermal/CPU spill and failure/timeout rate.
- [ ] Test model refusal, hallucinated path, inconsistent SHA, partial network loss and sensitive-path exclusion.
- [ ] Matched agent-study, if approved: same task/SHA/model/effort/acceptance conditions; record actual start/end and all sessions. Report cache-read, fresh input, cache-write and output **separately**.
- [ ] Report time/operator labor and new maintenance costs; investigate whether an apparent win simply moves cost to a hidden service.
- [ ] If benchmark does not improve correctness-adjusted retrieval, recommend NO-GO rather than expanding implementation.

## Boundaries and next gate

The [CONTEXT-100 implementation package](../archive/work_packages/PR-DEVEX-CONTEXT-100.md) is the first implementation objective. [AI-WORKER-110](../work_packages/AI-WORKER-110.md) is a separately authorized qualification; [CONTEXT-120](../work_packages/PR-DEVEX-CONTEXT-120.md) is conditional integration. Image-analysis work remains an independent later product/qualification decision.

Do not modify `STATUS.md` merely to narrate this research. Adopted runtime/architecture changes belong in their current living docs and must pass the current owner decision and validation process.
