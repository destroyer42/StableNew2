"""PR-IMG-MODELS-154B: controlled Z-Image-Turbo FP8 physical-qualification HARNESS (hardware qualification tooling only).

This package is deliberately isolated from the canonical StableNew execution path
(Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler -> Artifacts/History)
and adds no queue, runner, history or compiler authority. Importing it, or any module in it, has no side effect: nothing is
started, selected, sent or written at import time. The only module that can reach a real runtime is ``physical``; it is
disabled by default and is never imported by any other module here.
"""
