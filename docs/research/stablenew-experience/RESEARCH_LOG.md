# Research log

Compact, dated discovery outcomes — not a commit or PR narrative.

## Session identity

| Item | Value |
|---|---|
| Package | PR-GUI-UX-850 (research and documentation only) |
| Task start | 2026-11-05T10:12:27-05:00 (`2026-11-05T15:12:27Z`, first logged message) |
| Primary session | `claude:85f4f8c8-3cc0-424a-85fa-2b755a7eb8c1` (Claude Code, fresh top-level session, configured model Sonnet 5.5) |
| Other sessions | one read-only review sub-agent (owner-authorized, DR-A20), spawned after commit `6f8de9b2`; nothing else |
| Host | Local Windows desktop |
| Worktree / branch | `StableNew.worktrees/research-gui-ux-850` · `research/gui-ux-850-experience-redesign` · base `origin/main` `ed1e989f2149b01d16aef26d5f880326aeb250e0` |
| Usage | measured with `tools/usage_report.py` at closeout over the full session window; reported in the completion line (not embedded here, to avoid a self-referential figure) |

## 2026-11-05 — discovery outcomes

1. **Source lock drift.** `origin/main` moved from the brief's `d76d1acd` to `ed1e989f` (PR #253, QUAL-SYSTEM-840); no GUI change (EV-28).
2. **Missing source.** `layout-recommendation.md` is not on disk or in Git history; brief §5 used as its proxy (EV-27, DR-O9). *Since resolved: see item 11.*
3. **PR-831 verified, not assumed.** Findings registry plus sealed archives show GP830-F1, F2, F3, F4, F7, F8 and I1 repaired; F5 WONTFIX as a harness assumption. Screenshot of the earlier failure (A-830m) and passing archive (A-831m) confirm LRN-01 at 1280×680 (EV-01..06). These are **not** current debt.
4. **PR-832 defects remain open on `main`**: GP832-F1..F4 UNREPAIRED (EV-07..EV-10); classified Product ×4, plus Infra (Blender), Test gap ×2 (resource-preflight, Extend Canvas) (EV-11..13).
5. **Unpublished PR-833 evidence found** on a local branch (not on `origin/main`): repairs F1–F4, adds GP833-F1/O1..O4 and sealed `d8e3e9d0` archives (normal/minimum/maximized all PASS across six advanced journeys). Treated as local evidence pending DR-O2. *Since answered: under owner review, to be published as its own PR (DR-A9).*
6. **Audit partially superseded.** The 2026-10-22 audit's rows for Saved Recipes, Pack Selector, img2img prominence and Output settings describe a UI replaced by UX-500/520/530 (EV-20). Re-verify each in the live app before using it as scope.
7. **Chrome budget, by eye.** At 1280×680 the retained screenshots show header + nav + guidance ≈ 165 px and the Operator Log/Status zone ≈ 95 px of 719 (≈36%). Needs pixel measurement (EV-14).
8. **Qt evidence reframed.** Three questions (Q-A dispatcher, Q-B performance, Q-C target experience); only Q-A and Q-B have data, both negative on operator-visible performance; Q-C is unmeasured (QT_VS_TK_COAS §1).
9. **Tk-bound surface recount**: 140 `src` files import tkinter (≈68.8k whole-file lines); 165 test files mention it (EV-33).

## 2026-11-05 — owner review round (after the first local commit `df89b877`)

10. **Owner answers recorded** as DR-A8..A21 (accepted) with open follow-ups DR-O5b, O6b, O11–O15 (all since answered in the second response, item 16). Notably: no assistive-tech/scaling requirement *but the owner rejects "therefore no Qt"* (the G0 gate and one stop criterion were withdrawn); the 833 branch is under review and will be published separately; "preparing" job state accepted; model-assisted planning wanted before qualification finishes (conflicts with repository qualification holds, DR-O11); approval offers *Preview* or *Preview and queue immediately*; telemetry local with 90-day retention; the owner is the only test participant; the declared minimum may be raised; T1–T9 approved; sub-agent review authorized.
11. **`layout-recommendation.md` received.** Folded in as EV-27/EV-38 and DR-P10..P12. It is assistant-authored (PR-831 session), not an owner statement.
12. **Chrome discrepancy resolved by pixel measurement (B1, EV-14).** Global chrome ≈36% (≈164 px top + ≈97 px bottom of 719); Learning's tab-level overhead pushes the review pane to y≈447 (≈62% down; pane ≈170 px). The earlier "≈36% by eye" and the recommendation's "≈460 px" were both right for different scopes; the 460 px still holds after PR-831.
13. **PySide6 present.** `C:\Users\rob\qual\gui-port740-env` has PySide6 6.12.0 and Pillow 12.3.0 (EV-39). Nothing was installed or executed from it except the existing Pillow used for the pixel profile.
14. **B2 deferred, deliberately.** A full PR gate (`run_pr_gate.py --full` with sharded pytest workers) was running in the `StableNew-main` checkout when B2 would have started. The Windows driver uses `SendInput` on the live desktop and could corrupt that gate's GUI tests (and be corrupted by them), so B2 waits until no gate/pytest/journey process is running. No baseline numbers are claimed.

