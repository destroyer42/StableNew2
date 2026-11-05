# Comparative prototype package — proposal (NOT STARTED, NOT AUTHORIZED TO BUILD)

**Status: proposal only.** The owner approved *proposing* a bounded comparative package (DR-A26, O12) but **not building it inside this research package**. Nothing here authorizes a prototype, a Tk-to-Qt migration, a second job-processing architecture, GPU generation, a change to production authority, or a toolkit decision. The toolkit decision stays open until comparative evidence has been reviewed.

## 1. Preconditions (all must be true before the package is opened)

| # | Precondition | State 2026-11-05 |
|---|---|---|
| C1 | B2–B5 baseline complete on `origin/main`, sealed, with unavailable measurements named | **Not started.** B1 partly done (EV-14). B2 awaits explicit owner authorization and an exclusive desktop (DR-A30); B4 needs separate approval immediately before it runs, with a restoration procedure. |
| C2 | Qt licensing, module and packaging assessment complete | **Partial** (`QT_PACKAGING_ASSESSMENT.md`): module/size/metadata facts measured; counsel/owner review and per-module license table outstanding. |
| C3 | Owner reviews this proposal and names the package, branch and environment | pending |
| C4 | Scoring criteria and acceptance thresholds pre-registered **after** C1 baselines and **before** any prototype run | pending (O15: no arbitrary numeric limits before baselines) |
| C5 | A separate branch/worktree and a Python 3.14 environment outside every checkout (the existing `gui-port740-env` may be reused for the Qt arm; the Tk arm uses the repo interpreter) | environment exists (EV-39); package branch does not |

## 2. Arms

