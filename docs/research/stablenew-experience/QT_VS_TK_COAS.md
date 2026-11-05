# Qt vs Tk — courses of action (trade study)

**Status: research framing. No toolkit decision is made or implied; nothing was installed.** Licensing and Qt module selection remain unresolved and must be reviewed before any production decision. One host process, one toolkit: Tk and Qt are never competing production hosts in the same process.

## 1. Three different questions that prior documents blur

| Question | Answered by | Status |
|---|---|---|
| **Q-A. Can a better Tk dispatcher make the app feel faster?** | GUI-SEAM-743 | **Answered: NO-GO on tuning.** Callbacks-per-pump cuts synthetic burst latency 66% (E) but no candidate showed a worker-refresh benefit (best +8%, ±~20% at n=5); production stays 15 ms/32/8 ms. This says *nothing* about whether Qt could deliver a better experience (EV-26). |
| **Q-B. Does Qt give operator-visible performance over Tk?** | GUI-PORT-742 | **Answered for one read-only screen: no meaningful gain.** Startup +87 ms, idle +34 MiB, peak +79 MiB for Qt; filter −2.3 ms, selection −1.0 ms, refresh −18 ms; 96.7% of the burst gap was dispatcher policy (EV-25). |
| **Q-C. Can the toolkit deliver the *target experience* (responsive layout, gallery/list/media inspection, modern look, accessibility, real DPI) at acceptable cost?** | **Nobody** | **Unmeasured.** 742 compared scripted outcomes on one inspection screen, "not the same code or the same rendering effort", with Tk matching Qt on reach, tab order, focus, keyboard and *simulated* 150% DPI. It did not assess perceived quality, forms, dialogs, galleries, media inspection, or real scaling. |

743's NO-GO therefore **does not** support "Qt cannot deliver an improved experience"; it supports "do not tune the Tk pump." The 742 NO-GO is conditioned in its own text: *"The question that would reopen it is a product decision, not a measurement: does the operator … require assistive-technology support or true per-monitor scaling?"* — that decision has not been made (DECISION_REGISTER DR-O1).

### Reconciling the evidence

| Document | Established | Did not establish |
|---|---|---|
| GUI-QT-001 (10-25) | Source-level seams; toolkit is not the bottleneck for the tranche's defects; ≈54k Tk lines; lifecycle is controller-level | Any Qt runtime fact (nothing executed) |
| GUI-PORT-740 (10-30) | PySide6 6.12.0 runs on this host/Python 3.14; contained dispatcher, AppState, nav, shutdown semantics PASS in synthetic scope; one import blocker (later fixed by `design_values`) | Production shutdown, controllers, persisted UI state, packaging |
| GUI-PORT-742 (10-31) | Cost/benefit on one workspace; UIA 104/110 vs 0/31 named; 134 files/65.7k Tk-bound lines | Real DPI, multi-monitor, screen readers, other workspaces, design quality, effort of rendering |
| GUI-SEAM-743 (10-31) | Pump tuning has no operator-visible payoff; timer-resolution confound (15.6 ms vs 1 ms) | Production callback rates; richer views |
| This research | Tk-bound surface now 140 files/≈68.8k lines, 165 test files (EV-33) | Anything beyond source review |

## 2. Courses of action

**COA A — Tk redesign.** Keep the one Tk host. Re-organize flows (EXPERIENCE_ARCHITECTURE), build shared components (summary strip, anchored action bar, asset list/gallery, status drawer) with existing tokens, scroll contracts and view contracts. Candidate scope first: shell + one workspace. Risks: nested-scroll/wheel capture (EV-16), no per-widget accessibility tree, Treeview/Canvas scaling for large galleries (unmeasured), continued layout-contract bugs (831 needed ~12 commits).

**COA B — Qt-first isolated prototype.** Independent PySide6 environment *outside* every checkout (as 740/742 did), synthetic data, no production controllers. Same screens as COA A's prototype so the toolkits are compared on identical IA: shell, Create workspace, an N-thousand-item gallery/list, media inspection, forms, dialogs, 1280×680 responsive behavior. Needs separate authorization (PySide6 install, licensing note). Risks: prototype tests the toolkit, not the product (742's lesson); a nicer-looking mock proves little about 140 coupled files.

**COA C — Staged Qt migration.** Only if B warrants it. One active host selected at startup; toolkit-neutral presenters/state first (the GUI-QT-001 seam); dispatcher, shutdown, persistence parity; per-workspace cutover behind a single entry point; Tk host retired after parity. Risks: 140 files/165 tests, `AppController` widget reach (EV-34), concurrent roadmap edits in the same files, LICENSE/packaging unresolved (STATUS decision 1), no mixed host.

**Shared prerequisite for any COA:** extract presenters so views are thin. Hence COA A's work is mostly *reusable* by C; B's prototype is *discardable* by design.

## 3. Comparison against operator outcomes

`K` = known from evidence; `U` = unmeasured; `H` = hypothesis. Nothing is scored numerically because no operator-outcome data exist.

