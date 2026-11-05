# StableNew experience redesign — research foundation (PR-GUI-UX-850)

**Status:** research foundation, source review only. **No production code, test, dependency, configuration or runtime behavior is changed by this work.**
**Opened:** 2026-11-05. **Branch:** `research/gui-ux-850-experience-redesign`, from `origin/main` `ed1e989f2149b01d16aef26d5f880326aeb250e0`.
**Authority:** `AGENTS.md` and `STATUS.md` win over everything here. This directory records hypotheses and evidence; it authorizes no implementation, prototype, dependency, publication or toolkit decision.

## Purpose

Find the simplest coherent operator experience for creating, editing, animating, experimenting with, organizing and improving generated assets, and test whether a redesign (on Tk, on Qt, or staged) is justified by operator outcomes rather than appearance.

## What this research is not

- **Not user testing.** No operator was observed. Every usability statement is either a code/doc/archive observation or an explicitly labelled hypothesis. The only operator-reported material is the owner's brief (section 5 of PR-GUI-UX-850) and the 2026-10-22 audit's `[O]` items.
- **Not a toolkit decision.** `QT_VS_TK_COAS.md` frames the options. Nothing was installed; no PySide6 or Tk prototype was built.
- **Not an owner-decision record.** Owner answers to workflow questions are **pending**. Anything not traceable to the owner's own words or a repository decision is marked `PENDING` or `PROPOSED`.

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
| 2 | The owner's `layout-recommendation.md` **was not found** on the machine (searched the repo, `~/Downloads`, Documents, Desktop, project folders). | Section 5's findings are taken from the brief's wording and cross-checked against sources; they are not quoted from the report. See EV-27. |
| 3 | A local branch `fix/journeys-833-advanced-golden-path-reliability` (clone `StableNew-main`, head `b986c33c`) is **not on `origin/main` and has no remote-tracking ref** that contains it. It claims repairs for GP832-F1..F4 and sealed `d8e3e9d0` archives. | Reported as local, unpublished evidence. On `origin/main` GP832-F1..F4 are `UNREPAIRED`. See EV-07..EV-10. |
| 4 | Sealed acceptance archives and screenshots live outside Git (`~\StableNewAcceptance\golden-paths\`). They use a **loopback fake backend** at 2560×1440, 100% scaling. | No real-DPI, real-model or physical-GPU claim is possible. |

## Navigation

| Document | Content |
|---|---|
| [EVIDENCE_REGISTER.md](EVIDENCE_REGISTER.md) | Source-backed findings with SHA/evidence location, confidence and falsification tests |
| [WORKFLOW_INVENTORY.md](WORKFLOW_INVENTORY.md) | User-facing workflow inventory and issue-to-workflow matrix |
| [workflows/](workflows/) | Nine living discovery records (scaffolds; owner answers pending) |
| [EXPERIENCE_ARCHITECTURE.md](EXPERIENCE_ARCHITECTURE.md) | Candidate task-first IA, shell, flows, state boundaries (Mermaid) |
| [DESIGN_SYSTEM_CANDIDATE.md](DESIGN_SYSTEM_CANDIDATE.md) | Candidate components, density, disclosure, states |
| [QT_VS_TK_COAS.md](QT_VS_TK_COAS.md) | Three-COA trade study and counter-critique |
| [AI_GUIDED_EXPERIENCE.md](AI_GUIDED_EXPERIENCE.md) | Three AI tiers, governance, improvement monitoring |
| [VALIDATION_AND_BASELINES.md](VALIDATION_AND_BASELINES.md) | Metrics, task scripts, prototype tests, stop criteria |
| [DECISION_REGISTER.md](DECISION_REGISTER.md) | Accepted vs proposed decisions |
| [RESEARCH_LOG.md](RESEARCH_LOG.md) | Dated discovery outcomes and session identity |

## Current research phase

**Phase 0 — foundation published; discovery pending.** Done: evidence reconciliation, workflow scaffolds, candidate IA/design system, COA framing, AI governance, validation plan. **Not done:** owner interviews for any of the nine workflows (every workflow record is `DISCOVERY OPEN`), any prototype, any measurement of operator task time. The next gate is an owner review of the open questions in each workflow file and `DECISION_REGISTER.md`.

## Existing canonical documents (linked, not copied)

[AGENTS.md](../../../AGENTS.md) · [STATUS.md](../../../STATUS.md) · [CODEX_MAP](../../CODEX_MAP.md) · [GUI ownership map](../../Subsystems/GUI/GUI_Ownership_Map_v2.6.md) · [GUI style guide](../../Subsystems/GUI/GUI_STYLE_GUIDE.md) · [2026-10-22 GUI audit](../../audits/2026-10-22_gui_ux_audit_and_tranche.md) · [GUI-QT-001](../../assessments/2026-10-25_gui_qt_001_feasibility.md) · [GUI-PORT-740](../../assessments/2026-10-28_gui_port_740_qt_compatibility.md) · [GUI-PORT-742](../../assessments/2026-10-31_gui_port_742_qt_workspace_qualification.md) · [GUI-SEAM-743](../../assessments/2026-10-31_gui_seam_743_tk_dispatcher_budget.md) · [GUI-COMPLETE-760](../../assessments/2026-11-01_gui_complete_760_image_workflow_reachability.md) · [Testing and CI §11a/11b](../../Subsystems/Testing/TESTING_AND_CI.md) · [findings registry](../../../tools/operator_journey/golden/findings.v1.json) · [coverage matrix](../../../tools/operator_journey/golden/coverage_matrix.v1.json) · [AI Assist](../../Subsystems/AiAssist/AI_ASSIST.md)
