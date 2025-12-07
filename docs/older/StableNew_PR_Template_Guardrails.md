# StableNew PR Template (Enforced Guardrails Edition)

## 🚦 PR Title  
**PR-ID:**  
**Scope:**  
**Summary (1 sentence):**  

---

## 📦 Snapshot Requirement (MANDATORY)

Before making ANY changes, you must execute the snapshot script:

```cmd
python stablenew_snapshot_and_inventory.py
```

This generates:

- `snapshots/StableNew-snapshot-YYYYMMDD-HHMMSS.zip`
- `snapshots/repo_inventory.json`

**Record the snapshot used as this PR baseline:**

**Baseline Snapshot:**  
`<INSERT EXACT ZIP NAME HERE>`

❗ _PRs missing this field are invalid and must be redone._

---

## 🧱 PR Type  
(Check one)

- [ ] Fix-only  
- [ ] Wiring  
- [ ] GUI update  
- [ ] API/Backend  
- [ ] Refactor  
- [ ] New feature  
- [ ] Tests only  

---

## 🧩 Files to Modify (EXACT PATHS ONLY)

```
<list only the files Codex/Copilot may touch>
```

## 🚫 Forbidden Files  
(Codex/Copilot may NOT modify these)

```
src/gui/main_window_v2.py
src/gui/theme_v2.py
src/pipeline/executor.py
src/main.py
<add others as required>
```

---

## 🎯 Done Criteria (Must ALL be true)

- [ ] All allowed files modified ONLY as scoped above  
- [ ] Forbidden files untouched  
- [ ] All tests pass  
- [ ] No regressions in:  
  - app startup  
  - WebUI bootstrap  
  - pipeline execution  
  - resource discovery  
- [ ] Snapshot recorded in PR body

---

## 🧪 Tests to Validate

List exact tests Codex must ensure remain green:

```
pytest tests/app/test_app_controller_pipeline_flow_pr0.py -q
pytest tests/gui_v2/test_entrypoint_uses_v2_gui.py -q
pytest tests/api/test_webui_healthcheck.py -q
<others as needed>
```

---

## 📋 PR Instructions to Codex/Copilot

1. You may edit ONLY the “Files to Modify” list.  
2. You MUST NOT edit anything in “Forbidden Files.”  
3. All diffs must be minimal and surgical.  
4. No new behavior without explicit instruction.  
5. No renames, moves, or refactors unless explicitly stated.  

---

## 📝 Notes for Reviewers

```
<Optional notes>
```
