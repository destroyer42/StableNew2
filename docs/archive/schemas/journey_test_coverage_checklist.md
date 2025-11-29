# Journey Test Coverage Checklist


## Tasks

- [ ] Extend stage matrix to cover `video` stages, `upscale only` flows, and midstream entry points using stubbed FFmpeg/subprocess interactions.
- [ ] Add regression checks for manifests and CSV rollups: validate per-stage JSON structure, required fields, and data types; check rollup headers and timestamp ordering via `tmp_path`.
- [ ] Cover cooperative cancel and resume scenarios: simulate cancel tokens mid-run and verify clean stops plus resumptions without duplicate manifests.
- [ ] Validate retry/backoff behavior by injecting transient txt2img/img2img failures and asserting exponential backoff intervals are respected alongside manifest outcomes.
- [ ] Exercise prompt pack permutations with multi-batch runs to confirm metadata capture and persistent negative prompt safety lists.
- [ ] Verify thread-safe progress reporting: enforce ordered stage transitions, single completion events, and consistent ETA calculations without erratic fluctuations.
- [ ] Ensure video artifacts are produced: mock video assembly output and confirm summaries/manifests reference the final video path and stage completion status.


## Implementation Notes

- Leverage existing mocked client patterns in `tests/test_pipeline_journey.py` as a baseline for new scenarios.
- Introduce helper fixtures for video stubs, cancel token simulation, and transient failure injection to keep tests focused.
- Reuse `tmp_path` directories per test to isolate run manifests and artifacts.
- Document any new fixtures or utilities directly in their modules to keep contributors aligned.
