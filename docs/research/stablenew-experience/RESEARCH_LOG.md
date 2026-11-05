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

10. **Owner answers recorded** as DR-A8..A21 (accepted) with open follow-ups DR-O5b, O6b, O11–O15. Notably: no assistive-tech/scaling requirement *but the owner rejects "therefore no Qt"* (the G0 gate and one stop criterion were withdrawn); the 833 branch is under review and will be published separately; "preparing" job state accepted; model-assisted planning wanted before qualification finishes (conflicts with repository qualification holds, DR-O11); approval offers *Preview* or *Preview and queue immediately*; telemetry local with 90-day retention; the owner is the only test participant; the declared minimum may be raised; T1–T9 approved; sub-agent review authorized.
11. **`layout-recommendation.md` received.** Folded in as EV-27/EV-38 and DR-P10..P12. It is assistant-authored (PR-831 session), not an owner statement.
12. **Chrome discrepancy resolved by pixel measurement (B1, EV-14).** Global chrome ≈36% (≈164 px top + ≈97 px bottom of 719); Learning's tab-level overhead pushes the review pane to y≈447 (≈62% down; pane ≈170 px). The earlier "≈36% by eye" and the recommendation's "≈460 px" were both right for different scopes; the 460 px still holds after PR-831.
13. **PySide6 present.** `C:\Users\rob\qual\gui-port740-env` has PySide6 6.12.0 and Pillow 12.3.0 (EV-39). Nothing was installed or executed from it except the existing Pillow used for the pixel profile.
14. **B2 deferred, deliberately.** A full PR gate (`run_pr_gate.py --full` with sharded pytest workers) was running in the `StableNew-main` checkout when B2 would have started. The Windows driver uses `SendInput` on the live desktop and could corrupt that gate's GUI tests (and be corrupted by them), so B2 waits until no gate/pytest/journey process is running. No baseline numbers are claimed.

15. **Independent review (sub-agent, read-only) completed and applied.** It verified the counts, Qt numbers, archive hashes and the pixel figures, and found no wording that claims user testing. Fixes applied: chrome figures restated on client height (≈33%, not ≈36% of the 719 px capture) and Learning/Review screenshot origin (local 833 branch) disclosed; line-count bases for 54k/65.7k/68.8k labelled as not comparable; Qt table retitled so no cell reads as an operator outcome; DPI wording corrected (an app configuration choice, not a Tk limit); 742's and QT-001's own conclusions and the departure from them stated; a Tk-only layout-first arm (COA A0) and top risks added; decision-register entries marked where the research, not the owner, supplied content; the two authority conflicts (DR-A11 against `AI_ASSIST`/`STATUS` holds; DR-A13(b) against "frozen plan shown first") written down as open (DR-O11, DR-O6b). Not verified by the reviewer: the owner's chat answers, the supplied layout file, the B1 script.

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
