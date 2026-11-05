# Evidence register

Every finding: ID, exact source, SHA/evidence location, observed behavior, severity, confidence, unresolved question, falsification test. Severity is the source's own where one exists (the findings registry), otherwise this research's judgment marked `(R)`. Confidence: **High** = sealed archive or source verified; **Med** = single document or screenshot; **Low** = inference.

Archive shorthand: `A-830n/830m` = `4adaa1fa` normal `…2afd4b` / minimum `…15aef5`; `A-831n/831m/831x` = `a18c7403` normal `…78bb76` / minimum `…f052d4` / maximized `…a550d7`; `A-833n/833m/833x` = `d8e3e9d0` normal `…5da5c5` / minimum `…afbcab` / maximized `…00abdb` (**local branch only**). All under `~\StableNewAcceptance\golden-paths\`; the first 16 hex of each `MANIFEST.json` SHA-256 are given where an archive is cited. Findings registry = `tools/operator_journey/golden/findings.v1.json` at `ed1e989f` (GP830-*, GP832-*) unless noted.

## A. Provenance and scope facts

| ID | Fact | Source / location | Conf |
|---|---|---|---|
| EV-27 | `layout-recommendation.md` not located. Brief §5 is the only rendering of its findings available. | filesystem search 2026-11-05; `git log --all` for the filename empty | High (absence) |
| EV-28 | `origin/main` advanced `d76d1acd` → `ed1e989f`; only PR #253 (`4fe62fa6`, QUAL-SYSTEM-840) intervenes. Ledger `built_from.main_sha` is `d76d1acd`. | `git log d76d1acd..HEAD`; `tools/qualification/system840/ledger.v1.json` | High |
| EV-29 | All retained screenshots are from the loopback fixture on one 2560×1440 monitor at 100%, 96 DPI. | `evidence.json` `display` of A-831/A-833 | High |
| EV-30 | Shell today: nine stable tabs presented as five groups: Create (Prompt, Pipeline), Edit (Review, Photo Optimize), Motion (Video Workflow, SVD Img2Vid, Movie Clips), Learn (Learning), Advanced (Character Training, HOLD). Job History is inside Pipeline. | `src/gui/view_contracts/task_navigation_contract.py` [V] | High |
| EV-31 | Journey coverage: 27 workflows = 6 full desktop journeys, 6 partial, 14 integration-only, 1 untested (any physical GPU path). | `coverage_matrix.v1.json` v1.1.0 [V] | High |

## B. Layout and reachability

| ID | Finding | Evidence | Observed | Sev | Conf | Unresolved / falsify |
|---|---|---|---|---|---|---|
| EV-01 | Learning Rate step collapsed the 1–5 Rating box (GP830-F1). **REPAIRED in PR-831.** | A-830n `be5c6c3f8e57c831` LRN-01 BLOCKED → A-831n `918b3573aa119af1` PASS, reachability DIRECT. Tests `test_learning_review_pane_reachability_831.py`. Comparison `pr831_vs_pr830_normal`. | Blocked → direct; workaround count 8 → 0 (comparison marks the count inconclusive because the earlier run stopped early) | blocking (was) | High | Only normal/min/max layouts at 2560×1440 were run. Falsify: LRN-01 at another real DPI/height. |
| EV-02 | At the 1280×680 minimum the Learning Images list sat behind the Operator Log (GP830-F7). **REPAIRED in PR-831.** | A-830m `af9f92afd67987a0` screenshot `LRN-01_1_failure.png` (sha256 `91a124d7b47e2358…`) shows the "Images" header clipped at the log; A-831m `008606ff3c5f1889` PASS. | Fixed by making the review side columns one scrolling body above a fixed Save strip. | major (was) | High | Reachable ≠ comfortable: the list is reached by scrolling, not visible at once (EV-14). |
| EV-03 | Focus-reveal scrolled a control between press and release, losing clicks (GP830-F2, 3–8 releases per journey). **REPAIRED in PR-831.** | Findings registry; test `test_pointer_focus_no_scroll_831.py`; `pr831_vs_pr830_*` comparisons. | Click retries gone in A-831. | major (was) | High | Applies to pointer focus only; Tab/programmatic focus still reveals (by design). |
| EV-04 | Shutdown and lifecycle: LoRA scan 10 s stall (F3), tooltip re-entry crash (F4), stale `after` callbacks (F8). **REPAIRED in PR-831.** | Findings registry; tests `test_thread_registry_shutdown_listener_831.py`, `test_tooltip_helper_v2.py`, `test_stale_after_callbacks_831.py`. | Not GUI-layout issues; recorded to prevent mis-classifying them as design debt. | major/minor | High | Tooltip crash was "not reliably reproducible"; absence is not proof. |
| EV-05 | GP830-F5 (requested geometry not honored) is **WONTFIX**: a harness assumption, not an operator defect. | Findings registry `repair.classification`. | — | minor | High | — |
| EV-06 | GP830-I1 inherited `MediaInspector._current_path` test failure **REPAIRED** (test used a private attribute). | Findings registry. | Test debt, not product debt. | major (was) | High | — |
| EV-14 | At the 1280×680 minimum, fixed chrome consumes about a third of the window. Measured **by eye** from `IMG-03_1_review.png` (A-833m, sha256 `c8225511409bd94f…`, 1296×719 incl. frame): title bar, command row (Run/Stop/Preview/Settings/Refresh/Help/Debug/Readiness), group nav, "About This Tab", then ≈460 px of tab content, then Operator Log + Status ≈95 px. | A-833m screenshot; also `LRN-01_1_failure.png` in A-830m. | Header + nav + guidance ≈165 px and bottom zone ≈95 px of 719 px ≈ 36%. | (R) major at small windows | Med | Not pixel-measured. Falsify: script row boundaries on the screenshots; repeat on all layouts. |
| EV-16 | The Review preview canvas and the Motion Library tree capture the mouse wheel (GP833-O2). | **Local branch only** (`b986c33c` findings registry); A-833m. | List filling the 262 px viewport takes the wheel; page scrollbar still works. | minor (registry) | Med | Matches brief §5 "nested panes consume wheel input"; on `origin/main` this is **not registered** — a gap, not an absence of the problem. Falsify: wheel probe on `main`. |
| EV-17 | Review "Edit Mask" and "Extend Canvas" start below the fold at the minimum window (GP833-O3). | Local branch registry; A-833m `IMG-03_1_review.png` shows the actions area not visible. | Reachable by scroll; not initially visible. | minor | Med | GUI-COMPLETE-760 reports 0 *unreachable* controls; it does not measure *initially visible*. |
| EV-18 | GUI-COMPLETE-760 repaired 62 unreachable controls (Prompt 7, Pipeline 54, Review 1) to 0 across 8 windows × 4 tabs; **left** Review/Photo Optimize list taller than a 680 px client (degraded), Prompt text panes at simulated 150%, and real 125/150/175% DPI unrun. | `docs/assessments/2026-11-01_gui_complete_760_image_workflow_reachability.md`; `evidence/gui_complete_760/reachability_matrix.json` | Reachable at every qualified size by wheel and keyboard. | degraded residual | High | 150% is *simulated* Tk scaling; Motion/Learning/Character Training not probed by 760. |
| EV-19 | Controls inside collapsed disclosures are hidden until opened (GP833-O4, WONTFIX). | Local registry. | Journeys open disclosures "as an operator does". | minor | Med | Tension with brief §8 "required parameters visible before admission": whether any *required* parameter sits in a disclosure is **unknown** (see `workflows/create-image.md`). |
| EV-20 | The 2026-10-22 audit's per-tab findings are partly stale: PR-GUI-UX-500/520/530 shipped the Pipeline composer, config-source wording and removal of "Preset/recipe" concepts. | Ownership map "Pipeline composer", "Pipeline settings sources" [V]; audit table [D]. | Several audit rows (Saved Recipes, Pack Selector wording, img2img prominence) describe a superseded UI. | — | High | Each audit row must be re-verified in the live app before it becomes redesign scope. |

## C. Interaction, discoverability and state

| ID | Finding | Evidence | Observed | Sev | Conf | Unresolved / falsify |
|---|---|---|---|---|---|---|
| EV-15 | Multiple entry points reach the same outcome. *Make Video* is offered on Review, Job History and Pipeline preview; *edit an existing image* via Review, History "Edit Image in Review", History "Regenerate with Changes", Photo Optimize "Quick Edit" and Learning "Staged Curation → Review"; two "Show Guidance" buttons are visible together on Review. | `STATUS.md` image/video lines [V]; `PHOTO_REVIEW_REPROCESS.md` §3.5/§6.6 [D]; `IMG-03_1_review.png` (A-833m) [V] | Multiple valid doors; whether this confuses operators is **not measured**. | (R) minor–major | Med | Falsify: task-first usability test (VALIDATION §4); count distinct doors per outcome with a script over `task_navigation_contract` and handoff ports. |
| EV-21 | Settings scopes are named but distributed: PromptPack Settings, Saved Pack List, working settings + Current Job Overrides, Startup Defaults, Application Defaults, generation profile (No profile/Research/Learning/Custom). | Ownership map "Pipeline settings sources", "Generation profile strip" [V] | Six scopes named in one UI area; adequacy of explanation unmeasured. | (R) | Med | Brief §5 says scopes are "applied without adequate explanation" **[O]**. Verify against current wording with an operator. |
| EV-22 | Draft/Preview/queued/running/completed are shown in different places: Preview panel, Queue, Job History (inside Pipeline), Operator Log, header Run/Stop. The "preview thumbnail" never generates an image; "Show media" is separate from state. | Ownership map; audit row Pipeline/Preview [V/D] | State progression is reconstructable but spread over several surfaces. | (R) | Med | Falsify: time-to-answer "what happened to the job I just queued?" |

## D. PR-832 journey defects and holds (independent classification)

Classification vocabulary: **GUI** (presentation), **Product** (behavior or data), **Infra** (prerequisite missing on the host), **Test gap**, **Policy** (intended behavior).

| ID | Finding | Registry state on `origin/main` | Local 833 state | Class | Sev | Conf | Notes / falsify |
|---|---|---|---|---|---|---|---|
| EV-07 | **IMG-03:** masked edit from History records `parent_artifact_id` but `parent_job_id` is null, so Compare with Parent is disabled (GP832-F3). | UNREPAIRED | REPAIRED in `517868d3` (dialog gets source job id, bound to path, digest and embedded id); A-833n IMG-03 37/37 PASS | **Product (data/lineage)** — not cosmetic | major | High | Unmerged. Falsify: run IMG-03 on `main`; expect FAIL on `parent_job_recorded`. Do not fold into any layout work. |
| EV-08 | **OPS-01:** checkpoint changed before dispatch fails the job correctly but shows only a generic message; the cause is in the log (GP832-F1). | UNREPAIRED | REPAIRED in `ede26491` (bounded, path-free reason in the canonical error message) | **Product (error reporting)** | minor | High | The operator-visible reason is a recorded-message content problem; the presentation surfaces (queue/History row) already display recorded error text. |
| EV-09 | **OPS-01:** unreachable backend leaves a job `running` while the banner says WebUI jobs are held (GP832-F2). | UNREPAIRED | Diagnosed as a stale readiness snapshot beside a legitimately claimed RUNNING job; REPAIRED in `7bef424c`. New open **GP833-F1**: no "preparing" state for a claimed job (needs owner decision). | **Product (state projection)** | major | Med | Draft/queued/executing distinction is exactly what brief §5 calls hard to see. Owner decision pending (see DECISION_REGISTER DR-O3). |
| EV-10 | **VID-03:** Queue Sequence refused for a blank form-level motion prompt although every shot has one, message does not name the empty field (GP832-F4). | UNREPAIRED | REPAIRED in `a4954e33` (form check skipped for sequences) | **Product (validation)** + copy | minor | High | Note the repair changes *admission policy*, not only wording; confirm intent with owner before adopting. |
| EV-11 | **VID-02:** physical conversion untested: Blender absent on the host; lane is HOLD and never faked. | HOLD at conversion (`4dd86838`) | Gated on an explicit `--blender`/env path; HOLD otherwise | **Infra** + **Test gap** | n/a | High | Not a UI defect. Conversion quality unverified. |
| EV-12 | Resource-preflight refusal (low host RAM) not driven in any journey. | Coverage `operational-recovery-backend-faults` limits | Same | **Test gap** | n/a | High | Brief §5 "resource-preflight recovery". Needs a fake probe seam, not a GPU. |
| EV-13 | **Extend Canvas** not driven by IMG-03. | Coverage `history-iterate-masked-image-edit` | "its lineage is covered by a deterministic test" | **Test gap** | n/a | High | Same. |
| EV-32 | GP833-O1 Storyboard "Discard unsaved draft?" prompt after form-only prep: WONTFIX; the prompt is accurate. | — | WONTFIX | **Policy** | minor | Med | May be a design-system question (what counts as a draft), not a defect. |

## E. Toolkit and architecture evidence

| ID | Finding | Source | Conf |
|---|---|---|---|
| EV-23 | **GUI-QT-001** (2026-10-25): NO-GO/DEFER; no cited, measured operator problem required Qt; migration surface ≈54k Tk lines; lifecycle/shutdown are controller-level work. Source-and-documentary only; no Qt code run. | assessment §1, §2 | High |
| EV-24 | **GUI-PORT-740** (2026-10-30): isolated PySide6 6.12.0 proof PASS within synthetic scope; dispatcher, AppState, nine-tab navigation, shutdown semantics exercised with 16 contained children; CONDITIONAL GO for a *separately approved bounded package*. One real closure blocker: `ui_tokens → design_system_v2 → tkinter` (since addressed by `design_values`, GUI-SEAM-741). | assessment; `evidence/gui_port_740/` | High |
| EV-25 | **GUI-PORT-742** (2026-10-31): one read-only Job History workspace in Tk and Qt, n=5; startup +87 ms, +34 MiB idle, +79 MiB peak for Qt; filter −2.3 ms, selection −1.0 ms, refresh −18 ms; 96.7% of the 2,000-callback burst gap is dispatcher policy; **UI Automation: 104 of 110 Qt elements named vs 0 of 31 for Tk**; simulated-150% parity; NO-GO on migration "on current evidence". Real 125–175% DPI, multi-monitor and screen readers not tested. | assessment | High |
| EV-26 | **GUI-SEAM-743** (2026-10-31): Tk dispatcher tuning NO-GO: callbacks-per-pump cuts synthetic burst latency 66% but no candidate showed a demonstrated worker-refresh benefit (best +8%, ±~20% at n=5). Also: "does not translate into operator-visible latency". | assessment | High |
| EV-33 | Tk-bound surface at `ed1e989f`: 140 `src` files import `tkinter` (≈68.8k whole-file lines); 165 test files mention `tkinter`. (742 recorded 134 files/65.7k and 156.) | `git grep` this session | High |
| EV-34 | `AppController` still reaches widgets; Learning/Review controllers live under `src/gui/controllers/`; 742 §H4 and audit D1/D3 note this. A UI rebuild that is not preceded by presenter extraction inherits the coupling in either toolkit. | `PHOTO_REVIEW_REPROCESS.md` §7.1 [V/D]; QT-001 E4/E5 | Med |

## F. AI evidence

| ID | Finding | Source | Conf |
|---|---|---|---|
| EV-35 | Offline AI Assist: Prompt **Suggest…** exists but is disabled; nothing installed; every model NOT TESTED; qualification held on D12b and an ETW canary. A suggestion is text for an editing buffer; the AI package may not import queue/repository/runner/NJR (ratchet baseline 0). | `AI_ASSIST.md` §1, §2, §8, §11 [V]; `STATUS.md` Holds | High |
| EV-36 | Learning's *What Should I Test Next?* is a deterministic read-only projection (no AI call). A pattern for evidence-citing assistance that already exists. | `LEARNING.md` §3.16 [V] | High |
| EV-37 | Deterministic compatibility/readiness machinery exists to validate any AI-proposed plan: `ModelPolicy`, cross-workflow model compatibility preflight, whole-selection Review preflight, workflow readiness, frozen-plan admission gate (harness). | `STATUS.md`; `TESTING_AND_CI.md` §11a [V/D] | Med |

## Open evidence gaps (prioritized)

1. Operator task timing and error rates: none exist. (VALIDATION §3)
2. Locate or re-supply `layout-recommendation.md` (EV-27).
3. Real DPI, multi-monitor and assistive-technology behavior for either toolkit (EV-25, EV-29).
4. Pixel-measure the chrome budget (EV-14) and wheel-capture on `origin/main` (EV-16).
5. Decide the fate of the local 833 branch before treating EV-07..EV-10 as repaired.
