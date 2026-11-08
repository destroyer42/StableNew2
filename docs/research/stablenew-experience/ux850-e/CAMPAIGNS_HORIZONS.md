# Campaign boundaries and conditional delivery horizons

Existing proposal and batch services are a foundation for bounded explicit studies, not an unattended campaign engine. Anchors E10–E19/E25–E28/E41–E43 and D's accepted lifecycle/recovery research establish the seams. Horizons below are prioritization judgments, not dates, resource promises or authority to implement.

## Existing admission and recovery

`EvidenceProposalPlanner` derives candidates offline from exact identity, policy, catalog, resources and baseline. Save Drafts is create-only; Preview freezes/compiles without admission. Queue Selected confirms exact new work and revalidates the whole selection before its first submission. One experiment then crosses the existing Learning execution owner and `JobService.submit_njrs` with SQLite lifecycle. A selection of experiments is **not one transaction**; earlier confirmed work remains after later failure or cancellation.

Batch admission checkpoints expected IDs before crossing JobService. A lost acknowledgement reconciles those exact experiment/variant/job identities. It stops subsequent submissions, retains known/unknown state and does not retry uncertain work. A JSON checkpoint plus a SQLite commit is not a multi-store atomic transaction. Recovery never matches by a human-readable name, rebuilds old intent from live controls or automatically resubmits. Queue pause holds future claims; it does not stop a running backend. Existing resume/replay options and fresh campaign authorization are distinct, as D documents.

Existing recommendation automation modes are also distinct from campaigns: suggest-only, default apply-with-confirm and an explicitly selected auto-micro path. The current controller guards automatic evidence eligibility, validates stage/model/revision/targets, applies a rollback-capable patch and may submit one existing Preview through the canonical submission method. That small existing mode does not authorize new screening/repair/model routing or unattended campaign stages. E changes none of its semantics and does not claim the source path was demonstrated live.

## Proposed minimum campaign contract — held at G3/G4/G6

| Concern | Contract needed before implementation / current alternative |
|---|---|
| Approved plan identity | Immutable version binds hypotheses, cases, checkpoints/runtime/profile/adaptation, constraints, permitted stage transitions and material-deviation rules; operator approvals must apply to this identity, session and expiry. Current explicit study Preview/Run remains sufficient for ordinary work |
| Estimates versus budgets | Images/denoising work are estimates. Elapsed seconds, energy, money, peak RAM/VRAM/commit and storage growth need measured methods and units. Reservations across in-flight admissions, exact charging on unknown outcomes and remaining work require policy; no numbers chosen here |
| Stage gate | Only previously approved transition/criteria can advance. Evidence/readiness unknown, identity drift, evaluator mismatch or a material deviation must hold proposed future submission for review. A model's plan is advisory, never the gate decision |
| Incremental admission | Compile existing typed intent to NJRs, validate current approval/resources and cross canonical JobService. Campaign metadata never claims jobs or duplicates lifecycle. Define stop-intent versus in-flight reservation/admission linearization before promising immediate stop |
| Windows and priority | Decide timezone/DST, allowed windows, stale-reading policy, interactive precedence and fairness; changing a window cannot cancel an admitted job. No new dispatcher, OS priority control or resource preemption authority |
| Reconciliation | Save expected IDs before admission; on restart reconcile canonical jobs before considering separately authorized continuation. Preserve partial prefixes, unknown outcomes and newer drafts. A stored plan is not approval |
| Recovery playbooks | Versioned allowed action/trigger/scope/expiry, fresh identity and owner authority. Diagnose/hold first. Never auto-replay ambiguous POST, adopt/kill/restart external processes, substitute models/settings after failure or infer physical authorization |
| Evaluation and publication | Frozen evaluator identity and applicability; human observations kept separate; uncertainty can propose a follow-up. Stage success never auto-publishes a profile, qualifies a model or changes startup/favorites |

Resource checks reuse current canonical readiness and resource projections. AI Assist's observation/yield guard is not mutual exclusion with a queue claim and cannot be borrowed as a generic resource lease. No catalog or `STATUS.md` entry proves present installation, host capacity or absence of GPU quarantine. New campaign resource limits need separately accepted measurements and safety policy.

## Prioritized horizons

| Horizon / priority | Coherent outcome | Why / dependence / acceptance boundary |
|---|---|---|
| H0 — first, reuse current mechanisms | Better provenance and capability/refusal presentation over existing studies, profiles and deterministic next-test summaries | Highest-confidence reuse, no inference required. A future authorized bounded package should prove displayed source/effective/unknown distinctions and preserve action semantics; no policy change |
| H1 — next, deterministic research contracts | Common-task benchmark descriptors, evidence applicability/dependence previews and requalification suggestions | Enables comparison without an evaluator. G6/072 must settle method before consequential pooling; G1 for lock/fallback behavior. Use current studies/manual review pending that decision |
| H2 — only after identity-applicable qualification | Qualified optional prompt advice, then separately validated image screening/evaluator release if it beats manual/deterministic routes | C05 existing integration lowers wiring work, not qualification cost. C12–C14 need new data/security/model/hardware evidence; CPU latency/memory and vision performance unmeasured |
| H3 — after campaign authority and resource contract | Bounded incremental campaign proposals/control center using existing admission and reconciliation | G3/G4/G6 precede implementation. Prove stale approval, stop/admit races, unknown acknowledgements, accounting and no second runtime owner deterministically; physical runs require exact authorization |
| H4 — research, no enablement recommendation | Personalized predictors, AI-adaptive templates and consequential imported research synthesis | Highest data-dependence/calibration risk; G5/G6/072 plus privacy/qualification. Reject if no validated benefit over explicit human selection |

The ordering is sensitive to operator needs and available evidence, not a numeric value score. If the owner needs quick manual experimentation, H0/current studies deliver value first. If a consequential profile/import decision is urgent, methodology/conflict review may precede new UI polish. No usage denominator, time saved, inference speed or maintenance cost was measured; these are prioritization hypotheses to test, not established payoff.

All horizons retain D G8 implementation/operator evidence acceptance and A/B/C limits. Before a functional phase, recheck exact accepted SHA/diff and relevant CI/authorities. This E package completes documentation locally; hosted checks, publication and integration remain PENDING coordinator.
