# UX-850-A — Current repository, architecture and UX gap assessment

**Outcome:** a current-source foundation for redesign, covering all 73 confirmed owner decisions and the existing workflows that can be reused. **Framework disposition: partial Comprehensive**, not an all-controls-green audit or a production-design approval. All twelve categories and eight critical controls are screened; exhaustive durable-store, adversarial security, Windows/process-negative and operator-payoff proof remain open. See the explicit coverage ledger.

Evidence cut: `main` at `8e1ee82b5fd8cc18437274e86e9af4f59938a799`, fetched and fast-forwarded in isolated branch `research/ux850-a-repository-gap`. Application source is byte-identical in Git to `3399f8032182b65bd904f8f27818d927909cd6a3`. The complete accepted product register is [R1 OWNER_DECISIONS.md](../ux-850-r1/OWNER_DECISIONS.md), not the predecessor's abridgment. UX-DEC-072 remains pending. No source, test, configuration, dependency or runtime was changed.

## Execution Profile + Model/Reasoning Recommendation

- **Class:** Standard, read-only research in understood architecture. Recommendations involving new durable contracts, campaign authority, migration or toolkit ownership remain separate Architectural decisions. This package implements none of them.
- **Location:** Local/Desktop; local isolated source and session usage logs materially fit this host.
- **Actual executor:** Codex Desktop, `gpt-6.1-sol`, High; measured host model metadata confirms the model. The recommendation is separate from the actual execution record.
- **Model recommendation:** Claude Code Sonnet 5.5 High / Codex GPT-6.1 Sol High per `docs/AI_MODEL_SELECTION.md`. One source-lock/reuse pass plus a distinct contract/binding challenge minimizes expected successful-work cost and retries; a stronger tier is reserved for a separately scoped unresolved architecture decision. No claim about live provider pricing/availability is made.
- **Expected usage:** about 5M cache-read / 40k output tokens for this executor; fresh-input/cache-write estimates unavailable. Measurement starts `2026-11-08T04:02:47Z` (November 7 in America/New_York), session `codex:01a1b952-96b0-7471-a6e5-4ee49d2dffe8`. The receipt was recorded at task start before substantive source tracing. Initial Git/authority preflight was in the same first call; no earlier session work is claimed in this window.
- **Predecessor:** `claude:b8f909b4-f50d-4268-bbeb-dac19ed77799` supplied two untracked drafts, stopping at its limit at `2026-11-08T03:52:15Z`. Its time/token scope is separately reported in the PR; no tracer/reviewer completion is accepted from its prose. No subagents were spawned here. The complete original README draft is preserved in local execution artifacts; the abridged [input draft](OWNER_DECISION_REGISTER_INPUT.md) is preserved unchanged, SHA-256 `0eee8c23622ae1769c4081adb1549b2c13da26562d03138a75feaef6a947772a`. Its one-line-only/source-count claims are superseded by the complete accepted register and this assessment.
- **Controller Surface Assessment:** no production edits. Traces inspect AppController, PipelineController, JobService, Learning wrappers and cohesive services. Existing physical-line ceilings remain AppController 6816, JobHistoryService 647, JobService 1227, PipelineController 1697; new-controller limit 600 (E34). Future presentation work belongs in existing view contracts/service owners; no ceiling increase, second dispatcher, compiler, scheduler, queue, History, cancellation or process authority is proposed.
- **Token-Efficient Validation Plan:** reuse all 39 unchanged R1 source hashes and accepted 141+7 non-GUI results; add exact production bindings and AST contract-shape checks; validate 73 IDs, category vocabulary, source/blob/hash/line anchors and relative links; run only the documented cheap docs gate, aggregate review and `git diff --check`; await exact-head hosted required checks. No application/GUI tests are rerun for this docs-only change.

## Read the package

| Deliverable | Document |
|---|---|
| Baseline, evidence identities, CI and limits | [BASELINE_AND_VALIDATION.md](BASELINE_AND_VALIDATION.md) |
| Exact-source index: 39 reused + 45 supplemental anchors | [SOURCE_INDEX.md](SOURCE_INDEX.md) |
| All 73 decisions, six separate evidence dimensions, twelve UX-DEC-071 subrequirements | [DECISION_TRACEABILITY.md](DECISION_TRACEABILITY.md) |
| Existing screen/workflow routes, negative paths and test entrypoints | [SCREEN_WORKFLOW_INVENTORY.md](SCREEN_WORKFLOW_INVENTORY.md) |
| Runtime, settings, stores and extension boundaries | [OWNERSHIP_BOUNDARY_MAP.md](OWNERSHIP_BOUNDARY_MAP.md) |
| Findings, dependencies, twelve-category/eight-control coverage and unknowns | [GAPS_RISKS_UNKNOWNS.md](GAPS_RISKS_UNKNOWNS.md) |
| Prioritized inputs for downstream Lanes B–F | [LANE_FINDINGS.md](LANE_FINDINGS.md) |
| Actual method-diverse challenge, corrections, scoped absence searches and rerun | [INDEPENDENT_CRITIQUE.md](INDEPENDENT_CRITIQUE.md) |
| Five additional source-verified findings added after merge (read-only addendum) | [ADDENDUM_SOURCE_FINDINGS.md](ADDENDUM_SOURCE_FINDINGS.md) |

## Main conclusions and evidence boundary

Existing profiles, PromptPacks, spatial edits, parent comparison, Storyboards, Movie Clips, Motion Library, output discovery and exact-job Learning recovery are foundations to connect, not rebuild. Gaps cluster around coherent settings/draft context, cross-source artifact reuse and end-to-end evidence payoff; advanced timelines, evaluators, research import and autonomous campaigns require more contracts and evidence. Six previous invariant-related “conflicts” are narrowed to partial implementation; adaptive confirmation retains a real unresolved direction conflict.

Implementation delivered here is documentation. Demonstration is source/binding/contract inspection, reused identity-applicable deterministic evidence and documentary checks. Qualification is **N/A: no verdict granted or broadened**. Installed resources, actual model quality, accessibility/DPI, operator timing and full safety-negative coverage remain unverified. SYSTEM-840 contains narrower PARTIALLY QUALIFIED records; absence of a full QUALIFIED entry is not evidence that every production backend is unqualified or disallowed.

No new material security/lifecycle threat was verified in this bounded static review; this is not a safety clearance. Research conclusions do not enable inference, authorize repairs or decide product choices. `STATUS.md`, architecture and roadmap truth did not change and are not edited. Package B/C are not started here.
