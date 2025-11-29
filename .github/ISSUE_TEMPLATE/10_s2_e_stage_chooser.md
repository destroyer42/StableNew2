---
name: "S2-E Per-image Stage Chooser (non-blocking)"
about: "Non-blocking modal after txt2img with branching & re-tune"
title: "S2-E Per-image Stage Chooser (non-blocking): "
labels: [sprint-2, gui, ux, tdd]
assignees: ""
---


## Goal
Provide a per-image Stage Chooser modal (preview + choices: img2img/ADetailer/upscale/none). Must be **non-blocking** on Tk mainloop.

## DoD
- Modal returns choice via callback/event; no blocking queue.get() on UI thread.
- “Apply to rest” and “Re-tune settings” supported.
- Cancel at modal halts pipeline.

## Tasks
- [ ] Implement modal + callbacks.
- [ ] Coordinator wiring + persistence of last choice.
- [ ] Headless GUI tests verify no freeze and correct branching.

## Test commands
```
pytest tests/gui/test_stage_chooser.py -q
```
