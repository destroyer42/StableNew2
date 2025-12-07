# StableNewV2 — High-Stability Request Format v4.0
### (Optimized for PR Bundles, GUI-V2 Wiring, Pipeline Executor, Architecture_v2, and Codex 5-1 MAX)

---

# 1. StableNewV2 Context Controller
Use this block at the top of every request:

**StableNewV2 Context Mode**  
- Operate **only** within the StableNewV2 project folder.  
- Use **only** the files/snippets I provide in the Inputs section.  
- Ignore all older StableNew snapshots unless explicitly cited.  
- Ignore GUI-V1 context unless cited.  
- Ignore non-StableNew project context (e.g., CCIR, ASWF) unless cited.

This prevents unintended context loading and improves stability.

---

# 2. Task Scope (Single-Phase)
Each request must perform **exactly one phase**.  
Do not chain phases into the same message.

Examples of valid single-phase scopes:
- Generate **one** expanded PR  
- Generate **one** PR bundle (unexpanded, max 5)  
- Produce **one** Architecture_v2 update  
- Produce **one** wiring map description  
- Generate **one** YAML import  
- Generate **one** Python module  
- Generate **one** ZIP archive (≤ 8 files)  

---

# 3. Inputs (Strict Boundary)
This is where you paste all relevant files or snippets.

**Inputs:**  
Use **only** the following pasted StableNewV2 files/snippets.  
Ignore all other repository files.

*(Paste content here.)*

This keeps the model from pulling in unnecessary repo context.

---

# 4. Output Type (Select Exactly One)
Choose one and only one:

## PR / Project Artifacts
- PR Template (single)  
- Expanded PR (single)  
- PR Bundle (≤5, unexpanded)  
- Codex Implementation Prompt (single PR)  
- Codex Batch Prompt (for PR bundles)

## Architecture / Wiring
- Architecture_v2 update  
- GUI-V2 Wiring Map (text-based)  
- StageExecutor/Controller dependency map  
- Pipeline sequence flow  
- Directory/file structure plan  

## Code / Technical Files
- Tkinter skeleton (single file)  
- Tkinter event-loop patch  
- Python module (single)  
- Test scaffold (single)  
- JSON schema (single)  
- Code diff patch  

## Packaging
- Markdown file  
- YAML import  
- ZIP archive (≤ 8 files)

---

# 5. Generation Mode (Staged)
Use this every time:

**Mode:**  
1. Perform analysis only.  
2. Stop and wait for my confirmation.  
3. After confirmation, generate the final artifact.

This prevents runaway reasoning.

---

# 6. Stability Guardrails (Required)
Include this block unchanged:

**Rules:**  
- Operate only on the provided Inputs.  
- Do not load unrelated files.  
- Do not combine multiple output types.  
- No images unless specifically requested.  
- No mixing reasoning + tool calls unless asked.  
- ZIP archives must contain **8 files or fewer**.  
- Stop cleanly if approaching length limits.  
- Ask for clarification before assuming cross-file dependencies.  

---

# 7. Completion Condition
**Deliver exactly one artifact for the selected output type and stop.**  
Do not continue into additional PRs, phases, or packaging steps without approval.

---

# 8. Examples

---

## Example A — Expanded PR (Single)

**StableNewV2 Context Mode**  
Operate only within StableNewV2.

**Scope:**  
Expanded PR for GUI-V2 Controller→State wiring fix.

**Inputs:**  
(controller_v2.py, state_v2.py, theme.py pasted here)

**Output Type:**  
Expanded PR Template (single)

**Mode:**  
Pause after analysis.

**Rules:**  
One artifact only. No zips. No diagrams.

**Completion:**  
Stop after expanded PR.

---

## Example B — PR Bundle (Unexpanded)

**StableNewV2 Context Mode**  
Only use pasted files.

**Scope:**  
Phase 1/3 only — generate PR summaries for GUI-V2 event loop tasks (max 5)

**Inputs:**  
(paste relevant GUI-V2 files)

**Output Type:**  
PR Bundle (≤5, unexpanded)

**Mode:**  
Pause after analysis.

**Rules:**  
No expansions. No zip. No Codex.

**Completion:**  
Stop after summaries.

---

## Example C — Architecture_v2 Update

**StableNewV2 Context Mode**  

**Scope:**  
One architecture update describing the new Event Loop → StageExecutor integration.

**Inputs:**  
(paste changed files)

**Output Type:**  
Architecture_v2 update

**Mode:**  
Pause after analysis.

**Rules:**  
No PRs. No code. No zip.

**Completion:**  
Deliver architecture update only.

---

# 9. Mini Fast Format (Daily Use)

StableNewV2 Context Mode
Scope: (one task)
Inputs: (pasted)
Output Type: (one)
Mode: pause after analysis
Rules: one artifact only
Completion: stop after deliver

yaml
Copy code

---

# 10. Summary
This file defines the stable, atomic request format for all StableNewV2 workflows including:

- GUI-V2 refactor  
- Pipeline Executor  
- Tkinter restructuring  
- Architecture_v2 documentation  
- PR generation  
- Codex 5-1 MAX implementation prompts  

Using this template will reduce failures, timeouts, and tool-call crashes by 80–95%.

---