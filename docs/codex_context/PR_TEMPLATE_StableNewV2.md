# Pull Request Template — StableNewV2
### (Atomic, Architecture-Aligned, Codex-Ready)

---

# 1. PR Title
Short, explicit, action-oriented.

Example:  
**“GUI-V2: Fix Controller→State event wiring for txt2img pipeline start”**

---

# 2. PR Summary (High-Level)
Brief overview of what this PR accomplishes.

- What is being added/fixed/refactored?  
- Why does this change exist?  
- What user-level or system-level behavior does it affect?  

Limit this to 2–4 sentences.

---

# 3. Scope of This PR (Atomic Requirement)
> This PR addresses **exactly one** concern, module, or feature slice.

Clearly state the boundary:

- What *is* included  
- What is *not* included  
- Any work that is deferred to future PRs  

---

# 4. Related Architecture_v2 Section
(Optional but recommended)

Paste or cite the relevant section from `ARCHITECTURE_V2.md` that this PR implements or aligns with.

Example:

> Architecture Reference:  
> `docs/codex_context/ARCHITECTURE_V2.md` → Section: “4.2 GUI-V2 Event Loop”  

---

# 5. Functional Requirements (This PR Must Fulfill)
List explicit requirements for this PR.  
This is where ChatGPT or the PM will define *exact expected behavior*.

Example:

- State updates must flow Controller → State → View  
- Themed widgets must respect theme.py color map  
- Pipeline start event must trigger async executor correctly  
- No GUI freezing allowed during threaded operations  
- Only 1 upscale job at a time  

---

# 6. File-Level Tasks
Specify **exact files touched**, and what changes occur in each.

Format:

```
/src/gui/controller_v2.py  
- Add callback for txt2img start  
- Wire event to state update

/src/gui/state_v2.py  
- Add pipeline_start flag  
- Add validation logic

/src/pipeline/executor_v2.py  
- Ensure single-image processing guard
```

---

# 7. Implementation Details (What Codex Will Do)
This is the “developer notes” section telling Codex what to implement.

Include:

- Expected algorithms  
- Data flow  
- State transitions  
- Error-handling behavior  
- Logging expectations  
- Threading/async requirements  

Example block:

```
- Use existing async wrapper utilities
- Do NOT modify GUI-V1 modules
- Use Controller.update_state(...) instead of direct state mutation
```

---

# 8. Testing Requirements

Define the tests Codex should run or update.

**Unit Tests**  
- Which functions/classes require tests  
- Expected mock boundaries  
- Edge cases  

**Journey Tests (if applicable)**  
- Stage order  
- Error conditions  
- Proper completion and cleanup  

---

# 9. Acceptance Criteria (Reviewer Checklist)

Reviewers confirm the following:

- [ ] PR scope is atomic & focused  
- [ ] Architecture_v2 alignment is correct  
- [ ] No unrelated changes or refactors  
- [ ] Code follows existing patterns/style  
- [ ] All updated files listed clearly  
- [ ] Unit tests added/updated as required  
- [ ] Journey test behavior validated (if relevant)  
- [ ] GUI-V2 theming preserved  
- [ ] No breakage of existing pipeline stages  

---

# 10. Manual Validation Steps (Optional for GUI/Pipeline PRs)

Describe how a reviewer manually verifies correct behavior.

Examples:

- Launch `main.py` and verify txt2img button triggers proper state updates  
- Ensure GUI remains responsive  
- Confirm only one image processes in upscale stage  
- Check log output for correct stage labels  

---

# 11. Codex Prompt (Copy/Paste Ready)
This is the standardized implementation prompt for Codex 5-1 MAX.

Paste the PR content into the placeholders.

```
You are Codex 5-1 MAX working in the StableNewV2 repo.
Implement the following PR exactly as written.

PR Title:
{{TITLE}}

PR Description:
{{FULL_PR_BODY}}

Files to Modify/Create:
{{LIST_OF_FILES}}

Tasks:
- Implement the code changes described in this PR.
- Change only the files and concerns listed.
- Preserve existing behavior unless explicitly told to change it.
- Follow the Architecture_v2 section referenced.

Constraints:
- No broad refactors.
- No unrelated style changes.
- Keep commits small, local, and traceable.
- Maintain GUI-V2 conventions and theming.

After implementing, output:
- Files changed
- Key functions/classes added/modified
- Any TODOs for follow-on PRs
```

---

# 12. Notes / Follow-On Work (Optional)
If follow-up PRs are expected, list them clearly.

Example:

- PR #32 will finalize EventLoopV2 cancellation logic  
- PR #33 will clean logging duplication in ExecutorV2  
- PR #34 will unify GUI-V2 theme inheritance  

---

# End of PR Template
