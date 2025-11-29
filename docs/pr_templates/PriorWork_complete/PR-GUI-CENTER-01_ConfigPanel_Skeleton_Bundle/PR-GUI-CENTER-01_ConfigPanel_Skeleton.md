PR-GUI-CENTER-01: Core Config Panel Skeleton (Center Zone v2)
=============================================================

1. Title
--------
Introduce a basic Config Panel in the Center Zone for core SD settings (PR-GUI-CENTER-01).

2. Summary
----------
The current v2 GUI has:

- A functional Header (Run/Stop/etc.) tied to `AppController`.
- A LeftZone pack card that is being wired to real pack discovery and selection.
- A BottomZone status bar and log area.

The Center Zone, however, is effectively empty. Users cannot see or adjust core Stable Diffusion parameters (model, sampler, resolution, steps, CFG, etc.) from the v2 GUI.

This PR introduces a Config Panel skeleton in the Center Zone that:

- Displays the most important core settings:
  - Model (checkpoint) selection.
  - Sampler selection.
  - Image size (width/height) or preset resolution choices.
  - Steps and CFG scale.
- For now, remains mostly UI-only and backed by simple controller-side config state or stubs.
- Does not yet integrate deeply with the pipeline; that will be a follow-up PR once the pipeline interface is finalized.
