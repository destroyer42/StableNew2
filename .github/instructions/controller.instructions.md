---
applyTo: "src/controller/**/*.py"
---

# Controller Instructions

- Controllers orchestrate state and lifecycle; they do not invent alternate execution payloads.
- Keep controller APIs explicit and typed.
- Do not import GUI modules into controller modules.
- Preserve AppStateV2 and NJR-oriented flow assumptions from the v2.6 architecture docs.
- Mirror controller changes in `tests/controller/` or adjacent integration coverage.
