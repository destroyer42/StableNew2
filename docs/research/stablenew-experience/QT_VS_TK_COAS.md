# Qt vs Tk — courses of action (trade study)

**Status: research framing. No toolkit decision is made or implied; nothing was installed.** Licensing and Qt module selection remain unresolved and must be reviewed before any production decision. One host process, one toolkit: Tk and Qt are never competing production hosts in the same process.

## 1. Three different questions that prior documents blur

| Question | Answered by | Status |
|---|---|---|
| **Q-A. Can a better Tk dispatcher make the app feel faster?** | GUI-SEAM-743 | **Answered: NO-GO on tuning.** Callbacks-per-pump cuts synthetic burst latency 66% (E) but no candidate showed a worker-refresh benefit (best +8%, ±~20% at n=5); production stays 15 ms/32/8 ms. This says *nothing* about whether Qt could deliver a better experience (EV-26). |
| **Q-B. Does Qt give operator-visible performance over Tk?** | GUI-PORT-742 | **Answered for one read-only screen: gains of a few milliseconds against no operator latency budget (742 defined none; "no meaningful gain" is this study's wording).** Startup +87 ms, idle +34 MiB, peak +79 MiB for Qt; filter −2.3 ms, selection −1.0 ms, refresh −18 ms; 96.7% of the burst gap was dispatcher policy (EV-25). |
| **Q-C. Can the toolkit deliver the *target experience* (responsive layout, gallery/list/media inspection, modern look, accessibility, real DPI) at acceptable cost?** | **Nobody, as a whole** (742 measured UIA naming and simulated DPI only) | **Unmeasured as a whole.** 742 compared scripted outcomes on one inspection screen, "not the same code or the same rendering effort", with Tk matching Qt on reach, tab order, focus, keyboard and *simulated* 150% DPI. It did not assess perceived quality, forms, dialogs, galleries, media inspection, or real scaling. |

743's NO-GO therefore **does not** support "Qt cannot deliver an improved experience"; it supports "do not tune the Tk pump." **Where this study departs from the prior assessments (stated openly):** 742's own conclusion was "NO-GO … Qt work stops here" and "if no [accessibility/real scaling requirement], the remaining differences do not justify the cost"; GUI-QT-001 set explicit conditions for reopening Qt, including "a measured, reproducible Tk limit on a named surface" surviving a Tk prototype. This study explores Qt anyway **because the owner directed it** (DR-A8), not because those conditions were met; a Qt prototype would be a deliberate departure from 742/QT-001 and the stop criteria in §5 are the safeguard. The 742 NO-GO is conditioned in its own text: *"The question that would reopen it is a product decision, not a measurement: does the operator … require assistive-technology support or true per-monitor scaling?"* — the owner has since answered (2026-11-05, DR-A8): **no** such requirement today, and the owner explicitly rejects the inference that this ends the Qt work. This document therefore evaluates Qt on the remaining Q-C criteria; accessibility and real scaling are measured, not gating.

### Reconciling the evidence

| Document | Established | Did not establish |
|---|---|---|
| GUI-QT-001 (10-25) | Source-level seams; toolkit is not the bottleneck for the tranche's defects; ≈54k Tk lines (non-blank lines, 121 files; **not** the same basis as the 68.8k physical lines in the last row); lifecycle is controller-level | Any Qt runtime fact (nothing executed) |
| GUI-PORT-740 (10-30) | PySide6 6.12.0 runs on this host/Python 3.14; contained dispatcher, AppState, nav, shutdown semantics PASS in synthetic scope; one import blocker (later fixed by `design_values`) | Production shutdown, controllers, persisted UI state, packaging |
| GUI-PORT-742 (10-31) | Cost/benefit on one workspace; UIA 104/110 vs 0/31 named; 134 files/65.7k Tk-bound lines | Real DPI, multi-monitor, screen readers, other workspaces, design quality, effort of rendering |
| GUI-SEAM-743 (10-31) | Pump tuning has no operator-visible payoff; timer-resolution confound (15.6 ms vs 1 ms) | Production callback rates; richer views |
| This research | Tk-bound surface now 140 files/≈68.8k lines, 165 test files (EV-33) | Anything beyond source review |

## 2. Courses of action

**COA A — Tk redesign.** Keep the one Tk host. Re-organize flows (EXPERIENCE_ARCHITECTURE), build shared components (summary strip, anchored action bar, asset list/gallery, status drawer) with existing tokens, scroll contracts and view contracts. Candidate scope first: shell + one workspace. Risks: nested-scroll/wheel capture (EV-16), no per-widget accessibility tree, Treeview/Canvas scaling for large galleries (unmeasured), continued layout-contract bugs (PR-831 was a long series of per-defect commits; the count was not re-verified here).

**COA B — Qt-first isolated prototype.** Independent PySide6 environment *outside* every checkout (as 740/742 did), synthetic data, no production controllers. Same screens as COA A's prototype so the toolkits are compared on identical IA: shell, Create workspace, an N-thousand-item gallery/list, media inspection, forms, dialogs, 1280×680 responsive behavior. Environment exists and its reuse is authorized (DR-A19); building the prototype still needs an explicit go and a licensing/module note (DR-O12). Risks: prototype tests the toolkit, not the product (742's lesson); a nicer-looking mock proves little about 140 coupled files.

