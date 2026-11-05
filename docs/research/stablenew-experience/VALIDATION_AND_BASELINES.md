# Validation, baselines and prototype tests

**Status: PROPOSED methodology.** No operator test has been run. This document defines how future claims become measurable.

## 1. Rules of evidence

1. A **source review is not user testing.** Only timed, observed task runs count as usability evidence. The 2026-10-22 audit's `[O]` items and the brief's section 5 are operator *reports*, not measurements.
2. Simulated-lane journeys (loopback backends) measure orchestration and reachability, **never** image/video quality or physical resource behavior. The harness itself states: a single run is never statistical evidence of a speed or quality change.
3. Simulated DPI ≠ a real display change; label every screenshot ("actual 100%", "simulated 150%").
4. Sealed archives are comparable only like-with-like (driver, layout, display, interpreter, harness); the comparator already refuses or marks inconclusive otherwise.

## 2. Acceptance metrics

| Metric | Definition | Existing source |
|---|---|---|
| Task success without intervention | Journey ends with the intended artifact/state, no moderator help | journey verdict + reachability (`DIRECT`/`WITH_WORKAROUNDS`/`BLOCKED`) |
| Interactions to useful outcome | Actions from start to first intended result | `action_count`, `extra_interaction_count` |
| Navigation overhead | Tab/group switches per task | new (count `select_tab` calls) |
| Lost/retried inputs | Clicks that missed or were retried | `lost_clicks`, `click_retries` |
| Forced scroll/resize | Moves needed to reach a control | `forced_scroll_or_resize` |
| Time to decision-ready | Time until the information needed for the next choice is on screen | new |
| Chrome ratio | Fixed non-workspace height ÷ window height at 1280×680 | new (pixel script; EV-14 is by eye) |
| Error comprehension | Participant states cause and next action from the error text, unaided | new (protocol) |
| Perceived quality | Rating on a fixed scale after the task | new |
| Responsiveness | Interaction latencies (filter, select, refresh) | 742/743 harness |
| Large-list behavior | Scroll/filter time and memory at N = 500, 5k, 50k items | new |
| Accessibility | UIA elements named/focusable; keyboard completion of each task | 742 UIA probe |
| Safety | Wrong-job associations, unexpected queue submissions, invalid artifacts | comparator fields |

## 3. Baseline plan (before any prototype)

B1: Pixel-measure chrome ratio on retained and fresh screenshots at the five target sizes. B2: Re-run IMG-01/02/03, VID-01/02/03, LRN-01/02, OPS-01 with the Windows driver on `origin/main` and archive sealed runs with `--archive`; record action counts and navigation counts as the **current-UI baseline**. B3: Wheel-capture probe on `main` (EV-16). B4: Real 125%/150% display scale runs (the 760 gap). B5: Large-history load (N rows in a temporary repository). **Local host only; B2 uses fakes, not the GPU.**

## 4. Task scripts (candidate; owner to approve wording)

| ID | Script (start state → success) |
|---|---|
| T1 | New pack → text → queue 4 images → open the first result |
| T2 | Switch model and explain the effective settings aloud |
| T3 | Open a past image → mask a region → queue → see it beside its parent |
| T4 | Card sort of the 40 verbs the app offers into groups; first-click test for "make this image move", "find last week's best", "compare two models" |
| T5 | Image → clip → play it → add to a movie |
| T6 | Three-shot Storyboard → queue → resume after interruption |
| T7 | Rate results and decide which setting to keep |
| T8 | Backend not running: recover and finish T1 |
| T9 | Checkpoint changed under you: say why the job failed |

Each script has a timer, stop point, allowed help policy and recorded errors. T8/T9 use the existing OPS-01 fault seams.

## 5. Before/after methodology

Same scripts, same fixtures, same display and driver, sealed archives, comparator output (improved/unchanged/degraded/inconclusive). Operator studies: ≥ 5 participants per arm for qualitative findings (this is a single-operator product, so owner sessions plus a small number of external testers is a **design choice for the owner**, DR-O7); report medians and ranges, never single-run deltas. A prototype is judged on the same scripts as the current UI and as each other COA; the prototype must declare its fake data and exclude real backends.

## 6. Evidence retention

Outside Git under `~\StableNewAcceptance\` (sealed `COMPLETE`/`MANIFEST.json`); text redacted of home paths; screenshots reviewed before sharing (an edge or overlapping window can leak desktop pixels, per Testing §11a). Research docs cite archive names and manifest hash prefixes, never embed screenshots.

## 7. Prototype comparison protocol (COA A vs B)

Same IA, same synthetic data (reuse the 742 fixture digest approach), same scripts, both built in isolated child processes; record effort (hours and lines) for each build alongside outcomes; randomize which toolkit is built first or disclose the asymmetry.

## 8. Stop criteria

Stop and report if: a prototype requires a production controller or runner; real GPU/model use would be needed; the matched Tk build meets targets (stop COA B); any measurement requires touching the operator's running application; licensing blocks Qt; owner discovery contradicts the IA hypothesis (revise before measuring).

## 9. Docs-only validation for this PR

Link and local-path check over this directory, `git diff --check`, the repository's documentation rules and the cheap docs path in `tools/ci/validation_plan.py`; **no GPU/GUI journey suite** (Testing §11a). Results are recorded in RESEARCH_LOG.
