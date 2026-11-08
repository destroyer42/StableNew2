# StableNew experience redesign — research foundation (PR-GUI-UX-850)

**Status:** research foundation, source review only. **Owner disposition 2026-11-05: provisionally accepted on the reported evidence; comparative qualification remains open; not an authorization to merge, migrate toolkits or change production runtime behavior (DR-A22).** **No production code, test, dependency, configuration or runtime behavior is changed by this work.**
**Opened:** 2026-11-05. **Branch:** `research/gui-ux-850-experience-redesign`, from `origin/main` `ed1e989f2149b01d16aef26d5f880326aeb250e0`.
**Authority:** `AGENTS.md` and `STATUS.md` win over everything here. This directory records hypotheses and evidence; it authorizes no implementation, prototype, dependency, publication or toolkit decision.

## Purpose

Find the simplest coherent operator experience for creating, editing, animating, experimenting with, organizing and improving generated assets, and test whether a redesign (on Tk, on Qt, or staged) is justified by operator outcomes rather than appearance.

## What this research is not

- **Not user testing.** No operator was observed. Every usability statement is either a code/doc/archive observation or an explicitly labelled hypothesis. The only operator-reported material is the owner's brief (section 5 of PR-GUI-UX-850) and the 2026-10-22 audit's `[O]` items.
- **Not a toolkit decision.** `QT_VS_TK_COAS.md` frames the options. This research installed nothing; a PySide6 6.12.0 environment from earlier work already exists on the host (EV-39). No PySide6 or Tk prototype was built.
- **Not a workflow-discovery record yet.** The nine workflow files are still `DISCOVERY OPEN`: the owner answered the cross-cutting decision questions on 2026-11-05 (DECISION_REGISTER DR-A8..A21) but not the per-workflow discovery contracts. Anything not traceable to the owner's own words or a repository decision is marked `PENDING` or `PROPOSED`. The only usability participant is the owner (DR-A14).

## Evidence hierarchy

1. Current repository source, `AGENTS.md`, `STATUS.md` (at the verified SHA).
2. Living subsystem docs and sealed local acceptance archives (hash-identified).
3. Dated assessments and audits (point-in-time; may be superseded by shipped PRs).
4. The owner's brief (PR-GUI-UX-850 section 5).
5. This directory's hypotheses (lowest; never evidence for themselves).

Evidence tags used throughout: **[V]** verified in source/archive this session; **[D]** documented in a repo doc but not re-verified; **[O]** owner/operator-reported; **[H]** hypothesis; **[U]** unknown.

## Source-lock caveats (read first)