| Criterion | COA A (Tk) | COA B (Qt prototype) | COA C (staged Qt) |
|---|---|---|---|
| Task success without intervention | K: IMG-01/VID-01/LRN-01 DIRECT after 831 on Tk; failures were layout-contract bugs | U | U (prototype ≠ product) |
| Time/interactions for core jobs | U (baseline not yet captured) | U | U |
| Visibility of required steps/actions | H: fixable by IA + anchored bar, toolkit-independent | H: same | H: same |
| Learnability/discoverability | H: IA-driven | H: IA-driven | H |
| Perceived quality / modern appearance | U (dark theme, ttk) | U (Qt styling quality not assessed) | U |
| Responsiveness under realistic work | K: 743 no tuning payoff; 742 gap ≈ 18 ms refresh | K: ≈ 18 ms refresh advantage (synthetic) | same as B |
| Media inspection and large lists | U (Treeview/Canvas gallery unmeasured) | U (QAbstractItemView virtualization likely stronger, H) | H |
| Accessibility / UIA | K: 0/31 named; fundamental for Tk per 742 | K: 104/110 named; no screen reader run | same as B |
| Real display scaling | K: process DPI-unaware, bitmap-stretched at 150% (style guide); real scaling untested | K: per-monitor-v2 reported; real non-100% untested | same |
| Licensing/packaging | none new | U: LGPL/GPL options; 650 MiB metapackage; modules unselected | U; plus LICENSE unresolved |
| Migration effort & maintainability | lowest | prototype only | highest: 140 files, 165 tests |
| Preservation of canonical architecture | preserved | preserved (no controllers) | preserved only with one-host rule and presenter extraction |

## 4. Counter-critique (same-session adversarial pass)

*This is **not** an independent reviewer; it is a deliberate red-team by the authoring session. A genuinely independent review remains recommended before any decision.*

**Against the leading candidate (A first, B only on evidence):**
- **Successful tasks favor A.** After PR-831, IMG-01, VID-01 and LRN-01 pass with DIRECT reachability at normal, 1280×680 and maximized on Tk (EV-01..03). Unsuccessful tasks are mostly not toolkit-caused: IMG-03 lineage (EV-07), OPS-01 reason and state (EV-08/09), VID-03 admission (EV-10), VID-02 Blender (EV-11) are data/behavior/infra. Qt would fix none of them.
- **But the Tk-specific failures were real.** The Rating box squeeze and the Operator-Log overlap (EV-01/02) came from fixed weighted grids that Qt layouts, which honor minimum size hints by default, tend to avoid [H, untested here]. Continuing to patch Tk layouts has an unmeasured recurring cost.
- **Wheel capture is probably not toolkit-specific** (`QAbstractScrollArea` also consumes the wheel) [H]; a Qt rebuild composed as nested scrollers would reproduce EV-16.
- **"A first" can become indefinite deferral.** The 742 analysis says accessibility is a requirement question, not a measurement. If the owner needs UIA or true per-monitor scaling, A cannot meet it and the Tk-first work is partly wasted shell design; if not, A is clearly right. That is why DR-O1 gates everything.

**Against COA B:** a synthetic prototype risks 742's outcome (no actionable difference) at higher cost; PySide6 must be installed (outside the repo) and licensing reviewed first; a prototype built by one author in two toolkits has an effort asymmetry that biases toward the first-built.

**Against COA C:** AppController widget reach and the Learning/Review controllers (EV-34) make C a controller-extraction project first; the "no mixed host" rule means a long-lived branch; ratchets and 165 tests need dual-toolkit support during transition; Qt's rendering of the existing dark theme is unproven.

**Unnecessary preservation:** the three Make Video doors, duplicated "Show Guidance" and Review/Photo Optimize overlap may be legacy habits (EV-15). **Unnecessary removal:** expert workflows (Matrix, special studies, Motion Library, Storyboard JSON, experimental workflows) have recorded owner value; simplification must hide, not delete (proposed DR-P9).

## 5. Decision gates

| Gate | Condition to proceed | Owner |
|---|---|---|
| G0 | Owner states requirements: accessibility (UIA/screen reader), real DPI, "modern appearance" definition, acceptable packaging | Rob |
| G1 | IA and task scripts validated at low fidelity (VALIDATION T4) *before* toolkit work | research |
| G2 | COA A baseline captured (VALIDATION §3) | research |
| G3 | PySide6 install authorized; license/module review done; separate env outside checkouts | Rob |
| G4 | COA B prototype and a matching greenfield Tk build measured on identical scripts (≥ 5 participants-or-runs per arm; real display scales) | research |
| G5 | Only then: COA C architecture design (never implementation without a new authorization) | Rob |

**Stop criteria:** stop COA B if G0 shows no requirement a Tk redesign cannot meet; stop if the matched Tk build meets the pre-declared targets; stop if licensing cannot be resolved.

## 6. Provisional research recommendation (not a decision)

Do G0–G2 first: they are cheap and reusable under every COA. Treat COA B as an evidence-generating experiment gated on G0/G3, not a commitment. Do not design COA C yet.
