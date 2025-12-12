PipelineRunner Design Notes for PR-0
====================================

This file is *not* code, but guidance for how to implement src/controller/pipeline_runner.py.

Key points:
- Keep PipelineRunner extremely small and focused.
- Do not pull GUI concepts into this module.
- Do not modify src/pipeline internals from here; only call them.

Suggested structure:

- Define the Protocol:

    class PipelineRunner(Protocol):
        def run(self, config: RunConfig, cancel_token: CancelToken, log_fn: Callable[[str], None]) -> None:
            ...

- Dummy implementation:

    class DummyPipelineRunner(PipelineRunner):
        def run(...):
            log_fn("[pipeline] DummyPipelineRunner starting (stub).")
            # Loop a few times, checking cancel_token and logging progress.
            log_fn("[pipeline] DummyPipelineRunner finished (stub).")

- Real implementation (minimal placeholder for PR-0):

    from src.pipeline import Pipeline

    class RealPipelineRunner(PipelineRunner):
        def __init__(self, structured_logger: StructuredLogger | None = None):
            self.structured_logger = structured_logger

        def run(self, config: RunConfig, cancel_token: CancelToken, log_fn: Callable[[str], None]) -> None:
            log_fn("[pipeline] RealPipelineRunner starting.")
            try:
                # For PR-0, you may temporarily use a conservative default config and/or
                # a placeholder prompt. The important part is that this call does not hang
                # and that errors are surfaced.
                #
                # Later PRs will properly build the config from GUI + presets.
                pipeline = Pipeline(...)
                # TODO: call pipeline.run_full_pipeline(...), honoring cancel_token where possible.
            except Exception as exc:
                log_fn(f"[pipeline] RealPipelineRunner error: {exc!r}")
                raise
            else:
                log_fn("[pipeline] RealPipelineRunner finished successfully.")

These notes should be used together with PR-0_Pipeline_Execution_Hotfix.md and Codex_Execution_Guide_PR-0.md.
