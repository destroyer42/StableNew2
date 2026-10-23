# Subsystems

Status: Active support folder
Updated: 2026-10-17

This folder contains implementation details that are useful when changing the
named subsystem. They supplement but do not override the architecture,
roadmap, testing guide, or `STATUS.md`.

Examples:

- GUI ownership and consistency references
- learning and randomizer subsystem specs
- testing and workflow reference docs

Read only the subsystem material relevant to the current task. Old audits,
completed plans, generated inventories, and historical implementation records
belong in Git history rather than this directory.

## Living documents

One living document per subsystem, edited in place in the PR that changes the behavior it describes. Per-PR records in the same
folders are historical evidence; where they disagree with the code or a living document, the code and the living document win.

- Image pipeline: [`Image/IMAGE_PIPELINE.md`](Image/IMAGE_PIPELINE.md)
- Model profiles and policy: [`Image/MODEL_PROFILES.md`](Image/MODEL_PROFILES.md)
- Photo Optimize, Review and reprocess: [`GUI/PHOTO_REVIEW_REPROCESS.md`](GUI/PHOTO_REVIEW_REPROCESS.md)
- GUI tokens, styles and shared components: [`GUI/GUI_STYLE_GUIDE.md`](GUI/GUI_STYLE_GUIDE.md)
- Video: [`Video/VIDEO_PIPELINE.md`](Video/VIDEO_PIPELINE.md)
- Queue, runtime and WebUI: [`Runtime/QUEUE_AND_RUNTIME.md`](Runtime/QUEUE_AND_RUNTIME.md)
- Learning: [`Learning/LEARNING.md`](Learning/LEARNING.md)
- PromptPacks and prompting: [`PromptPacks/PROMPTPACKS_AND_PROMPTING.md`](PromptPacks/PROMPTPACKS_AND_PROMPTING.md)
- Offline AI Assist: [`AiAssist/AI_ASSIST.md`](AiAssist/AI_ASSIST.md)
- Testing and CI: [`Testing/TESTING_AND_CI.md`](Testing/TESTING_AND_CI.md)