| # | Caveat | Effect |
|---|---|---|
| 1 | `origin/main` is `ed1e989f` (PR #253, QUAL-SYSTEM-840). The brief verified `d76d1acd` during planning. The only commits since are PR-QUAL-SYSTEM-840's (ledger/frozen plans/gates), none GUI. | None on UX findings. |
| 2 | `layout-recommendation.md` was missing at first and was **re-supplied by the owner on 2026-11-05** (it is an assistant-authored recommendation from the PR-831 session, never committed). Its seven findings and seven proposals are folded in (EV-27, EV-38, DR-P10..P12); its measurements were re-checked by pixel script (EV-14). | Treat its proposals as inputs awaiting the owner's pick (DR-O14), not decisions. |
| 3 | A local branch `fix/journeys-833-advanced-golden-path-reliability` (clone `StableNew-main`, head `b986c33c`) is **not on `origin/main` and has no remote-tracking ref** that contains it. It claims repairs for GP832-F1..F4 and sealed `d8e3e9d0` archives. | Reported as local, unpublished evidence. On `origin/main` GP832-F1..F4 are `UNREPAIRED`. See EV-07..EV-10. *Later note (2026-11-05):* the branch merged to `main` as PR #254 (`f5830839`), after the B2 code-under-test SHA `ed1e989f`. |
| 4 | Sealed acceptance archives and screenshots live outside Git (`~\StableNewAcceptance\golden-paths\`). They use a **loopback fake backend** at 2560×1440, 100% scaling. | No real-DPI, real-model or physical-GPU claim is possible. |

## Navigation

| Document | Content |
|---|---|
| [UX-850-R1 integrated assessment](ux-850-r1/README.md) | Later 73-decision traceability, five operator journeys, current-source feasibility and bounded delivery contracts (assessment at `3399f803`; partial evidence coverage) |
| [EVIDENCE_REGISTER.md](EVIDENCE_REGISTER.md) | Source-backed findings with SHA/evidence location, confidence and falsification tests |
| [WORKFLOW_INVENTORY.md](WORKFLOW_INVENTORY.md) | User-facing workflow inventory and issue-to-workflow matrix |
| [workflows/](workflows/) | Nine living discovery records (scaffolds; owner answers pending) |
| [EXPERIENCE_ARCHITECTURE.md](EXPERIENCE_ARCHITECTURE.md) | Candidate task-first IA, shell, flows, state boundaries (Mermaid) |
| [DESIGN_SYSTEM_CANDIDATE.md](DESIGN_SYSTEM_CANDIDATE.md) | Candidate components, density, disclosure, states |
| [QT_VS_TK_COAS.md](QT_VS_TK_COAS.md) | Three-COA trade study and counter-critique |
| [AI_GUIDED_EXPERIENCE.md](AI_GUIDED_EXPERIENCE.md) | Three AI tiers, governance, improvement monitoring |
| [VALIDATION_AND_BASELINES.md](VALIDATION_AND_BASELINES.md) | Metrics, task scripts, prototype tests, stop criteria |
| [DECISION_REGISTER.md](DECISION_REGISTER.md) | Accepted vs proposed decisions |
| [PROPOSED_AI_ASSIST_AMENDMENT.md](PROPOSED_AI_ASSIST_AMENDMENT.md) | Draft `AI_ASSIST.md`/`STATUS.md` amendment for planning assistance (inactive; decision draft) |
| [QT_PACKAGING_ASSESSMENT.md](QT_PACKAGING_ASSESSMENT.md) | Qt licensing, module and packaging assessment (partial, measured vs unavailable) |
| [COMPARATIVE_PACKAGE_PROPOSAL.md](COMPARATIVE_PACKAGE_PROPOSAL.md) | Proposed separate COA A0 vs COA B package (not built), DPI experiment protocol, and the measured/assumed/unmeasured ledger |
| [DECISION_HANDOFF.md](DECISION_HANDOFF.md) | Final decision handoff: round-3 dispositions, D-1 to D-5 verbatim with recommendations and conflicts, open items, session boundary |
| [BASELINE_B2_B3_B5_RESULTS.md](BASELINE_B2_B3_B5_RESULTS.md) | Executed B2/B3/B5 baseline on `main`: sealed archives, wheel probes, large-history load |
| [NEXT_SESSION_B2_B3_B5_CONTRACT.md](NEXT_SESSION_B2_B3_B5_CONTRACT.md) | Bounded acceptance contract and kickoff text for the B2/B3/B5 execution session (B4 excluded); executed, see the results above |
| [RESEARCH_LOG.md](RESEARCH_LOG.md) | Dated discovery outcomes and session identity |

## Current research phase

**Phase 0 — documentation milestone provisionally accepted; research qualification incomplete; B2/B3/B5 baseline executed.** Done: evidence reconciliation, workflow scaffolds, candidate IA/design system, COA framing, AI governance, validation plan, owner decisions (three rounds), layout-recommendation intake, B1 chrome measurement (four screenshots), independent review applied, draft AI-assist amendment (inactive), partial Qt licensing/module/packaging assessment, comparative-package proposal with DPI protocol, Create Image product-intent record, decision handoff and next-session contract, and the B2/B3/B5 baseline ([BASELINE_B2_B3_B5_RESULTS.md](BASELINE_B2_B3_B5_RESULTS.md), executed 2026-11-05 under that contract and merged with PR #255).

B2/B3/B5 measured code at `ed1e989f` with the simulated harness and loopback fakes only (one 2560x1440 display at 100%; no real backend, GPU, real DPI or operator timing). B2's sealed suites FAIL at all three layouts: GP832-F1 (OPS-01) and GP832-F3 (IMG-03) reproduce, GP832-F2 reproduces as an observation, VID-02 is HOLD because Blender is absent, and GP832-F4 was not exercised. B3 finds the wheel captured at the inner limit for the Job History and Motion Library trees. B5 finds no N-dependent history load cost up to 50,000 rows, with the panel bounded at 20 rows. PR #254 (golden-path repairs) merged after `ed1e989f`, so these failures are not evidence about current `main` without a new run. [DECISION_HANDOFF.md](DECISION_HANDOFF.md) still says B2/B3/B5 had not run; that was true at its decision point and is kept as history.

**Not done:** owner discovery for the nine workflows (every record is `DISCOVERY OPEN`); B4 (not approved); any prototype; any operator task timing; adjudication of D-1 to D-5; Qt legal review.

## Later integrated assessment

[UX-850-R1](ux-850-r1/README.md) preserves the subsequently supplied 73-decision owner register and maps it against `3399f803`. It supplements the historical discovery status above; UX-DEC-072 remains pending. It proposes the next bounded foundation package and grants no implementation, toolkit, runtime or merge authorization.

## Existing canonical documents (linked, not copied)

[AGENTS.md](../../../AGENTS.md) · [STATUS.md](../../../STATUS.md) · [CODEX_MAP](../../CODEX_MAP.md) · [GUI ownership map](../../Subsystems/GUI/GUI_Ownership_Map_v2.6.md) · [GUI style guide](../../Subsystems/GUI/GUI_STYLE_GUIDE.md) · [2026-10-22 GUI audit](../../audits/2026-10-22_gui_ux_audit_and_tranche.md) · [GUI-QT-001](../../assessments/2026-10-25_gui_qt_001_feasibility.md) · [GUI-PORT-740](../../assessments/2026-10-28_gui_port_740_qt_compatibility.md) · [GUI-PORT-742](../../assessments/2026-10-31_gui_port_742_qt_workspace_qualification.md) · [GUI-SEAM-743](../../assessments/2026-10-31_gui_seam_743_tk_dispatcher_budget.md) · [GUI-COMPLETE-760](../../assessments/2026-11-01_gui_complete_760_image_workflow_reachability.md) · [Testing and CI §11a/11b](../../Subsystems/Testing/TESTING_AND_CI.md) · [findings registry](../../../tools/operator_journey/golden/findings.v1.json) · [coverage matrix](../../../tools/operator_journey/golden/coverage_matrix.v1.json) · [AI Assist](../../Subsystems/AiAssist/AI_ASSIST.md)
