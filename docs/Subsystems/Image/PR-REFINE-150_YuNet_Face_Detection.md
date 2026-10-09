# PR-REFINE-150 — YuNet on existing core OpenCV

Status: local implementation and CPU qualification; independent review/publication pending.

## Execution profile and validation

Standard, bounded detector/dependency qualification. Recommended: Codex GPT-6.1
Sol High / Claude Code Sonnet 5.5 High, Windows Local/Desktop for the supported
CPython 3.14 wheel. Controller Surface Assessment: no controller/coordinator
changes or ceiling increases; PipelineRunner changes only preserve truthful
refinement failure observations. Its submission/execution authority is unchanged.

Token-Efficient Validation Plan: qualify the pinned core wheel and upstream model
in a disposable environment, prove detector geometry/failure behavior with mocks,
run real-photo CPU checks and affected OpenCV/refinement/Learning regressions,
then scoped lint/type/security checks and one final local PR gate. Reuse unchanged
generation, restoration and PromptPack evidence; no physical generation required.

Final tri-state repair/integration is Narrow: Codex GPT-6.1 Sol Medium / Claude
Code Sonnet 5.5 Medium, existing Local/Desktop host. No controller changes.
Validate status-qualified Learning projection and actual bundle/record JSON
roundtrips, affected refinement/Learning tests and the prescribed final gate;
reuse unchanged detector, CPU, asset and dependency qualification.

## Ownership and dependency contract

The owner-selected implementation retains `opencv-python==5.0.0.93`, NumPy
2.5.3 and CodeFormer 0.0.11. No dependency declaration or runtime pin changes.
CodeFormer requires `opencv-python`; no Contrib distribution is introduced.
Prior Contrib qualification found missing Haar XML assets. Haar and external
XML workarounds are removed from the subject detector.

`OpenCvFaceDetector` remains the implementation of `SubjectDetector` selected
by intent `detector_preference="opencv"`. It now reports
`detector_id="opencv_yunet"`, `detector_algorithm_version="yunet_2026may/1"`
and the model SHA in observations. Policy `algorithm_version="v1"` remains the
subject-scale policy version, not the detector version. Historical Haar rows
with detector identity `opencv` are not relabeled or rewritten.

## Offline model and CPU execution

The 229,738-byte ONNX model and its MIT copyright/license notice live in
`src/refinement/assets/`. Exact upstream revision, SHA and redistribution notice
are documented in the adjacent README. The detector checks bounded file length
and SHA before native loading. Missing, corrupt or different bytes refuse loading
with guidance to restore the repository asset. There is no download, search,
registry, backend, worker process or installed model-folder mutation.

YuNet uses dynamic input shape, OpenCV DNN and the CPU target. Supported core
OpenCV 5 uses its default graph engine; its warning that targets are unsupported
by that engine does not select CUDA or another runtime. CPU inference was directly
qualified; no process-wide engine override is introduced.

Input is BGR in raw raster orientation, matching Pillow dimensions used by the
subject-scale service. Inputs exceeding a 1,280-pixel edge are resized with their
aspect ratio preserved. Box coordinates are projected with the actual rounded
input dimensions, outward rounded, and clipped to the original image bounds.
Valid detections below the score threshold are filtered. Any nonempty row with
nonfinite or degenerate geometry, a score outside [0, 1], or no area inside the
image is malformed output: the whole inference fails (`error`, `face_detected` null)
rather than becoming a confirmed no-face result. Defaults: score
0.6, native NMS 0.3, top-k 5,000; the existing 0.35 overlap suppression remains.
Largest-area-first ordering preserves the primary-subject convention, followed
by confidence and coordinates to resolve ties deterministically. Landmarks are
not interpreted as a new pose classifier; `pose_band` remains unknown.

## Evidence and failure semantics

Successful empty inference means `scale_band="no_face"`. Missing detector/input,
initialization errors, decode/inference errors and assessment deadlines mean an
unknown scale with explicit unavailable/error/timeout status and diagnostic notes.
They never become a confirmed empty detector result. Initialization guidance is
preserved in runner metadata. Adaptive Refinement retains existing policies and
prompt intent; observations explain which evidence was available for a decision.

The compact Learning context preserves detector identity/version, model SHA and
detection status. `face_detected=True` requires successful available assessment,
positive count and a qualified face scale; `False` requires successful zero
detections and `no_face`. Unavailable, error, timeout, missing, unknown and
inconsistent assessments yield `None`, preserved as JSON `null`. Legacy records
are not rewritten; missing status is insufficient for a new qualified summary.
The RecommendationEngine's lightweight normalization preserves detector version and
status; no pipeline import or recommendation policy change is introduced.

The immutable NJR, queue-first JobService admission, replay envelopes and
`PipelineRunner.run_njr` entrypoint remain unchanged. Existing historical records
are not migrated. This detector only produces post-execution observations.

## Qualification evidence and limits

Windows standard-GIL CPython 3.14.8, core OpenCV 5.0.0.93 and NumPy 2.5.3
loaded and inferred the independently hashed official model on CPU. The NASA
astronaut reference photo from pinned scikit-image source produced a plausible
original-coordinate face (approximately 0.93 confidence), with successful mirror,
tilt and large-input checks. This is reference-photo qualification, not a recall
benchmark or a guarantee of every profile/occluded face. Synthetic tests separately
prove resize projection, clipping, overlap handling, confidence and failure paths.

Sharpness/Laplacian, image transformations, blank-image inference and deterministic
temporary video encode/decode were exercised. No physical image/video generation
or active application/runtime mutation occurred. Base CI can run mocked geometry,
failure and asset-identity tests without OpenCV; native CPU coverage is explicitly
optional when that declared capability is absent. Full restoration with actual
weights is unchanged and its accepted evidence is reused, not requalified here.

Run offline photo qualification with an explicitly supplied local reference:

```text
python tools/qualification/refine150/qualify_cpu.py PHOTO --report REPORT.json
```

The tool asserts exact core OpenCV ownership and NumPy pins, uses temporary output
paths and never downloads an image/model, starts a runtime, or submits a job.
