Packs/Presets Panel Design Notes (PR-GUI-LEFT-01)
=================================================

Intent
------
Move core Pack discovery and basic selection behavior to the v2 architecture without pulling legacy GUI code forward.

Key Ideas
---------
- There should be a single place where pack metadata is discovered (a small utility/service module).
- The controller should:
  - Own the list of available packs.
  - Own the notion of "currently selected" pack.
  - Provide simple methods that the GUI can call on button clicks.
- The GUI LeftZone should:
  - Be responsible only for presenting the pack list and forwarding events to the controller.
  - Never perform direct file I/O or pack parsing.

Future Extensions (not in this PR)
----------------------------------
- Integrating the active pack into the pipeline configuration.
- Persisting last-selected pack between sessions.
- Providing an in-app editor or rich metadata view for Packs.
