Config Panel Design Notes (PR-GUI-CENTER-01)
===========================================

Intent
------
Provide a minimal but functional Config Panel in the Center Zone for model, sampler, resolution, steps, and CFG, while keeping pipeline integration for a later PR.

Key Principles
--------------
- AppController holds the source-of-truth config state.
- ConfigPanel is a thin view that reads from/writes to controller via MainWindow_v2.
- Keep defaults simple and deterministic; no randomizer or advanced options yet.