**COA C — Staged Qt migration.** Only if B warrants it. One active host selected at startup; toolkit-neutral presenters/state first (the GUI-QT-001 seam); dispatcher, shutdown, persistence parity; per-workspace cutover behind a single entry point; Tk host retired after parity. Risks: 140 files/165 tests, `AppController` widget reach (EV-34), concurrent roadmap edits in the same files, LICENSE/packaging unresolved (STATUS decision 1), no mixed host.

**COA A0 — Tk-only layout repair first (baseline arm, added after independent review).** Deliver the layout recommendation's P1–P3, P5 and P7 on the existing Tk host, optionally make the process DPI-aware, and re-measure (EV-14 script, journeys) *before* any new IA or toolkit work. This is the cheapest option, is reusable by A/B/C, and gives the matched "Tk after fixes" arm that any Qt comparison needs; without it a Qt prototype would be compared against today's unfixed layouts and would look better by construction. Not a decision: the owner picks the layout work (DR-O14).

**Top risks to the whole study (stated up front):** (1) every redesign motivation beyond the brief and the 2026-10-22 audit is an unmeasured hypothesis, and the only participant is the owner, who is also the designer (n = 1, expert bias); (2) a Qt migration touches 140 files/165 tests while nine workflow discoveries are still open, so a toolkit choice made before discovery could lock in the wrong IA; (3) COA B builds the same screens twice by one author, so effort asymmetry biases toward whichever is built first; (4) owner direction to explore Qt departs from 742/QT-001's reopen conditions (§1).

**Shared prerequisite for any COA:** extract presenters so views are thin. Hence COA A's work is mostly *reusable* by C; B's prototype is *discardable* by design.

## 3. Comparison against outcome criteria

