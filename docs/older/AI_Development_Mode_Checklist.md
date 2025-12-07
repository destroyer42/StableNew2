FILE 2 — AI_Development_Mode_Checklist.md
# StableNew — Interactive AI Development Mode Checklist

Run this checklist **EVERY TIME** before beginning a PR or coding session.

---

# ✔ Step 1 — Confirm Snapshot

**Question:**  
Do you have the latest snapshot ZIP?

- ☐ Yes → proceed  
- ☐ No → run: `snapshot_and_inventory_generator.cmd`

---

# ✔ Step 2 — Confirm repo_inventory.json

Is `repo_inventory.json` up to date?

- ☐ Yes  
- ☐ No → regenerate  

---

# ✔ Step 3 — Identify Subsystem(s)

Choose exactly the subsystem(s) targeted by this PR:

- ☐ GUI  
- ☐ Controller  
- ☐ Pipeline  
- ☐ API  
- ☐ Learning system  
- ☐ Resource discovery  
- ☐ Layout/Theming  
- ☐ Tests  
- ☐ Other (must justify)

---

# ✔ Step 4 — Lock Down Forbidden Files

PR **may NOT modify**:

- executor.py  
- main_window_v2.py  
- theme_v2.py  
- main.py  
- pipeline_runner.py  
- anything under /src/api  
- anything under /archive  

If needed, you must explicitly request a temporary unlock.

---

# ✔ Step 5 — Identify Approved Files

List *only* the files the AI is allowed to touch:


<Insert explicit file list here> ```

No other files may be altered.

✔ Step 6 — Define PR Goal in ONE Sentence

Examples:

“Wire model dropdown to discovery service and propagate selection to payload.”

“Fix AppController zone wiring and eliminate AttributeError on startup.”

If your PR goal is more than one sentence → split into multiple PRs.

✔ Step 7 — Validate Inputs for Codex

Before running Codex:

☐ Required files uploaded

☐ Snapshot name included in PR header

☐ Forbidden file list included

☐ Exact summary of changes

☐ Expected diff behavior described

☐ One or two example code blocks included (optional, recommended)

✔ Step 8 — Generate Patch (Codex)

Run the PR prompt using ONLY:

Snapshot

Explicit file list

Targeted diffs

Test expectations

✔ Step 9 — Validate Patch Before Committing

Check the diff:

☐ Only allowed files touched

☐ Smallest diff possible

☐ No whitespace churn

☐ No refactors

☐ No legacy imports

☐ App still boots

☐ Pipeline still runs

☐ No new Tkinter errors

☐ No missing attributes

☐ Snapshot diff matches expected changes

✔ Step 10 — Run Tests

☐ Unit tests

☐ GUI tests

☐ Integration/pipeline tests

☐ Journey test suite

If anything breaks → repair or revert patch.

✔ Step 11 — Commit PR

Include:

Snapshot name

List of touched files

Subsystem justification

Diff summary

Checklist results

✔ Step 12 — Create a Post-Merge Snapshot

Run the snapshot generator again after merging.

This checklist guarantees:

No accidental regressions

No uncontrolled AI drift

Clean, surgical PRs

Full reproducibility

Stable evolution of the StableNew architecture

Use it religiously.