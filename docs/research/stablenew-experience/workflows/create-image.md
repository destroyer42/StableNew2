# Workflow W1 — Create image

**Discovery status: OPEN** (owner has not reviewed). Last updated 2026-11-05. Evidence IDs refer to [EVIDENCE_REGISTER](../EVIDENCE_REGISTER.md).

## Observed current state [V/D]
- Entry: Prompt tab (authoring) and Pipeline tab (sidebar composer, Working Settings, Preview, Queue, Job History); header Run/Preview/Stop. Group "Create" holds Prompt and Pipeline (EV-30).
- Pipeline composer: **Generate** (txt2img), **Improve Result (optional)** (ADetailer, upscale), collapsed **Advanced and legacy stages** (img2img); Refiner/Hires inside one disclosure (ownership map, PR-GUI-UX-530).
- Path: PromptPack → Preview (frozen jobs) → Add to Queue (queue-first; Run Now only enqueues) → Job History → image. Preview thumbnail only shows a *saved* image, never generates one.
- IMG-01 full desktop journey passes at normal/minimum/maximized with direct reachability after PR-831 (EV-01..03). Stages ADetailer/upscale are off in that journey.
- Settings scopes visible in this area: PromptPack Settings, Saved Pack List, Working Settings + Current Job Overrides, Startup Defaults, Application Defaults, generation profile (EV-21).

## Owner direction (from the brief; not yet confirmed per workflow)
Operators should reach a useful outcome without knowing backend/model-family distinctions; one obvious primary action per task state; required parameters visible before admission; concise effective-settings summary.

## Confirmed product decisions (repository)
Queue-first; frozen NJR; GUI does not build backend payloads or call the runner (`AGENTS.md` §2). Forge default, A1111 rollback (`STATUS.md`). Retained persisted tab IDs (audit 2026-10-22 "do not renumber").

## Hypotheses [H]
- H1: The minimum useful path is *prompt → model → count → Queue* and the rest belongs behind one disclosure level.
- H2: Header Run and Pipeline Queue/Preview duplicate each other's role for new users.
- H3: Showing Draft/Preview/Queued/Running/Done as one progression strip beside the primary action reduces navigation to Job History.

## Alternatives
(a) Keep Prompt and Pipeline as two tabs, improve cross-links. (b) Merge into one *Create* workspace with Author / Review-before-queue / Results zones. (c) Wizard for first-time use over (a) or (b).

## Current-state flow → ideal-state flow → differences
Current: Prompt (author) → Pipeline (choose pack/model/profile/stages) → Preview → Add to Queue → Job History to see result. Ideal: **PENDING owner**; candidate in `EXPERIENCE_ARCHITECTURE.md` §3. Differences are unknown until the ideal is stated.

## Discovery contract — status
1 Goal/situation: PENDING · 2 Inputs: PENDING (pack, prompt, model are the known inputs) · 3 Minimum actions: PENDING (current count unmeasured, see VALIDATION T1) · 4 Info at decision points: PENDING · 5 Basic-path settings: PENDING · 6 Expert controls: observed list only (stages, Refiner/Hires, ControlNet) · 7 Duplicated steps: H2 · 8 Reuse of prior assets: Job History "Regenerate with Changes" exists [D] · 9 AI help: Prompt Suggest disabled (EV-35) · 10 Approval/safety: queue admission, frozen NJR [V] · 11 Failure explanation: backend/model reason visibility is an open defect (EV-08) · 12 Finished artifact/follow-on: image in History; follow-ons Edit, Make Video · 13 Owner acceptance examples: **none provided**.

## Open questions
Q1 Is Prompt a separate task or a step of Create? Q2 Which of the six settings scopes must the operator ever see on the basic path? Q3 Should the operator see the chosen backend, or only a capability summary? Q4 What is the acceptance example (e.g., "queue 4 images of a described scene in ≤ N actions")? Q5 Are any *required* parameters currently inside a disclosure (EV-19)?
