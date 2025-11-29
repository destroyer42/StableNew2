---
name: "S2-B Max dimensions ≤2260"
about: "Increase width/height caps to 2260 with validation/warnings"
title: "S2-B Max dimensions ≤2260: "
labels: [sprint-2, config, feature, ux]
assignees: ""
---


## Goal
Allow width/height up to **2260** with validation and helpful warnings/tooltips.

## DoD
- Spinboxes permit ≤2260.
- Validator rejects >2260 and shows message.
- Low-VRAM warning if applicable.

## Tasks
- [ ] Update bounds; add validator + tooltip text.
- [ ] Tests for boundaries and messaging.

## Test commands
```
pytest tests/gui/test_config_panel.py -q
```
