# PROJECT_CONTEXT

> High-level context for AI coding assistants (Codex / Copilot / ChatGPT / Cursor).
> **Do not inline this entire file into prompts.** Instead, reference specific sections.

---

## 1. Project One-Liner

StableNew is a **Python-based orchestration layer and GUI for Stable Diffusion WebUI (A1111)** that:
- Manages prompt packs and pipeline configs (txt2img → img2img → upscale → optional video).
- Talks to a running SD WebUI instance via HTTP API.
- Provides a Tkinter GUI for non-technical users.
- Records learning / execution traces for later analysis (Learning v2 system).

---

## 2. Core Design Principles

1. **Separation of concerns**
   - GUI widgets must not embed pipeline / HTTP logic directly.
   - Controllers orchestrate; pipelines execute; API client talks over HTTP.

2. **Testability**
   - Prefer thin, pure functions and injected dependencies over globals/singletons.
   - New logic should be covered by unit and integration tests (pytest).

3. **Safety & Observability**
   - Structured logging (info/warn/error, diagnostic messages).
   - Clear error propagation to GUI (user-friendly messages).

4. **Incremental refactor**
   - New code follows the “v2” patterns (structured configs, controllers).
   - Old legacy paths are gradually removed only after tests cover the new flow.

---

## 3. Major Subsystems (Pointers)

- **GUI**
  - Tkinter-based windows, panels, dialogs.
  - Lives under `src/gui/` (e.g., `main_window.py`, `prompt_pack_panel.py`, etc.)

- **Controllers**
  - Coordinate user actions, pipeline execution, status updates.
  - Lives under `src/controller/`.
  - Key files: `pipeline_controller.py`, `learning_execution_controller.py`, etc.

- **Pipelines**
  - Implementation of the full SD flow.
  - Lives under `src/pipeline/` (e.g., `pipeline_runner.py`, pipeline config objects).
  - Pipelines must be **headless** and non-GUI-aware.

- **API Client**
  - Wraps Stable Diffusion WebUI HTTP API.
  - Lives under `src/api/` (e.g., `client.py`).
  - Enforces defaults, timeout behavior, and retry semantics.

- **Learning System (v2)**
  - Records structured “LearningRecords” for each pipeline run.
  - Builder constructs records from configs + results.
  - Writer appends records to JSONL in an atomic, append-only fashion.

- **Logging / Utilities**
  - Logging helpers, file I/O utilities, configuration loaders.
  - Lives under `src/utils/`.

---

## 4. Golden Rules For AI Agents

When changing code, **follow these rules**:

1. **No GUI logic in pipeline or API client modules.**
2. **No direct HTTP calls from GUI.** Always go via controllers or API client.
3. **Prefer data classes / config objects** for pipeline inputs over ad-hoc dicts.
4. **Preserve existing tests.** If a change breaks tests, adjust implementation first and tests only when behavior legitimately changes.
5. **Keep “learning” APIs opt-in and side-effect-safe.**
6. **Never hard-code user paths or system-specific paths.** Use config and environment / settings.

---

## 5. How This File Should Be Used (For AI Assistants)

- When asked to implement a feature or PR, **load only the relevant section(s)** of this file.
- Prefer referencing:
  - `ARCHITECTURE_V2.md` for structure and dependencies.
  - `PIPELINE_RULES.md` for pipeline-specific behavior.
  - `LEARNING_SYSTEM_SPEC.md` for anything about Learning v2.

---
