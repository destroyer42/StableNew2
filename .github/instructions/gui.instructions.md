**Purpose:** Prevent GUI from accidentally importing pipeline/learning and making spaghetti.

**Content:**

```markdown
# GUI Folder Instructions

You are inside `src/gui/`, which defines the Tk/Ttk interface for StableNew.

## Hard Rules
- GUI modules must NOT import: pipeline, learning, api, cluster, ai.
- GUI may import: controller, utils, other GUI modules.
- Use V2 conventions: prefer `*_v2.py` and `panels_v2/`.
- No new legacy (V1) files should be created.

## Styling
- Use the V2 theme from `src/gui/theme.py` only.
- Do not create duplicate theme modules.

## Behavior
- GUI widgets should remain thin. Move logic to controllers.
- Avoid threading from GUI — route through controllers.
- Maintain existing Tk event patterns and avoid adding global side effects.