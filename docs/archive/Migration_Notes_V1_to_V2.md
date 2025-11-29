# Migration Notes: GUI V1 → GUI V2 and Architecture V2

---

## 1. Why We Pivoted

GUI V1 evolved organically and became:

- Hard to reason about (monolithic main window, ad‑hoc panels).
- Difficult to test (tight coupling between GUI, pipeline, and randomizer logic).
- Risky to refactor (400+ tests with intertwined expectations).

V2 addresses these issues by:

- Introducing **modular panels and stage cards**.
- Strictly separating GUI from controller and pipeline layers.
- Reducing the number of tests required to validate behavior (while increasing their clarity).
- Preparing for **learning** and **cluster** features that V1 was never designed for.

---

## 2. What Is Considered Legacy

- All V1 GUI tests and layout assumptions.
- Monolithic ConfigPanel behaviors and legacy config metadata interfaces.
- Any code that expects GUI to drive pipeline or randomizer logic directly.

These are now captured in:

- A **tests/gui_v1_legacy/** folder (or equivalent) for historical reference.
- Archived documents such as StableNew_Roadmap_v1.0 and ARCHITECTURE_v2_Translation_Plan.md.

---

## 3. New Center of Gravity

Going forward, the following are authoritative:

- **StableNew_Roadmap_v2.0.md** – direction and phases.
- **ARCHITECTURE_v2.md** – layering and flows.
- V2 GUI modules:
  - StableNewGUI
  - PipelinePanelV2 and stage cards
  - RandomizerPanelV2
  - StatusBarV2
- V2 core subsystems:
  - PipelineRunner and PipelineConfig
  - RandomizerAdapter + randomizer utilities
  - Learning plan/runner/record modules
  - (Future) Cluster scheduler and agents

---

## 4. How to Think about Migration

### 4.1 Keep Legacy Tests, Don’t Chase Them

- Legacy GUI tests are moved under a legacy folder and **not** run by default.
- They remain available for consultation (e.g., to understand old behavior), but they are not gatekeepers for V2.

### 4.2 Migrate Workflows, Not Widgets

- V1: direct manipulation of many controls, often in one large panel.
- V2: workflows are expressed via cleaner building blocks:
  - Stage cards for pipeline.
  - Randomizer panel for variants.
  - Status bar for lifecycle.
  - Learning and cluster features as first‑class concepts.

---

## 5. Practical Guidelines for Developers

1. **New features must target V2 only.**
   - Do not add new controls or logic to V1 panels.
   - If a behavior is only present in V1, port the intent into V2 and tests, not the exact implementation.

2. **Do not resurrect legacy coupling.**
   - Randomizer logic lives in utils + adapter, not inside GUI widgets.
   - Learning logic lives in learning modules and pipeline hooks, not in Tk callbacks.

3. **Tests should be V2‑focused.**
   - GUI V2 tests should be small, focused: layout skeletons, button wiring, config roundtrips, etc.
   - Controller and pipeline tests handle behavior and edge cases.

---

## 6. User‑Facing Changes

- Initially, V2 may look like an evolution of V1 (similar controls, more organized layout).
- Over time, the user will see:
  - More **one‑click actions**.
  - Learning‑aware recommendations.
  - Cluster status indicators and batch capabilities.

The guiding principle is to **reduce cognitive load** on the user while greatly increasing the sophistication of what happens under the hood.

---

## 7. Summary

- V1 is now historical context.
- V2 is the living architecture.
- Learning and cluster features are built into V2 from the ground up.
- All new PRs should reference this migration doc when making breaking changes, to ensure we stay aligned with the new direction.
