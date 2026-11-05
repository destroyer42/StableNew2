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
| Chrome ratio | Fixed non-workspace height ÷ window height at 1280×680 | pixel script (EV-14); denominator is client height (680 px), not the 719 px captured window |
| Error comprehension | Participant states cause and next action from the error text, unaided | new (protocol) |
| Perceived quality | Rating on a fixed scale after the task | new |
| Responsiveness | Interaction latencies (filter, select, refresh) | 742/743 harness |
| Large-list behavior | Scroll/filter time and memory at N = 500, 5k, 50k items | new |
| Accessibility | UIA elements named/focusable; keyboard completion of each task | 742 UIA probe |
| Safety | Wrong-job associations, unexpected queue submissions, invalid artifacts | comparator fields |

## 3. Baseline plan (before any prototype)

**Status 2026-11-05 (updated after the owner's second response, DR-A30):** B2 and B4 are **not yet authorized to run**: B2 needs the owner's explicit authorization *and* exclusive use of the interactive desktop (no gate, pytest or other driver is sufficient evidence of availability); B4 needs separate approval immediately before execution with a documented restoration procedure for the display scale. B1 is partly done. B3 (wheel probe) and B5 also drive or load the application and are held with B2 until the owner authorizes the desktop. (Earlier text: B1–B5 re-authorized by the owner, DR-A18, now narrowed by DR-A30.) B1 done for four retained minimum-size screenshots (EV-14: global chrome ≈36%, Learning review pane ≈62% below the fold); the other sizes and tabs remain. B2–B5 pending: B2 is a Windows desktop `SendInput` run, so it must not overlap another desktop-driving run or a full PR gate on the same machine (a gate was running in the `StableNew-main` checkout when this was written). The harness does not drive the GPU; fakes only. **B4 (real 125%/150% display scale) changes the Windows display setting**, which GUI-COMPLETE-760 treated as out of scope and which would disturb the owner's open applications; the owner's general B1–B5 authorization is taken to cover it only once the owner confirms the moment, so B4 is asked again immediately before it runs.

B1: Pixel-measure chrome ratio on retained and fresh screenshots at the five target sizes. B2: Re-run IMG-01/02/03, VID-01/02/03, LRN-01/02, OPS-01 with the Windows driver on `origin/main` and archive sealed runs with `--archive`; record action counts and navigation counts as the **current-UI baseline**. B3: Wheel-capture probe on `main` (EV-16). B4: Real 125%/150% display scale runs (the 760 gap). B5: Large-history load (N rows in a temporary repository). **Local host only; B2 uses fakes, not the GPU.**

## 4. Task scripts (**approved by the owner 2026-11-05, DR-A21**)

| ID | Script (start state → success) |
|---|---|
| T1 | New pack → text → queue 4 images → open the first result |
| T2 | Switch model and explain the effective settings aloud |
| T3 | Open a past image → mask a region → queue → see it beside its parent |
| T4 | Card sort of the verbs the app offers (inventory them first; the count is not yet established) into groups; first-click test for "make this image move", "find last week's best", "compare two models" |
| T5 | Image → clip → play it → add to a movie |
| T6 | Three-shot Storyboard → queue → resume after interruption |
| T7 | Rate results and decide which setting to keep |
| T8 | Backend not running: recover and finish T1 |
| T9 | Checkpoint changed under you: say why the job failed |

Each script has a timer, stop point, allowed help policy and recorded errors. T8/T9 use the existing OPS-01 fault seams.

## 5. Before/after methodology

Same scripts, same fixtures, same display and driver, sealed archives, comparator output (improved/unchanged/degraded/inconclusive). Operator studies: **the only participant is the owner (DR-A14).** Every usability result is therefore n = 1 operator and must say so. Replace "≥ 5 participants" with ≥ 5 repeated sessions per arm, spaced and counterbalanced (randomize arm order, vary task variants) because an expert who has seen task T1 on one arm will do better on the next; report medians and ranges, never single-run deltas, and report any practice effect observed. Nothing here supports a claim about operators other than the owner, and the owner is also the designer, so first-click and card-sort results (T4) carry expert bias; treat them as hypotheses about the owner's own mental model, which is the stated target. A prototype is judged on the same scripts as the current UI and as each other COA; the prototype must declare its fake data and exclude real backends.

## 6. Evidence retention

Outside Git under `~\StableNewAcceptance\` (sealed `COMPLETE`/`MANIFEST.json`); text redacted of home paths; screenshots reviewed before sharing (an edge or overlapping window can leak desktop pixels, per Testing §11a). Research docs cite archive names and manifest hash prefixes, never embed screenshots.

## 7. Prototype comparison protocol (COA A vs B)

Same IA, same synthetic data (reuse the 742 fixture digest approach), same scripts, both built in isolated child processes; record effort (hours and lines) for each build alongside outcomes; randomize which toolkit is built first or disclose the asymmetry.

## 8. Stop criteria

Stop and report if: a prototype requires a production controller or runner; real GPU/model use would be needed; the matched Tk build meets targets (stop COA B); any measurement requires touching the operator's running application; licensing blocks Qt; owner discovery contradicts the IA hypothesis (revise before measuring).

## 9. Docs-only validation for this PR

Link and local-path check over this directory, `git diff --check`, the repository's documentation rules and the cheap docs path in `tools/ci/validation_plan.py`; **no GPU/GUI journey suite** (Testing §11a). Results are recorded in RESEARCH_LOG.

## 10. Research telemetry (owner-approved scope, DR-A23; **no implementation here**)

**Approved by the owner on 2026-11-05:** opt-in, local-only usability telemetry for **research and prototype evaluation**. It is a separate thing from existing operational diagnostics and from the AI improvement-monitoring requirements in `AI_GUIDED_EXPERIENCE.md` §6 (which stay PROPOSED).

| Aspect | Rule |
|---|---|
| Consent | Off by default; the participant enables it; a visible indicator while on |
| Scope | Research sessions and the comparative prototypes only; **not** enabled in normal operation unless the owner later says so |
| Fields captured | task completion time; navigation paths; backtracking; failed interactions; control visibility and clipping; scroll use; window dimensions; DPI scaling; queue-submission outcomes (against the prototype's fake JobService); basic-versus-advanced control usage |
| Never captured | prompt text, generated images, filesystem paths, personal identifiers, model contents; no hashes of user content |
| Transmission | None. Never sent externally; no network call in the telemetry path |
| Participant control | The participant can inspect and delete all collected research data at any time (real deletion) |
| Retention | Local, **90 days** (DR-A12) |
| Separation | A separate store and code path from operational diagnostics (`events.jsonl`, operator log, crash bundles, journey evidence); it has no queue, history or runtime authority and cannot change behavior |
| Interaction with other holds | Research's proposal (not stated by the owner): disabled during any physical qualification run. This research has not built it |

How it differs from existing operational diagnostics: diagnostics record *what the application did* for support and qualification (codes, counts, stack/error text, owned-process evidence) and are always on; research telemetry records *how the participant used the interface* to answer design questions, is opt-in, and exists only in research sessions. The golden-path comparator (`extra_interaction_count`, `lost_clicks`, `click_retries`) remains the offline substitute and is exhausted first.

## 11. Viewport and scale matrix (owner, DR-A27)

Primary cells: **1280×680** (existing compatibility baseline) and **1280×760** (additional comparison viewport, **not** an adopted minimum), each at real **100%, 125% and 150%** display scaling (6 cells). Secondary sizes (1366×768, 1920×1080, 2560×1440) are optional. The aim is controls reachable and workflows usable through responsive layout, scrolling and progressive disclosure, not a larger required monitor; the minimum height is **determined by measurement** and no value is adopted yet.
