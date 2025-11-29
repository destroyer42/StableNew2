Theme Design Notes for PR-GUI-01
================================

Goals
-----
- Dark base UI with clear accents.
- Subtle differentiation between background and surface frames.
- High contrast for primary actions; softer contrast for secondary actions and status text.
- All colors and paddings defined via tokens in `theme.py`, not scattered literals.

Suggested Palette
-----------------
- Window background: very dark neutral (e.g., #18181b)
- Surface frames: slightly lighter neutral (e.g., #27272f)
- Primary accent (Run): warm gold/yellow (e.g., #facc15, close to ASWF gold)
- Danger accent (Stop): red (e.g., #ef4444)
- Text primary: near-white (e.g., #f9fafb)
- Text secondary: gray (e.g., #9ca3af)
- Border subtle: dark gray (e.g., #3f3f46)

Spacing
-------
- Use consistent horizontal and vertical padding:
  - XS = 2
  - SM = 4
  - MD = 8
  - LG = 12
- Header buttons should have MD horizontal padding and SM vertical padding.

Styles
------
- `Primary.TButton`: bold, bright, flat, minimal border.
- `Danger.TButton`: similar to primary but red.
- `Ghost.TButton`: low-contrast background, light border or no border.
- `Status.TLabel`: muted foreground color for less important text.
- `StatusStrong.TLabel`: brighter text for primary status.

Usage in MainWindow_v2
----------------------
- Initialize theme once per root using `configure_style(root)`.
- Set root background to `COLOR_BG`.
- Ensure header and bottom frames use `COLOR_BG` or `COLOR_SURFACE`.
- Apply the named styles to the intended buttons and labels.

These notes guide the aesthetic but the actual implementation in `theme.py` should remain minimal, focused, and aligned with the PR spec.