15. **Independent review (sub-agent, read-only) completed and applied.** It verified the counts, Qt numbers, archive hashes and the pixel figures, and found no wording that claims user testing. Fixes applied: chrome figures restated on client height (≈33%, not ≈36% of the 719 px capture) and Learning/Review screenshot origin (local 833 branch) disclosed; line-count bases for 54k/65.7k/68.8k labelled as not comparable; Qt table retitled so no cell reads as an operator outcome; DPI wording corrected (an app configuration choice, not a Tk limit); 742's and QT-001's own conclusions and the departure from them stated; a Tk-only layout-first arm (COA A0) and top risks added; decision-register entries marked where the research, not the owner, supplied content; the two authority conflicts (DR-A11 against `AI_ASSIST`/`STATUS` holds; DR-A13(b) against "frozen plan shown first") written down as open (DR-O11, DR-O6b). Not verified by the reviewer: the owner's chat answers, the supplied layout file, the B1 script.

16. **Second owner response recorded** (DR-A22..A31): foundation provisionally accepted, comparative qualification open; research telemetry approved (opt-in, local, content-free); "queue immediately" defined as Confirm & Queue after a mandatory visible preview for confirmed Tier-2 plans; amendment text to be prepared but not activated; comparative COA A0 vs COA B to be *proposed* (not built) after the B2-B5 baseline and the Qt licensing/module/packaging assessment; minimum height by measurement (680 baseline, 760 comparison, 100/125/150%); layout backlog P1-P5 and P7 selected (not authorized); B2 held for explicit authorization and an exclusive desktop, B4 for separate approval with a restoration procedure.
17. **Drafts produced** (documentation only): `PROPOSED_AI_ASSIST_AMENDMENT.md`, `QT_PACKAGING_ASSESSMENT.md` (partial), `COMPARATIVE_PACKAGE_PROPOSAL.md`. Nothing in `AI_ASSIST.md`, `STATUS.md`, `config/`, `src/` or tests changed.
18. **Learning layout confirmed on a `main`-ancestor archive.** The PR-831 minimum archive `a18c7403` (an ancestor of `origin/main`) screenshot `LRN-01_2_after_reopen.png` has the same row boundaries as the 833 screenshot (pane at y 448-616, Operator Log/Status from y 622), so the Learning chrome figures no longer depend on the unmerged 833 branch. The Review/IMG-03 body (EV-14), the wheel-capture finding (EV-16) and the below-the-fold actions (EV-17) still do.
19. **Qt environment audited read-only** (`QT_PACKAGING_ASSESSMENT.md`): full wheel set 647 MiB, Widgets-only core about 58 MiB (about 38 MiB without software OpenGL) against about 8.8 MiB for the Tk 9.0 runtime of Python 3.14.9; the 740/742 proofs imported only QtCore, QtGui and QtWidgets. License metadata is `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` plus a commercial option. Nothing was installed or built.
20. **Draft decision on the AI amendment** (`PROPOSED_AI_ASSIST_AMENDMENT.md`): ten edit points listed (R1-R10); only invariant 2 widens semantically; the import ratchet and D10 are unchanged. A statement in the first draft that the ratchet baseline mismatched between docs and tests was wrong and was removed before commit (the test's `1` values count synthetic violations).
21. **B2 still not run.** A full PR gate was running in the `StableNew-main` checkout at the latest check, and the owner has made B2 a separate explicit authorization (DR-A30).

22. **Round-3 owner response recorded** (DR-A32..A38): milestone provisionally accepted; B2/B3/B5 approved conditionally as one session (owner must confirm the desktop is free; B4 not approved); Create Image directions recorded as product intent; AI amendment direction recorded, D-1 to D-5 not adjudicated and no widening authorized; LGPL-3.0 provisional route for QtCore/QtGui/QtWidgets; experimental isolated DPI awareness for COA A0; session to close after the decision documentation.
23. **Create Image intent checked against the repository** (EV-40, `workflows/create-image.md`): model profiles are implemented and merged on `main` (PR-IMG-PROFILE-630 #208, PR-LEARN-PROFILE-660 #213); a profile's recommended settings replace the working values on checkpoint selection, and no mechanism preserving a manual edit to such a setting was found (source reading, not run); there is no pin/promote mechanism; the name "Hybrid Create Image" is absent from the repository.
24. **Decision handoff and next-session contract written** (`DECISION_HANDOFF.md`, `NEXT_SESSION_B2_B3_B5_CONTRACT.md`). The contract is based on the harness's own isolation (disposable workspace, real-data and Git-tree guards) and names no run in this session. **B2, B3, B5 were not run here:** the owner's preconditions require the owner's confirmation of an exclusive desktop and the session boundary assigns them to the next session.
25. **Strict Qt set re-measured:** QtCore + QtGui + QtWidgets with the Windows platform plugin is about 38.9 MiB on disk (the earlier 58.2 MiB figure included Qt Svg and software OpenGL, both outside the owner-approved set).

## Final-acceptance report status (DR-A31)

| # | Required report item | Status |
|---|---|---|
| 1 | B2-B5 measurements with unavailable ones identified | **B1 partly measured** (chrome rows for four minimum-size screenshots, EV-14). **B2, B3, B4, B5 not run** (B2, B3 and B5 approved conditionally in round 3, DR-A33, for the next session; B4 not approved). Unavailable: current-UI task action/navigation/lost-click counts on `main`; wheel-capture probe on `main`; real 125%/150% runs at 680 and 760; large-history load (N = 500, 5,000, 50,000); installer size, cold start and memory of a product-like Qt shell; any operator task timing |
| 2 | Layout conclusions depending on unmerged PR-833 screenshots | **Depend on 833:** Review/IMG-03 body and the below-the-fold actions (EV-14 partly, EV-17), wheel capture (EV-16), disclosure finding (EV-19), and the repairs of EV-07..EV-10. **Verified against `main`-ancestor evidence:** global chrome rows (IMG-01, VID-01) and the Learning pane position (LRN-01) |
| 3 | Comparable Tk-vs-Qt operator outcomes, assumptions separated | **None exist.** Ledger in `COMPARATIVE_PACKAGE_PROPOSAL.md` section 7 (measured Tk-only, measured prior synthetic, assumed, unmeasured) |
| 4 | Bounded investigation of the >3x output-token variance | See below |
| 5 | Exact final branch/SHA, scope and validation | Reported in the closeout message (a SHA written inside the commit it describes would be self-referential); validation results recorded below |

### Token variance investigation (bounded; measured with `tools/usage_report.py` for session `claude:85f4f8c8-3cc0-424a-85fa-2b755a7eb8c1`, window from 2026-11-05T10:12:27-05:00)

- **Expected** (brief): about 8M cache read, about 40k output.
- **Coverage of the sub-agent:** measurable and **included**. The tool counts the sub-agent's transcript (it carries the parent `sessionId`): isolated, the one review sub-agent is 26 responses, 3.7M cache read, 22.6k output; the main-session file alone was 77 responses, 15.9M cache read, 124.7k output at that moment, and the two sum to the session total exactly.
- **By phase** (commit boundaries): original brief up to `df89b877` 34 responses, 7.4M cache read, 65.1k output (0.9x and 1.6x of expected, **within** the threshold); owner-review round to `1a015fd4` 60 responses (including the sub-agent), 10.1M, 71.0k; second-response round after `1a015fd4`, 30 responses at the time of writing, 7.9M, 46.6k. Session total at that time: 123 responses, 25.1M cache read, 182.3k output (3.1x and 4.6x of expected).
- **Cause:** the variance is the sum of **owner-requested additional rounds** after the brief that the estimate did not cover (review round, sub-agent review, amendment/assessment/proposal drafting). The largest single responses (13.3k, 7.0k and 5.7k output tokens) fall in the first phase's writing stretch (15:19-15:23Z), consistent with large document writes, though tool names were not captured in this check; nothing indicates a retry loop, a failed-tool storm or a repair pass (0 repair passes). Cache read tracks context length: responses average roughly 190k tokens of re-read context, so cache read scales with the number of responses rather than with new work.
- **Not established:** a counterfactual cost of the extra rounds if they had been run in fresh sessions (context would have been smaller, so cache read lower); host logs do not give per-tool-call attribution.

## Validation record (docs only)

| Check | Result |
|---|---|
| Link/local-path check over `docs/research/stablenew-experience/` (48 refs, 0 problems at `6f8de9b2`) | pass (script kept outside the repository) |
| `git diff --check` | clean |
| Cheap CI classification (`tools/ci/validation_plan.py`) | docs-only expected; confirmed at closeout |
| GPU/GUI journey suite | **not run** by design |
| User testing | **none performed** |

## Not done (explicitly)

No per-workflow owner discovery, no live-app walk-through, no prototype, no PySide6 install (an existing environment was found), no model/GPU execution, no baseline run (B2–B5), no push or PR.
