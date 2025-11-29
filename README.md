# StableNew V2

## Overview
StableNew V2 is a ground-up architectural reset designed to fix the complexity, regressions, and architectural drift of V1. This version emphasizes modularity, testability, learning-driven defaults, and cluster-scale execution.

## V1 → V2 Pivot (Direct & Pragmatic)
V1 became too large, too tangled, and too hard to safely change. Every small fix risked breaking unrelated UI or pipeline paths. The test suite ballooned because the architecture demanded it, not because it increased quality. The GUI mixed responsibilities. The pipeline had too many implicit assumptions. Randomizer logic leaked everywhere. Adding new features felt dangerous.

V2 corrects this by:
- Splitting GUI, controller, pipeline, randomizer, and learning systems cleanly.
- Removing legacy hooks and replacing them with well-defined adapters.
- Introducing deterministic, purely functional components where possible.
- Reducing required test surface through proper separation of concerns.
- Creating a real foundation for cluster/job-distributed AI generation.

V2 is what V1 should have been.

## Key Capabilities
- Modular Stage Cards (txt2img, img2img, upscale)
- Learning-mode infrastructure (active & passive)
- Randomizer V2 (matrix modes, fanout, overlays)
- Testable GUI (headless-safe, isolated)
- Pipeline Runner with structured I/O
- Future cluster-ready design

## Repository Inventory
Generate a machine-readable snapshot of active modules and likely legacy files:

```
python -m tools.inventory_repo
```

Outputs:
- `repo_inventory.json`
- `docs/ACTIVE_MODULES.md`
- `docs/LEGACY_CANDIDATES.md`

## Contributing
Follow PR templates under `docs/pr-templates/`.
Do not modify multiple subsystems in a single PR.
Tests come first.
Codex instructions must be followed exactly.

