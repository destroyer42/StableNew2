# Archive Reference Package

`tools.archive_reference` holds legacy reference code that is intentionally kept
out of importable runtime package paths under `src/`.

Rules:

- do not import this package from active runtime code under `src/`
- compat-only or archival tests may import it explicitly when they need
  historical `PipelineConfig`-era fixtures
- this package does not revive any supported runtime API
