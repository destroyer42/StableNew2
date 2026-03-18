---
applyTo: "src/pipeline/**/*.py"
---

# Pipeline Instructions

- Preserve the builder pipeline and NJR-only execution contract.
- Do not import GUI modules.
- Do not introduce dict-based or PipelineConfig-based execution payloads for new work.
- Keep builders deterministic and runtime contracts typed.
- Mirror behavior changes in `tests/pipeline/` and relevant integration coverage.
