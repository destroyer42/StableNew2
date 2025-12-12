LeftZone Layout Notes (PR-GUI-02)
=================================

Goal: Give the LeftZone a clean, non-overlapping preset row.

- Use a card-like frame with padding inside LeftZone.
- Put “Preset:” and its dropdown in that frame using grid.
- Either:
  - Label on row 0, dropdown on row 1 (vertical stack), or
  - Label at (0,0), dropdown at (0,1) (horizontal row).
- Allow the combobox column to expand with `columnconfigure`.

Focus strictly on layout; do not change behavior.
