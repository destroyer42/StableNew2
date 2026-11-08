# UX-850-C — Windows desktop design system and prototypes

**Delivered:** an implementable **PROPOSED** presentation specification over the existing Tk application: reusable components, tokens, five annotated journey wireframes with compact counterparts, Windows sizing/accessibility requirements, feasibility and future acceptance cases. This is documentation and static visual research; no production screen or usability improvement is claimed delivered.

Use [B's N1 recommendation](../ux850-b/NAVIGATION.md): strengthen the current task groups and contextual routes. Preserve all nine persisted IDs, creation order, startup resolver, notebook selection owner and native-strip fallback. C does not adopt R1's proposed Library destination. The Library journey remains source-specific discovery; unified discovery is still incomplete.

## Execution Profile + Model/Reasoning Recommendation

- **Class / location:** Standard research and design, Local/Desktop; one fresh primary session, no subagents. Local source, an existing offline renderer and session telemetry fit this host.
- **Actual executor:** Codex Desktop, `gpt-6.1-sol`, High, confirmed by this session's logged turn metadata; recommendation and measured execution remain separate.
- **Model recommendation:** Codex GPT-6.1 Sol High / Claude Code Sonnet 5.5 High, per [selection authority](../../../AI_MODEL_SELECTION.md). One shared context across five workflows plus a geometry/identity challenge should minimize expected total successful-work and retry cost. A cheaper model requiring rediscovery is not assumed cheaper overall; architecture decisions are deferred rather than solved by a stronger tier here. Expected about 5M cache-read / 40k output tokens; actuals belong in the PR body.
- **Controller Surface Assessment:** no controller, coordinator, source or test edits. Future presentation must use the existing views, view contracts, dispatcher and services in [TK_FEASIBILITY.md](TK_FEASIBILITY.md); no new queue, lifecycle, persistence, cancellation or process owner and no ratchet increase. General handoff cancellation is a proposed contract, not universal current parity.
- **Token-Efficient Validation Plan:** reuse accepted A/B exact-source evidence; inspect only design-sensitive source; validate links/source anchors, SVG XML, bounds, text and contrast; inspect offline previews; run the policy's cheap documentation checks, evidence-body check and aggregate diff review. No full gate, app/GUI suites, resource probes or desktop interaction.

## Review route

| Artifact | Purpose |
|---|---|
| [COMPONENTS.md](COMPONENTS.md) | Shell, panels, authoring, selection, inspection, editing, Motion, Learning and common asynchronous interactions |
| [TOKENS.md](TOKENS.md) | Proposed visual roles, provenance and existing theme mapping |
| [PROTOTYPES.md](PROTOTYPES.md) | Ten inspectable SVGs; five B journey annotations, default/advanced and transition rules |
| [WINDOWS_ACCESSIBILITY.md](WINDOWS_ACCESSIBILITY.md) | Client-area/DPI matrix, reflow, keyboard, focus, contrast and accessibility requirements |
| [TK_FEASIBILITY.md](TK_FEASIBILITY.md) | Exact-base owning-source anchors, feasible reuse and gaps |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Measurable future UI cases linked to B steps and existing test entrypoints |
| [CHALLENGE.md](CHALLENGE.md) | Alternative-first and boundary/negative-case challenge, repairs and retained decisions |
| [EVIDENCE_AND_VALIDATION.md](EVIDENCE_AND_VALIDATION.md) | Identities, validation results and limits |

**Evidence boundary:** implementation = these Markdown/SVG research assets. Demonstration = source applicability, static checks and offline artifact inspection. Qualification = N/A, no verdict granted or broadened. Actual Tk reachability, Windows scaling, screen-reader access, interaction and operator benefit remain **UNVERIFIED**. A's partial Comprehensive assessment stays partial; C is a focused design specification, not another Comprehensive safety audit.

No canonical application truth changes: `STATUS.md`, architecture, roadmap and production styles remain unchanged. New locks/pins/draft scopes, durable collections, import/deletion, timelines, campaigns/evaluators and UX-DEC-072 remain gated. Publication, exact-head hosted CI and merge are **PENDING coordinator**, outside this session.