`K` = known from harness or assessment evidence; `U` = unmeasured; `H` = hypothesis. **No cell is a measured operator outcome**: the "K" entries come from loopback-fixture journeys and the 742/743 assessments, not from a person doing tasks. COA A shows more `K` only because the product runs on Tk and only Tk has been measured; `U` for B and C is an evidence gap, not a deficit. Nothing is scored numerically.

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
| Real display scaling | K: **the app** sets no DPI awareness, so Windows bitmap-stretches it at 150% (style guide); this is a configuration choice, not a Tk limit: `SetProcessDpiAwareness(2)` gives Tk real 144-DPI scaling (untested here for the product's layouts); real scaling untested | K: both 742 children ran per-monitor-v2; real non-100% untested | same |
| Licensing/packaging | none new | U: LGPL/GPL options; 650 MiB metapackage; modules unselected | U; plus LICENSE unresolved |
| Migration effort & maintainability | lowest | prototype only | highest: 140 files, 165 tests |
| Preservation of canonical architecture | preserved | preserved (no controllers) | preserved only with one-host rule and presenter extraction |

## 4. Counter-critique (same-session adversarial pass)

*This is **not** an independent reviewer; it is a deliberate red-team by the authoring session. A genuinely independent review remains recommended before any decision.*

**Against the leading candidate (A first, B only on evidence):**
- **Successful tasks favor A.** After PR-831, IMG-01, VID-01 and LRN-01 pass with DIRECT reachability at normal, 1280×680 and maximized on Tk (EV-01..03). Unsuccessful tasks are mostly not toolkit-caused: IMG-03 lineage (EV-07), OPS-01 reason and state (EV-08/09), VID-03 admission (EV-10), VID-02 Blender (EV-11) are data/behavior/infra. Qt would fix none of them.
- **But the Tk-specific failures were real.** The Rating box squeeze and the Operator-Log overlap (EV-01/02) came from fixed weighted grids that Qt layouts, which honor minimum size hints by default, tend to avoid [H, untested here]. Continuing to patch Tk layouts has an unmeasured recurring cost.
- **Wheel capture is probably not toolkit-specific** (`QAbstractScrollArea` also consumes the wheel) [H]; a Qt rebuild composed as nested scrollers would reproduce EV-16.
- **"A first" can become indefinite deferral.** The 742 analysis treated accessibility as the question that would reopen Qt. The owner has answered it "no" (DR-A8) *and* declined to treat that as the end of Qt, which is the right correction: the 742 test compared one read-only screen, and the criteria that could favor Qt (layout engine that honors size hints, virtualized galleries, rendering quality, long-term maintainability of the shell) were never measured (Q-C). Without a target-experience measurement, "no requirement, therefore Tk" would be a conclusion from absence of evidence. **Consequence for this study:** the defensible bias is *toward measuring Q-C cheaply*, not toward either toolkit.

**Against COA B:** a synthetic prototype risks 742's outcome (no actionable difference) at higher cost; a PySide6 environment already exists outside the repo (EV-39) but licensing and module selection (the env includes WebEngine and PDF) are still unreviewed; a prototype built by one author in two toolkits has an effort asymmetry that biases toward the first-built.

**Against COA C:** AppController widget reach and the Learning/Review controllers (EV-34) make C a controller-extraction project first; the "no mixed host" rule means a long-lived branch; ratchets and 165 tests need dual-toolkit support during transition; Qt's rendering of the existing dark theme is unproven.

**Unnecessary preservation:** the three Make Video doors, duplicated "Show Guidance" and Review/Photo Optimize overlap may be legacy habits (EV-15). **Unnecessary removal:** expert workflows (Matrix, special studies, Motion Library, Storyboard JSON, experimental workflows) have recorded owner value; simplification must hide, not delete (proposed DR-P9).

## 5. Decision gates

| Gate | Condition to proceed | Owner |
|---|---|---|
| G0 | **Partly answered 2026-11-05.** Accessibility/UIA and per-monitor scaling: *not required today* (DR-A8) and **no longer a stop condition**; they stay as measured criteria. **Still open:** a definition of "modern appearance" and acceptable packaging (DR-O15) — without a target, Q-C cannot be scored. | Rob |
| G1 | IA and task scripts validated at low fidelity (VALIDATION T4) *before* toolkit work. Scripts T1–T9 approved (DR-A21); the only participant is the owner (DR-A14). | research |
| G2 | COA A baseline captured (VALIDATION §3). B1 (pixel chrome) done for four screenshots (EV-14); B2–B5 authorized (DR-A18), B2 pending. | research |
| G3 | **Environment satisfied:** existing PySide6 6.12.0 environment outside every checkout, reuse authorized (DR-A19, EV-39). **Not done:** license/module review (WebEngine/PDF included in that env). | Rob |
| G4 | COA B prototype and a matching greenfield Tk build measured on identical scripts. With a single participant, "≥ 5 per arm" means ≥ 5 repeated, counterbalanced sessions per arm, reported with the learning-effect caveat (VALIDATION §5); real display scales needed. **Needs an explicit go** (DR-O12). | research |
| G5 | Only then: COA C architecture design (never implementation without a new authorization) | Rob |

**Stop criteria (revised 2026-11-05):** stop COA B if the matched Tk build meets the pre-declared targets; stop if licensing cannot be resolved; stop if the prototype would need a production controller or runner. **Withdrawn:** "stop if G0 shows no requirement a Tk redesign cannot meet" — the owner stated that a missing accessibility/scaling requirement does not make Qt valueless (DR-A8), and the layout recommendation's "do not move toolkit" is a prior opinion to be re-tested (DR-A17).

## 6. Provisional research recommendation (not a decision)

Do G1–G2 first (cheap, reusable under every COA), and define the Q-C target (DR-O15) before any toolkit build. COA B is an evidence-generating experiment, not a commitment: the toolkit comparison must use the same screens (shell, Create workspace, an N-thousand-item gallery, media inspection, 1280×680 behaviour) and score layout robustness, gallery behaviour, perceived quality and effort, not accessibility alone. The environment is ready; the missing pieces are the target definition, the module/licence review and an explicit go (DR-O12). Do not design COA C yet.
