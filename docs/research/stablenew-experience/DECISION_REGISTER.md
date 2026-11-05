# Decision register

Rule: only items traceable to the owner's words or a repository authority are **ACCEPTED**. Proposals stay **PROPOSED** and are not decisions. Assessment verdicts are not owner decisions ("Neither verdict authorizes anything", GUI-PORT-742/743).

IDs: `DR-A#` accepted · `DR-P#` proposed (this research) · `DR-O#` open owner question.

## Accepted (recorded elsewhere; restated for traceability)

| ID | Decision | Date | Source | Alternatives rejected | Implication for this research |
|---|---|---|---|---|---|
| DR-A1 | Canonical path `Intent → Compiler → NJR → JobService → Queue/Repository → run_njr → Handler → Artifacts/History`; GUI captures intent and renders projections; fresh work is queued | standing | `AGENTS.md` §2 | second queue/runner/history authority | Every candidate shell binds to existing ports; AI cannot submit |
| DR-A2 | Approved Comfy workflows are production video backends; experimental needs the job's own opt-in, never a global switch | 2026-10-20 | `AGENTS.md` §2, `STATUS.md` decision 10 | global experimental switch | Auto engine choice must respect governance state and per-job opt-in |
| DR-A3 | Composition-root decision (11) accepted for the **Tk production host only**; does not authorize Qt or a second GUI host | 2026-10 | `GUI_Ownership_Map` §GUI-SEAM-730; `STATUS.md` decision 11 | n/a | COA B/C need a new decision; no mixed host |
| DR-A4 | Preserve the workflow-centric top navigation and stable tab IDs; "do not rebuild the entire GUI"; do not delete Refiner/Hires/img2img merely because rarely used | 2026-10-22 | GUI audit "Product direction", "Critical appraisal" | big-bang rewrite | **Under re-examination by the PR-850 mandate**; reopening it is itself an owner call (DR-O8) |
| DR-A5 | PR-850 is research and documentation only: no Tk→Qt migration, no final toolkit decision, no prototype, no dependency/runtime/production change, no push/merge without explicit authorization | 2026-11-05 | PR-GUI-UX-850 brief §1, §13 | n/a | Scope guard for this directory |
| DR-A6 | AI must not submit directly; approval of an AI plan produces normal Intent; AI imports no queue/repository/runner/NJR | standing + brief | `AGENTS.md`; `AI_ASSIST.md` §8; brief §10 | direct AI submission | Contracts in AI_GUIDED_EXPERIENCE |
| DR-A7 | Offline AI Assist decisions D1–D12 (CPU-only v1, one-shot contained subprocess, hash-pinned models, refusals surfaced, no training capture) | 2026-10 | `AI_ASSIST.md` §1 | cloud/resident server | Any model-assisted tier is offline-only unless the owner reopens it |

## Assessment verdicts (not owner decisions)

| ID | Verdict | Source | Status |
|---|---|---|---|
| AV-1 | GUI-QT-001: NO-GO/DEFER production migration | 2026-10-25 | Recommendation; owner selection (A or B) not recorded in repository |
| AV-2 | GUI-PORT-740: CONDITIONAL GO for a separately approved bounded Qt package | 2026-10-30 | Never separately approved (742 followed) |
| AV-3 | GUI-PORT-742: NO-GO for production Qt migration *on current evidence*; reopen by product decision on accessibility/per-monitor scaling | 2026-10-31 | Recommendation |
| AV-4 | GUI-SEAM-743: NO-GO on tuning the Tk pump | 2026-10-31 | Recommendation; says nothing about Q-C (QT_VS_TK_COAS §1) |

## Proposed (NOT accepted)

| ID | Proposal | Evidence | Alternatives | Rationale / unresolved |
|---|---|---|---|---|
| DR-P1 | Organize by operator intent: Create · Edit/Improve · Animate · Experiment · Library/History | EV-30; EV-15 | keep current groups; add only Library | Test by card sort and first-click (VALIDATION T4) before adopting |
| DR-P2 | One anchored primary-action bar per task state | EV-14, EV-17 | fixed strips only where needed (existing pattern) | Needs a measured below-fold problem on `main` |
| DR-P3 | At most two disclosure levels; no admission-required control hidden | EV-19 | status quo | Unknown whether any required control is hidden today |
| DR-P4 | Promote Library/History to a destination | EV-30, library workflow | keep inside Pipeline | Usage data absent |
| DR-P5 | Collapse Operator Log into a status drawer | EV-14 | shrink fonts/rows at small heights | Needs chrome-ratio baseline |
| DR-P6 | Three AI tiers with deterministic validation and per-step approval | EV-35..37 | deterministic-only | Contracts only; no model qualified |
| DR-P7 | Opt-in, local, content-free improvement signals | AI_GUIDED §6 | none (offline comparator only) | Privacy requirements pre-conditions |
| DR-P8 | Chrome budget ≤ 20% of a 680 px window | EV-14 | other numeric target | By-eye measurement; re-baseline first |
| DR-P9 | Simplify by hiding/relocating, not deleting, expert workflows (Matrix, special studies, Motion Library, Storyboard JSON, experimental workflows) | DR-A4; audit | retire some | Retirement is a separate owner decision |

## Open owner questions

| ID | Question | Why it matters |
|---|---|---|
| DR-O1 | Does the operator (or anyone who will use StableNew) require assistive-technology support or true per-monitor scaling on non-100% displays? | 742 states this is the question that reopens Qt; also defines accessibility acceptance |
| DR-O2 | Disposition of the local, unpublished PR-QUAL-JOURNEYS-833 branch (`b986c33c`): publish, adopt, or discard? | Determines whether EV-07..EV-10 are repaired for the redesign baseline |
| DR-O3 | GP833-F1: should a claimed job awaiting an unreachable backend show a distinct "preparing" state? | Lifecycle/state vocabulary for the job progression strip |
| DR-O4 | Is model-assisted planning wanted before offline AI qualification completes? | Sequencing of Tier 1 vs 2 |
| DR-O5 | Is any improvement telemetry wanted? Which signals? Retention? | AI_GUIDED §6 |
| DR-O6 | May a Tier-2 approval enqueue with immediate start, or only produce a Preview? | Approval boundary |
| DR-O7 | Who are the test participants (owner only, plus others)? | Validity of usability evidence |
| DR-O8 | Does the PR-850 mandate supersede the 2026-10-22 "preserve top-level groups" direction? | Scope of IA research |
| DR-O9 | Where is `layout-recommendation.md`? Please re-supply. | EV-27 |
