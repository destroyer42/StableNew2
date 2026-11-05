"""PR-QUAL-SYSTEM-840: cross-workflow image, video, motion and AI qualification control (operator-only tooling).

This package builds the qualification ledger, freezes per-arm physical plans, gates every physical arm on an exact owner
authorization and a typed launch, archives attempts immutably and compares accepted evidence read-only.  It adds no queue,
runner, cancellation manager, runtime owner or History store, changes no production behavior and promotes nothing.  The
production path stays ``Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr -> Handler``;
physical work is delegated to the retained harnesses and the normal operator GUI.  Nothing here is imported by the
application, and pytest and CI never reach a GPU, a runtime, a model download or a physical arm.
"""

SUITE_ID = "qual-system-840"
SUITE_VERSION = "1.0.0"
#: The fixed-source benchmark the arms share; a changed benchmark is a new version and is never compared to an older one.
BENCHMARK_VERSION = "840.1"
