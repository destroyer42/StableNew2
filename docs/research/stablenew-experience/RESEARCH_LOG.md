# Research log

Compact, dated discovery outcomes — not a commit or PR narrative.

## Session identity

| Item | Value |
|---|---|
| Package | PR-GUI-UX-850 (research and documentation only) |
| Task start | 2026-11-05T10:12:27-05:00 (`2026-11-05T15:12:27Z`, first logged message) |
| Primary session | `claude:85f4f8c8-3cc0-424a-85fa-2b755a7eb8c1` (Claude Code, fresh top-level session, configured model Sonnet 5.5) |
| Other sessions | none (no subagents spawned) |
| Host | Local Windows desktop |
| Worktree / branch | `StableNew.worktrees/research-gui-ux-850` · `research/gui-ux-850-experience-redesign` · base `origin/main` `ed1e989f2149b01d16aef26d5f880326aeb250e0` |
| Usage | measured with `tools/usage_report.py` at closeout over the full session window; reported in the completion line (not embedded here, to avoid a self-referential figure) |

## 2026-11-05 — discovery outcomes

1. **Source lock drift.** `origin/main` moved from the brief's `d76d1acd` to `ed1e989f` (PR #253, QUAL-SYSTEM-840); no GUI change (EV-28).
2. **Missing source.** `layout-recommendation.md` is not on disk or in Git history; brief §5 used as its proxy (EV-27, DR-O9).
3. **PR-831 verified, not assumed.** Findings registry plus sealed archives show GP830-F1, F2, F3, F4, F7, F8 and I1 repaired; F5 WONTFIX as a harness assumption. Screenshot of the earlier failure (A-830m) and passing archive (A-831m) confirm LRN-01 at 1280×680 (EV-01..06). These are **not** current debt.
4. **PR-832 defects remain open on `main`**: GP832-F1..F4 UNREPAIRED (EV-07..EV-10); classified Product ×4, plus Infra (Blender), Test gap ×2 (resource-preflight, Extend Canvas) (EV-11..13).
5. **Unpublished PR-833 evidence found** on a local branch (not on `origin/main`): repairs F1–F4, adds GP833-F1/O1..O4 and sealed `d8e3e9d0` archives (normal/minimum/maximized all PASS across six advanced journeys). Treated as local evidence pending DR-O2.
6. **Audit partially superseded.** The 2026-10-22 audit's rows for Saved Recipes, Pack Selector, img2img prominence and Output settings describe a UI replaced by UX-500/520/530 (EV-20). Re-verify each in the live app before using it as scope.
7. **Chrome budget, by eye.** At 1280×680 the retained screenshots show header + nav + guidance ≈ 165 px and the Operator Log/Status zone ≈ 95 px of 719 (≈36%). Needs pixel measurement (EV-14).
8. **Qt evidence reframed.** Three questions (Q-A dispatcher, Q-B performance, Q-C target experience); only Q-A and Q-B have data, both negative on operator-visible performance; Q-C is unmeasured (QT_VS_TK_COAS §1).
9. **Tk-bound surface recount**: 140 `src` files import tkinter (≈68.8k whole-file lines); 165 test files mention it (EV-33).

## Validation record (docs only)

| Check | Result |
|---|---|
| Link/local-path check over `docs/research/stablenew-experience/` (46+ refs) | see completion report (script kept outside the repository) |
| `git diff --check` | clean |
| Cheap CI classification (`tools/ci/validation_plan.py`) | docs-only expected; confirmed at closeout |
| GPU/GUI journey suite | **not run** by design |
| User testing | **none performed** |

## Not done (explicitly)

No owner interview, no live-app walk-through, no prototype, no PySide6 install, no model/GPU execution, no push or PR.
