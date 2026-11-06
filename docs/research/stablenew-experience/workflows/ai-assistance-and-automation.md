# Workflow W8 — AI assistance and automation

**Discovery status: OPEN.** Last updated 2026-11-05. Governance contracts: [AI_GUIDED_EXPERIENCE.md](../AI_GUIDED_EXPERIENCE.md).

## Observed current state [V/D]
- **Offline AI Assist**: Prompt tab **Suggest…** (prompt rewrite, target-fit advice, workflow advice) disabled; nothing installed; every model NOT TESTED; qualification held on D12b and a protected-interpreter ETW canary. Output is text for an editing buffer; Accept revalidates the full source fingerprint; nothing saves, compiles or queues (AI_ASSIST §2, §11).
- AI package may not import queue/repository/job service/runner/NJR (ratchet baseline 0). Request-scoped cancellation; AI yields to generation and to GPU quarantine.
- **Smart Review** (opt-in): SAM 2.1 Small points/boxes and Florence-2 captions in a contained CPU child; unqualified.
- Deterministic precedents: *What Should I Test Next?* (evidence classes, no AI), Operator Readiness, model compatibility preflight (EV-36, EV-37).
- "Workflow Choice" advice is unavailable until an eligibility-checked closed list exists (AI_ASSIST §10).

## Owner direction (brief)
Three separately governed tiers: (1) explain and suggest, (2) goal → editable plan validated deterministically then admitted through normal Intent/NJR, (3) bounded guided multi-step flows. AI never submits. Optional, privacy-conscious local improvement monitoring; deterministic checks first.

## Confirmed decisions (repository)
AI Assist D1–D12 (one-shot contained subprocess; CPU-only v1; hash-pinned third-party GGUF; refusals surfaced, never sanitised; no training-data capture; request-scoped cancel). `src.ai` settings-suggestion stub retired.

## Hypotheses [H]
H1: Most operator value arrives from Tier 1 deterministic explanations (why disabled, why incompatible) before any language model is involved. H2: Plan-level approval is useful only if the plan is shown as editable structured steps, not prose. H3: Telemetry can start as local, deterministic counters with no content.

## Alternatives
(a) Stay with deterministic explanation; defer language models. (b) Qualify the offline model, ship Tier 1 only. (c) Tier 2 plan editor on top of (b). Tier 3 only after (c) proves safe.

## Flows
Current: operator → Suggest… (disabled) → review dialog → Accept into buffer → ordinary Preview/Queue. Ideal: PENDING for the workflow as a whole. **Owner direction already given (2026-11-05):** model-assisted planning wanted before qualification finishes (DR-A11); an approved plan offers *Send to Preview* or *Send to Preview and queue immediately* (DR-A13); telemetry local, 90 days (DR-A12). See AI_GUIDED_EXPERIENCE §0.

## Discovery contract — status
1–5 PENDING · 6 Expert: model/runtime selection (held) · 7 Duplicates: none yet · 8 Reuse: prompt history for suggestion context (privacy open) · 9 This workflow *is* AI · 10 Boundaries: see AI_GUIDED §2–§4 · 11 Failure: refusals and admission outcomes use stable copy [D] · 12 Artifact: editing-buffer text / editable plan · 13 Acceptance: none.

## Open questions
Q1 Which operator problems justify a language model vs deterministic explanation? Q2 Is any cloud/remote model ever acceptable? (Existing decisions are offline-only.) Q3 What telemetry, if any, will the owner consent to? Q4 Who decides when a model is "qualified enough" for Tier 2?
