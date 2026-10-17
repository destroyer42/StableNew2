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

- Image: [`Image/IMAGE_PIPELINE.md`](Image/IMAGE_PIPELINE.md)
