#ARCHIVED
> Superseded by docs/Roadmap_v2.5.md (canonical)

## GUI V2 Roadmap Notes

- AppLayoutV2 now owns panel composition for StableNewGUI, enabling further V2 UX work without expanding main_window.py.
- StableNewGUI groups controller/adapter wiring separately from layout, making future editor/preset/learning UI work easier without touching pipeline semantics.
- Learning execution API (non-GUI) initial implementation complete for orchestrating learning plans via pipeline runs.