- **COA A0 — Layout-first Tk prototype.** Isolated, synthetic-data prototype of the screen set below on Tk, using the existing design tokens (`design_values.py` → `ui_tokens.py` → `theme_v2.py`), the scroll-page contract (P1), fixed primary actions (P5), compact chrome (P2/P3) and the Learning working-pane priority (P4).
- **COA B — PySide6/Qt Widgets prototype.** The same screen set on `QtCore`/`QtGui`/`QtWidgets` only (no WebEngine, PDF, Multimedia, QML), styled to the same tokens.
- **Why both are isolated prototypes.** Comparing a Qt mock against the *production* Tk app would favor Qt by construction (the production app carries today's unfixed layouts and 140 coupled files). If the separate layout work package (DR-A28) later ships on production Tk, it supplies an additional data point; it is **not** the A0 arm unless it was built and measured under this protocol.
- **Not an arm:** a staged migration (COA C). It is considered only after reviewing this package's evidence, as a new decision.

## 3. Equivalence contract ("equivalent behavior, not attractive screenshots")

Each arm must pass the **same** behavior checks, driven by the same journey scripts (T1–T9, approved) and the same fixtures:

| Area | Behavior to demonstrate (both arms) |
|---|---|
| Shell | Task-first navigation with the same five intent groups; one scroll owner per workspace; fixed primary action bar; collapsible status/log drawer |
| Create workspace | Hybrid Create Image approach; automatic model-profile application with valid overrides preserved; customizable basic controls and pinnable advanced settings (owner-stated, O15; see section 7 caveat) |
| Review/Learning | Review workspace gets remaining height first; secondary panes reserve no space when empty; rating/compare reachable without scrolling the page at the 760 comparison viewport |
| Gallery/list | Same N-row synthetic gallery/history (N = 500, 5,000, 50,000): scrolling, filtering, selection, multi-select, virtualization behavior |
| Media inspection | Fit, 100%, zoom/pan, show/detach, source-pixel vs preview-pixel label |
| States and errors | Same state vocabulary including the accepted **Preparing** state (DR-A10); identical error text and disabled-with-reason rule |
| Queue path | Both arms submit **only** to a fake JobService port that records an Intent and returns canned lifecycle events; **no real queue, runner, backend or GPU**. "Confirm & Queue" shows a mandatory visible frozen-preview step (DR-A24) |
| Keyboard | Every control reachable and operable by keyboard; focus visibly indicated; contrast measured |
| Resize/scale | Reflow, clipping and reachability at 1280×680 and 1280×760, each at real 100%, 125% and 150% display scaling |

A single failing row marks that arm "not equivalent" for the affected journey; its numbers are then reported but not scored against the other arm.

## 4. Datasets and fixtures

Synthetic only: generated placeholder images and clips, generated history rows, generated experiment results. No real models, prompts, user assets or backends. Fixture digests recorded (the 742 approach). Both arms load byte-identical fixtures.

## 5. Scoring (measurable operator outcomes, owner-defined in O15)

| Criterion | Measurement |
|---|---|
| Task-first navigation and hierarchy | first-click correctness and navigation count on T4/T1; extra interactions (`extra_interaction_count`) |
| Consistent typography/spacing/alignment/control styling | automated token audit: every rendered control resolves to a token; count of off-grid values |
| Responsive, no clipped or unreachable controls | reachability probe: `DIRECT` / `WITH_WORKAROUNDS` / `BLOCKED` per control at each viewport × scale; clipped-text probe |
| Progressive disclosure | count of permanently visible advanced controls vs basic at default; required-for-admission controls never hidden |
| Consistent status/validation/error feedback | checklist across 10 canned error/state cases, identical wording and placement |
| Keyboard, focus, contrast | tab-order trace; focus-indicator pixel diff; WCAG contrast ratio computed from tokens and rendered pixels (UIA named-element count recorded as secondary, DR-A8) |
| Wasted space in preview/review | working-pane area ÷ client area at each viewport; empty-pane space |
| Cost | installer size, cold-start latency, memory, rendering responsiveness (gallery scroll, filter), dependency complexity, implementation effort in hours and lines per arm |

**Thresholds are not set here.** They are pre-registered after the baselines (C4). Results are reported as improved / unchanged / degraded / inconclusive with ranges, as in `VALIDATION_AND_BASELINES.md` §5.

## 6. Protocol

- **One participant (the owner, DR-A14):** ≥ 5 repeated sessions per arm, counterbalanced order, with a practice-effect note; no claim about other operators.
- **Build order:** randomized, or disclosed with effort accounting; both arms get the same time-box.
- **Research telemetry:** only the approved opt-in, local, content-free fields (`VALIDATION_AND_BASELINES.md` §10), enabled only in the prototypes.
- **Evidence:** sealed archives under `~\StableNewAcceptance\`, home paths redacted, screenshots reviewed before sharing.
- **Desktop control:** every run uses the exclusive-desktop rule (DR-A30); real display-scale changes need approval each time with a restoration step.
- **Bounds:** at most the five screens in section 3, the T1–T9 journeys, two viewports × three scales, N ≤ 50,000 gallery rows. Anything larger is a new proposal.

## 7. Evidence ledger: measured vs assumed vs unmeasured (completion-report item 3)

| Statement | Class | Basis |
|---|---|---|
| Global chrome on Tk at 1280×680 ≈ 33% of client height; Learning review pane starts ≈ 60% down and is ≈ 25% tall | **Measured** (Tk only) | EV-14; Learning also confirmed on the PR-831 archive whose code is an ancestor of `main` |
| Review-tab body size at the minimum | **Measured** but from the local 833 branch only | EV-14 origin note |
| Qt startup/idle/peak and small interaction deltas vs Tk | **Measured, Prior** (one read-only workspace, n = 5, loopback, 100% scale) | 742 |
| Dispatcher tuning gives no operator-visible gain | **Measured, Prior** | 743 |
| UIA naming 104/110 (Qt) vs 0/31 (Tk) | **Measured, Prior** | 742 |
| Qt Widgets-only on-disk footprint ≈ 6–7× Tk's runtime | **Measured** (file sizes only) | `QT_PACKAGING_ASSESSMENT.md` |
| Qt layout engine avoids the fixed-grid squeeze class of defects | **Assumed** | not tested |
| Wheel capture is toolkit-independent | **Assumed** | not tested |
| Qt virtualized views beat Treeview/Canvas for large galleries | **Assumed** | not tested |
| Either arm yields shorter task time or fewer errors for the owner | **Unmeasured** | no operator outcome exists for any arm |
| Modern appearance / perceived quality | **Unmeasured** | needs the O15 criteria applied |
| Real 125%/150% behavior of either toolkit | **Unmeasured** | B4 not run |
| Installer size, product-like cold start and memory | **Unavailable** | no packaged build |
| "Hybrid Create Image approach, automatic profile application with overrides preserved, pinnable advanced settings" are accepted product decisions | **Owner-stated, source not located in the repository** (`git grep -il hybrid` finds only a 2025 modernization report and an unrelated AI contract) | see DR-O16; the equivalence rows citing them are provisional |

**There are currently no comparable Tk-versus-Qt operator outcomes.** Every row above is either Tk-only, synthetic, file-size-level, or assumed.

## 8. Stop criteria

Stop and report if: a prototype needs a production controller, queue or runner; GPU, Forge or SVD activity would be required; the matched Tk arm meets the pre-registered targets (stop COA B); licensing cannot be resolved for the Widgets-only subset; the equivalence contract cannot be met by one arm; any measurement needs the owner's running application; effort in either arm exceeds the declared time-box.

## 9. What the owner must decide to launch

1. Open the package (C3) and name its branch, environment and time-box.
2. Authorize each desktop run (B2, and prototype runs) when the exclusive-desktop condition holds; approve B4/real scaling runs individually.
3. Decide the Qt license route or confirm that the prototype may proceed under the LGPL/commercial question being open (a prototype does not distribute anything).
4. Confirm or supply the source for the "previously accepted" Create Image decisions (DR-O16).
