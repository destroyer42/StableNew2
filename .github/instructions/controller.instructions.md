# Controller Folder Instructions

You are inside `src/controller/`.

## Core Rules
- Act as the mediator: GUI → controller → pipeline/learning/api.
- Do not import GUI modules.
- Keep controllers pure and avoid file I/O unless intentional.

## Behavior
- Expose clean methods for GUI to call.
- Manage async tasks, cancel tokens, and orchestration of pipelines.
- Keep configs deterministic; avoid modifying global state.

## Testing
- Ensure controller changes have corresponding tests under `tests/controller/`.