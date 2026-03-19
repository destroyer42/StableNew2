Yes — we can incorporate AnimateDiff and Deforum cleanly, without breaking your v2.6 invariants, as long as we treat them as capability-gated WebUI “video frame generators” that produce frames, and then use a canonical “video render” stage (FFmpeg) to assemble those frames into an MP4.

That preserves the v2.6 rules:

Builder constructs immutable NJRs with a complete stage chain and resolved configs. 

CORE1-D Roadmap — History Integ…

Runner consumes NJR/RunPlan only and doesn’t re-resolve or infer. 

ARCHITECTURE_v2.6

No GUI prompt sourcing; PromptPack-only remains untouched. 

ARCHITECTURE_v2.6

 

PROMPT_PACK_LIFECYCLE_v2.6

How to incorporate AnimateDiff + Deforum (architecture shape)
Key design choice

Split “video” into two distinct stage responsibilities:

VideoFrames stage (optional)
Generates a sequence of frames. Backends:

webui_animatediff (A1111 extension via API payload / script invocation)

webui_deforum (Deforum API routes when enabled)

VideoRender stage (always available)
Assembles frames → MP4 (FFmpeg). This stage is deterministic and does not depend on WebUI.

This prevents “one stage that does everything,” keeps execution deterministic, and gives you graceful fallback:

If AnimateDiff/Deforum aren’t present: you can still do frames-from-images → render MP4.

If they are present: you can do img→frames via backend → render MP4.

Does it still use the WebUI API?

Yes — for AnimateDiff and Deforum, but in two different ways:

AnimateDiff: invoked through the A1111 API using an extension-driven payload (commonly via alwayson_scripts / script args patterns). This is inherently “extension-contract” territory, so it must be capability detected and schema-versioned in DebugHub/History.

Deforum: typically uses Deforum-specific API routes, which are available only when WebUI is launched with the Deforum API flag (commonly --deforum-api). So again: capability detection + gating.

Either way, StableNew’s Runner remains “pure consumer”: it just calls the backend adapter with the already-resolved parameters from NJR/RunPlan. 

ARCHITECTURE_v2.6

Metadata schema (PromptPack + NJR) that supports both
PromptPack JSON (defaults only; still immutable at runtime)

Add / standardize:

"video": {
  "enabled": false,
  "frames": {
    "enabled": false,
    "backend": "animatediff|deforum",
    "num_frames": 24,
    "fps": 12,
    "seed_mode": "inherit|fixed|random",
    "seed": null,
    "strength": 0.55,
    "backend_params": {}
  },
  "render": {
    "enabled": true,
    "container": "mp4",
    "codec": "libx264",
    "crf": 18,
    "preset": "medium",
    "keep_frames": false
  }
}

NJR mapping (canonical, immutable)

In NJR, represent this as two stage configs (preferred):

stage_chain: [..., {kind:"video_frames"}, {kind:"video_render"}]

Each stage has a typed config (Pydantic), not dict blobs, consistent with your “explicit data models only” rule. 

CORE1-D Roadmap — History Integ…

VideoFramesStageConfig

backend: WEBUI_ANIMATEDIFF | WEBUI_DEFORUM

num_frames, fps, seed rules, strength

backend_params (typed map with validation, but namespaced so you don’t leak extension-specific junk into global config)

VideoRenderStageConfig

container/codec/crf/preset

keep_frames

output naming

Config + GUI elements needed
Pipeline Tab / AppStateV2

Add a Video section that is strictly “config selection,” not prompt editing:

Enable Video

Enable “Generate frames via WebUI extension”

Backend dropdown: AnimateDiff / Deforum

Only enabled when capability detection confirms availability

Frames:

fps, num_frames, strength, seed mode

Render:

mp4/webm/gif, quality preset, keep_frames

This stays consistent with “GUI only manipulates AppStateV2.job_draft; Builder owns construction.” 

ARCHITECTURE_v2.6

How the chaining works (end-to-end)
Chain A — camera-motion / slideshow video (no WebUI dependency)

txt2img → upscale → video_render

render stage takes the set of images and turns them into a clip

Chain B — AnimateDiff (img→frames→clip)

txt2img (or img2img) → video_frames(backend=animatediff) → video_render

Chain C — Deforum (scripted motion)

txt2img (or img2img) → video_frames(backend=deforum) → video_render

RunPlan rule: the plan must explicitly state:

frame output directory for video_frames stage

final mp4 output path for video_render stage
No inference in Runner. 

ARCHITECTURE_v2.6

Updated roadmap (with AnimateDiff + Deforum)
Milestone 1 — Canonical stage model + schemas

Introduce video_frames and video_render stage kinds

Add typed configs + validation (illegal chains rejected at preview/build time)

Update DebugHub schema to show resolved video configs

Milestone 2 — FFmpeg render stage (always works)

Implement video_render execution using FFmpeg

Works with frames produced by any prior stage (including “static frames”)

Milestone 3 — WebUI capability detection

Query WebUI for available scripts/routes and cache capabilities

Gate UI options accordingly

Record capability snapshot into DebugHub (so history is explainable)

Milestone 4 — AnimateDiff backend adapter

Build WebUI request payload

Execute; save returned frames

Integrate with video_render

Milestone 5 — Deforum backend adapter

Call Deforum API endpoints (only if enabled)

Save returned frames (or returned video → optionally transcode)

Integrate with video_render

Milestone 6 — Golden Path tests

Add E2E: txt2img → video_render

Add integration tests for adapters with mocked WebUI responses

Capability-gated tests for AnimateDiff/Deforum (skipped if backend absent)

Dedicated PR set (small, deterministic)
PR-VID-001 — Video stage authorization + schema

Changes

Add video_frames, video_render stage kinds

Add typed config models

Add stage chain validation rules
Tests

Unit tests for valid/invalid chains

PR-VID-002 — VideoRender (FFmpeg) execution

Changes

Implement video_render runner stage using FFmpeg

Persist MP4 artifacts into history result
Tests

Runner integration test with mocked subprocess/ffmpeg wrapper

PR-VID-003 — GUI + AppStateV2 config plumbing

Changes

Video panel/card, config persistence

No prompt changes
Tests

GUI config round-trip + controller event API wiring

PR-VID-004 — WebUI capability detection service

Changes

Detect AnimateDiff + Deforum presence

Cache capabilities; expose to GUI/controller
Tests

API parsing tests; fallback behavior tests

PR-VID-005 — AnimateDiff adapter (capability-gated)

Changes

WebUI payload builder + executor path to frames

Save frames, call video_render
Tests

Payload structure test + runner adapter integration test (mock WebUI)

PR-VID-006 — Deforum adapter (capability-gated)

Changes

Deforum API client + executor path to frames/video

Normalize outputs into frames directory, call video_render
Tests

API client tests + runner integration tests (mock)

PR-VID-007 — Golden Path journeys

Changes

Add journey test for txt2img → video_render

Optional journeys for AnimateDiff/Deforum gated on capability
Tests

Journeys + pipeline suite