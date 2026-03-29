# Adaptive Scale- and Intent-Aware Refinement and Smart Prompting for StableNew

## Executive summary

StableNew v2.6 already has the correct backbone for an adaptive refinement system: an NJR-only execution contract, a single production runner entrypoint (`PipelineRunner.run_njr`), a canonical multi-stage image chain (`txt2img → img2img → adetailer → upscale`), and durable artifact/manifest + embedded-metadata infrastructure for reproducibility and learning. fileciteturn25file0L1-L1 fileciteturn11file0L1-L1 fileciteturn17file0L1-L1

The “faces look terrible when the subject is small / distant” failure you described is structurally addressable because StableNew already serializes stage execution and can branch per-image inside the stage loops (e.g., the runner loops each `current_stage_paths` image through ADetailer and upscale). fileciteturn11file0L1-L1 The missing piece is a deterministic, runner-owned decision layer that (a) analyzes the base render(s), (b) infers “what the user wanted,” and then (c) chooses stage-specific refinement policies (ADetailer knobs, upscale mode/strength, prompt tweaks, LoRA/embedding policy) while recording *exactly what it chose*, per-image, in manifests + learning records.

This report specifies a StableNew-owned, backend-agnostic feature set:

- **SubjectScalePolicyService**: per-image analysis → discrete “scale/pose bands” → per-stage policy selection (ADetailer/upscale/prompt rules).
- **PromptIntentAnalyzer**: prompt + PromptPack provenance → stable intent features (portrait vs full-body, profile/over-shoulder, people/no-people, realism/anime, etc.), leveraging existing prompt bucketing infrastructure. fileciteturn22file0L1-L1 fileciteturn24file0L1-L1
- **RefinementPolicy schema**: a versioned, serializable contract for decisions and the *applied* overrides (so replay and learning can reason about outcomes).
- **Detector wrapper**: a pluggable interface that supports “no heavy dependency” installs while enabling higher fidelity when optional extras (e.g., OpenCV) are present. StableNew’s `svd` optional dependency group already includes OpenCV and other vision libs, so we can reuse that capability without forcing it into the minimal install path. fileciteturn45file0L1-L1 fileciteturn44file0L1-L1
- **Replay + learning loop**: extend the existing learning record and recommendation engine so policies can be tuned using user ratings and derived quality metrics (e.g., face-crop sharpness), while staying within the v2.6 architecture invariants. fileciteturn14file0L1-L1 fileciteturn15file0L1-L1 fileciteturn25file0L1-L1

Suggested doc outputs (as future repo docs): `docs/PRD_ADAPTIVE_REFINEMENT_v2.6.md`, `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`, and `docs/PR-REFINE-###-Adaptive-Refinement-Implementation.md`.

## Current repo state analysis and existing seams

StableNew v2.6 explicitly defines: (a) NJR as the only executable job envelope, (b) queue-only fresh execution, and (c) `PipelineRunner.run_njr(...)` as the only production runner entrypoint. This is binding architecture and the new feature should attach at the runner/stage orchestration layer, not in GUI/controllers. fileciteturn25file0L1-L1

### Pipeline stages and where refinement hooks already exist

`PipelineRunner.run_njr` constructs a run plan from NJR (`build_run_plan_from_njr`) and then runs enabled stages in canonical order. fileciteturn11file0L1-L1 fileciteturn12file0L1-L1 Key points for the adaptive system:

- The runner maintains `current_stage_paths` and loops **each image** through downstream stages (`img2img`, `adetailer`, `upscale`). This makes per-image policy selection straightforward (no need to change the outer architecture). fileciteturn11file0L1-L1
- The runner flattens `StageConfig.extra` into stage configs (notably for ADetailer prompt fields and upscaler fields), which is exactly where a policy service can inject stage-specific overrides (using a copy-on-write config dict per image). fileciteturn11file0L1-L1 fileciteturn16file0L1-L1

StableNew’s multi-stage chain is already canonicalized and ordered by `build_run_plan_from_njr`, which sorts the stage chain by a canonical order map: `txt2img`, `img2img`, `adetailer`, `upscale` (plus video stages). fileciteturn12file0L1-L1

### PromptPack → NJR and prompt/LoRA/embedding provenance

`PromptPackNormalizedJobBuilder` is the main PromptPack builder that resolves pack rows and emits `NormalizedJobRecord` instances. It supplies:

- `positive_prompt`, `negative_prompt`
- `positive_embeddings`, `negative_embeddings` (rendered into textual references)
- `lora_tags`
- `stage_chain` computed from config + stage flags
- `intent_config` (currently canonicalized to a small key whitelist)
- `backend_options` derived from config fileciteturn16file0L1-L1

That means intent inference can be based on the **resolved prompts** and **explicit embedding/LoRA lists**, not fragile string parsing alone. fileciteturn16file0L1-L1 fileciteturn26file0L1-L1

### Existing prompt optimization infrastructure to build on

StableNew already has prompt classification and configurable prompt optimization/bucketing:

- Rule-based and score-based bucket classification (`prompt_classifier.py`) fileciteturn22file0L1-L1
- Default keyword buckets (including “full body”, “close-up”, “profile”) in `prompting_defaults.py` fileciteturn24file0L1-L1
- A robust comma splitter that respects parentheses/brackets and detects LoRA syntax (`prompt_splitter.py`) fileciteturn27file0L1-L1

So PromptIntentAnalyzer should reuse these, rather than inventing a parallel tokenization/classification system.

### ADetailer/upscale config surface and a concrete “missing faces” lever

StableNew already serializes and embeds exact ADetailer arguments into stage manifests (via `alwayson_scripts` payloads). The included diagnostic metadata example shows:

- `ad_mask_min_ratio` used to ignore small detections (0.01 in the sample)
- `ad_use_inpaint_width_height` currently disabled
- a face detector model like `mediapipe_face_full` fileciteturn42file0L1-L1

For “small/distant faces,” two parameters are especially relevant:

- **Lower `ad_mask_min_ratio`** so tiny faces aren’t filtered out.
- **Enable `ad_use_inpaint_width_height` selectively** so ADetailer can inpaint at a higher working resolution for small faces (but keep it off for big images or memory-risk conditions). fileciteturn42file0L1-L1

These are precisely the kinds of knobs that should be made adaptive based on detected bounding box size.

### Replay/metadata/learning infrastructure to reuse

StableNew’s image metadata contract v2.6 supports embedding a JSON payload, including stage history, stage manifest config hashes, prompts, and the NJR snapshot hash (`stablenew:njr_sha256`). fileciteturn17file0L1-L1

StableNew’s learning subsystem already persists `LearningRecord` entries with metadata and rating detail normalization, and includes a `RecommendationEngine` that consumes ratings to recommend parameter values. fileciteturn14file0L1-L1 fileciteturn15file0L1-L1

So the adaptive refinement feature should “plug into” learning by recording:

- detected scale/pose bands
- selected policy id
- applied stage overrides
- outcome metrics (auto)
- user rating (manual)

## Feature architecture and detailed module specifications

### Design goals and architectural constraints

This feature must comply with the v2.6 invariants:

- **Runner-owned orchestration** (no GUI/controller logic for backend policies).
- **NJR remains the only outer job contract**; any new config must be stored as NJR intent/config metadata, not a parallel job model. fileciteturn25file0L1-L1
- **Comfy/backends are not allowed to become public contracts**; the policy system must operate at StableNew’s orchestration layer and emit backend-neutral decisions. fileciteturn25file0L1-L1

### Proposed modules and file paths

Create a new domain package:

- `src/refinement/`
  - `subject_scale_policy_service.py`
  - `prompt_intent_analyzer.py`
  - `refinement_policy_models.py`
  - `refinement_policy_registry.py`
  - `detectors/base_detector.py`
  - `detectors/opencv_face_detector.py` (optional)
  - `detectors/null_detector.py`

Wire into:

- `src/pipeline/pipeline_runner.py` (policy invocation + per-image stage config mutation) fileciteturn11file0L1-L1
- `src/pipeline/config_contract_v26.py` (intent_config whitelist extension for refinement metadata) fileciteturn7file0L1-L1
- `src/pipeline/job_models_v2.py` (NJR snapshot inclusion strategy) fileciteturn6file0L1-L1
- `src/pipeline/executor.py` (optional: allow passing “analysis payload” into stage manifests cleanly) fileciteturn10file0L1-L1
- `src/learning/learning_record_builder.py` and/or runner learning hooks (to include policy context in learning metadata) fileciteturn14file0L1-L1

### Mermaid flow diagram for end-to-end data flow

```mermaid
flowchart TD
  A[PromptPack / UI Intent] --> B[PromptPackNormalizedJobBuilder]
  B --> C[NJR: prompt + embeddings + loras + stage_chain]
  C --> D[JobService Queue]
  D --> E[PipelineRunner.run_njr]

  E --> F[PromptIntentAnalyzer\n(prompt + pack metadata)]
  E --> G[Base Stage Execution\n(txt2img/img2img)]
  G --> H[Subject Detector Wrapper\n(bbox + pose)]
  F --> I[RefinementPolicySelector]
  H --> I
  I --> J[Per-stage Overrides\n(adetailer/upscale/prompt)]
  J --> K[Stage Execution Loops\nADetailer/upscale per image]
  K --> L[Manifests + Embedded Metadata]
  L --> M[Learning Record + Ratings]
  M --> N[RecommendationEngine / Auto-tuning]
```

### Core schemas and class signatures

#### `refinement_policy_models.py`

```python
# src/refinement/refinement_policy_models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ScaleBand = Literal["no_face", "micro", "small", "medium", "large"]
PoseBand = Literal["unknown", "frontal", "three_quarter", "profile"]
IntentBand = Literal["unknown", "portrait", "full_body", "group", "non_people"]

@dataclass(frozen=True, slots=True)
class SubjectDetection:
    detector_id: str
    confidence: float
    x: int
    y: int
    w: int
    h: int
    # Optional 5-point landmarks: (x, y) tuples
    landmarks5: tuple[tuple[int, int], ...] = ()

@dataclass(frozen=True, slots=True)
class SubjectScaleAssessment:
    image_path: str
    image_w: int
    image_h: int
    detections: tuple[SubjectDetection, ...] = ()
    primary_index: int | None = None

    face_area_ratio: float | None = None          # primary bbox area / image area
    face_height_ratio: float | None = None        # primary bbox h / image_h
    face_width_ratio: float | None = None         # primary bbox w / image_w
    scale_band: ScaleBand = "no_face"
    pose_band: PoseBand = "unknown"

    notes: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class PromptIntent:
    positive_prompt: str
    negative_prompt: str
    # key signals
    intent_band: IntentBand
    requested_pose: PoseBand
    wants_face_detail: bool
    wants_full_body: bool
    wants_profile: bool
    has_people_tokens: bool
    style_hint: str = "default"
    conflicts: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class StagePolicyDecision:
    stage_name: str
    policy_id: str
    overrides: dict[str, Any] = field(default_factory=dict)
    prompt_patch: dict[str, Any] = field(default_factory=dict)  # additions/removals/weighting
    rationale: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class RefinementDecisionBundle:
    schema: str  # "stablenew.refinement-decision.v1"
    algorithm_version: str  # e.g. "v1"
    prompt_intent: PromptIntent
    subject_assessment: SubjectScaleAssessment
    stage_decisions: tuple[StagePolicyDecision, ...] = ()
```

#### `prompt_intent_analyzer.py` built on existing prompt bucketing

Leverage existing classification primitives (`PromptBucketRules`, `classify_chunk_rule_based`, `split_prompt_chunks`) instead of re-implementing parsing. fileciteturn22file0L1-L1 fileciteturn23file0L1-L1 fileciteturn27file0L1-L1

```python
# src/refinement/prompt_intent_analyzer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.prompting.prompt_bucket_rules import build_default_prompt_bucket_rules
from src.prompting.prompt_classifier import classify_chunk_rule_based
from src.prompting.prompt_splitter import split_prompt_chunks
from src.utils.embedding_prompt_utils import extract_embedding_entries

from .refinement_policy_models import PoseBand, PromptIntent

@dataclass(frozen=True, slots=True)
class PromptIntentAnalyzerConfig:
    # thresholds and keyword sets can be extended via config later
    enable_conflict_detection: bool = True

class PromptIntentAnalyzer:
    def __init__(self, cfg: PromptIntentAnalyzerConfig | None = None) -> None:
        self._cfg = cfg or PromptIntentAnalyzerConfig()
        self._rules = build_default_prompt_bucket_rules()

    def infer(self, *, positive: str, negative: str, context: dict[str, Any] | None = None) -> PromptIntent:
        # 1) bucket chunks using existing rules
        chunks = split_prompt_chunks(positive)
        buckets = [classify_chunk_rule_based(c, "positive", self._rules) for c in chunks]

        # 2) detect “pose/composition scale” cues
        lower = positive.lower()
        wants_full_body = "full body" in lower
        wants_portrait = ("portrait" in lower) or ("close-up" in lower) or ("close up" in lower)
        wants_profile = ("profile" in lower) or ("side view" in lower) or ("over shoulder" in lower) or ("looking back" in lower)

        # 3) people presence heuristic aligned with RecommendationEngine people keywords concept
        has_people_tokens = any(tok in lower for tok in ("woman", "man", "person", "portrait", "face"))  # keep small set

        requested_pose: PoseBand = "profile" if wants_profile else ("frontal" if ("looking at viewer" in lower) else "unknown")

        # 4) face detail desire: embeddings/lora + explicit “detailed face/eyes” cues
        emb = extract_embedding_entries(positive)
        wants_face_detail = any("face" in name.lower() or "eye" in name.lower() for name, _w in emb) or ("detailed face" in lower)

        # 5) intent band selection
        intent_band = "non_people" if not has_people_tokens else ("full_body" if wants_full_body and not wants_portrait else "portrait")

        conflicts: list[str] = []
        if self._cfg.enable_conflict_detection:
            # Example conflict: asks for full body but overloads face/portrait tokens
            if wants_full_body and wants_portrait:
                conflicts.append("prompt_contains_full_body_and_portrait_tokens")

        return PromptIntent(
            positive_prompt=positive,
            negative_prompt=negative,
            intent_band=intent_band,
            requested_pose=requested_pose,
            wants_face_detail=wants_face_detail,
            wants_full_body=wants_full_body,
            wants_profile=wants_profile,
            has_people_tokens=has_people_tokens,
            style_hint="default",
            conflicts=tuple(conflicts),
        )
```

#### `subject_scale_policy_service.py` and detector wrapper

```python
# src/refinement/detectors/base_detector.py
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path

from ..refinement_policy_models import SubjectDetection

class SubjectDetector(ABC):
    detector_id: str

    @abstractmethod
    def detect_faces(self, image_path: Path) -> tuple[SubjectDetection, ...]:
        raise NotImplementedError
```

```python
# src/refinement/detectors/null_detector.py
from __future__ import annotations
from pathlib import Path

from .base_detector import SubjectDetector
from ..refinement_policy_models import SubjectDetection

class NullDetector(SubjectDetector):
    detector_id = "null"

    def detect_faces(self, image_path: Path) -> tuple[SubjectDetection, ...]:
        return ()
```

Optional OpenCV implementation should be behind a guarded import so the minimal install remains valid (StableNew’s default deps are intentionally small). fileciteturn44file0L1-L1 fileciteturn45file0L1-L1

```python
# src/refinement/detectors/opencv_face_detector.py
from __future__ import annotations
from pathlib import Path

from .base_detector import SubjectDetector
from ..refinement_policy_models import SubjectDetection

class OpenCvFaceDetector(SubjectDetector):
    detector_id = "opencv"

    def __init__(self) -> None:
        try:
            import cv2  # optional
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("OpenCV not available; install extras: stablenew[svd]") from exc
        self._cv2 = cv2
        # Implementation detail: load a model or use a built-in detector (to be chosen in implementation PR).

    def detect_faces(self, image_path: Path) -> tuple[SubjectDetection, ...]:
        # Return detections in image pixel coordinates
        raise NotImplementedError
```

Policy service ties it together:

```python
# src/refinement/subject_scale_policy_service.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .refinement_policy_models import (
    PromptIntent,
    RefinementDecisionBundle,
    ScaleBand,
    StagePolicyDecision,
    SubjectScaleAssessment,
)
from .refinement_policy_registry import RefinementPolicyRegistry
from .detectors.base_detector import SubjectDetector

@dataclass(frozen=True, slots=True)
class SubjectScalePolicyConfig:
    algorithm_version: str = "v1"
    # scale thresholds tuned later by learning loop
    micro_face_area_ratio: float = 0.004
    small_face_area_ratio: float = 0.012
    medium_face_area_ratio: float = 0.030
    # pose thresholds (proxy-based) also tunable
    profile_nose_offset_ratio: float = 0.16

class SubjectScalePolicyService:
    def __init__(
        self,
        *,
        detector: SubjectDetector,
        registry: RefinementPolicyRegistry,
        cfg: SubjectScalePolicyConfig | None = None,
    ) -> None:
        self._detector = detector
        self._registry = registry
        self._cfg = cfg or SubjectScalePolicyConfig()

    def assess(self, image_path: Path) -> SubjectScaleAssessment:
        with Image.open(image_path) as img:
            w, h = img.size

        dets = self._detector.detect_faces(image_path)

        if not dets:
            return SubjectScaleAssessment(
                image_path=str(image_path),
                image_w=w,
                image_h=h,
                detections=(),
                primary_index=None,
                face_area_ratio=None,
                face_height_ratio=None,
                face_width_ratio=None,
                scale_band="no_face",
                pose_band="unknown",
                notes=("no_face_detected",),
            )

        # Primary = largest area
        areas = [d.w * d.h for d in dets]
        primary_i = max(range(len(dets)), key=lambda i: areas[i])
        d = dets[primary_i]
        area_ratio = (d.w * d.h) / float(w * h)
        h_ratio = d.h / float(h)
        w_ratio = d.w / float(w)

        scale_band: ScaleBand
        if area_ratio < self._cfg.micro_face_area_ratio:
            scale_band = "micro"
        elif area_ratio < self._cfg.small_face_area_ratio:
            scale_band = "small"
        elif area_ratio < self._cfg.medium_face_area_ratio:
            scale_band = "medium"
        else:
            scale_band = "large"

        # pose_band: default “unknown” until landmark-based proxy is implemented
        pose_band = "unknown"

        return SubjectScaleAssessment(
            image_path=str(image_path),
            image_w=w,
            image_h=h,
            detections=dets,
            primary_index=primary_i,
            face_area_ratio=area_ratio,
            face_height_ratio=h_ratio,
            face_width_ratio=w_ratio,
            scale_band=scale_band,
            pose_band=pose_band,
            notes=(),
        )

    def decide_for_stage(
        self,
        *,
        stage_name: str,
        intent: PromptIntent,
        assessment: SubjectScaleAssessment,
        base_stage_config: dict[str, Any],
    ) -> StagePolicyDecision:
        policy = self._registry.select(stage_name=stage_name, intent=intent, assessment=assessment)
        overrides, prompt_patch, rationale = policy.compute_overrides(
            stage_name=stage_name,
            intent=intent,
            assessment=assessment,
            base_stage_config=base_stage_config,
        )
        return StagePolicyDecision(
            stage_name=stage_name,
            policy_id=policy.policy_id,
            overrides=overrides,
            prompt_patch=prompt_patch,
            rationale=tuple(rationale),
        )

    def build_bundle(
        self,
        *,
        intent: PromptIntent,
        assessment: SubjectScaleAssessment,
        stage_decisions: list[StagePolicyDecision],
    ) -> RefinementDecisionBundle:
        return RefinementDecisionBundle(
            schema="stablenew.refinement-decision.v1",
            algorithm_version=self._cfg.algorithm_version,
            prompt_intent=intent,
            subject_assessment=assessment,
            stage_decisions=tuple(stage_decisions),
        )
```

## Scale and pose algorithms with thresholds and policy banding

### Auto-selection logic based on bounding box size

Your immediate “auto-selection logic” can be specified as:

1. Detect face bounding boxes on the base render.
2. Compute *relative face size* metrics for primary face:
   - `face_area_ratio = bbox_area / image_area`
   - `face_height_ratio = bbox_h / image_h`
3. Map to a discrete `ScaleBand`, then select a policy preset for downstream stages.

The system should be designed so thresholds can be tuned and versioned (recorded in replay metadata). This aligns with StableNew’s contract layering: runner-owned decisions are allowed as long as they’re captured in NJR snapshot + manifests. fileciteturn25file0L1-L1 fileciteturn17file0L1-L1

### Baseline threshold bands

A practical initial set of bands (tunable later) that matches typical SDXL framing behaviors:

| Band | `face_area_ratio` (primary bbox) | Expected symptom if untreated |
|---|---:|---|
| `no_face` | no detection | no face to fix; avoid face-specific refinement |
| `micro` | `< 0.004` | face collapses into “blob” / no eyes, ADetailer often filters it out |
| `small` | `0.004 – 0.012` | eyes/mouth unstable; “over shoulder” faces fail frequently |
| `medium` | `0.012 – 0.030` | generally fixable with standard ADetailer |
| `large` | `> 0.030` | close-up/portrait; lighter denoise preserves identity |

Why these numbers: StableNew’s current ADetailer example uses `ad_mask_min_ratio=0.01` (1%), which would *discard* many “micro” and part of “small” faces. The adaptive system should lower that min ratio in those bands. fileciteturn42file0L1-L1

### Pose classification heuristics

Full head-pose estimation is optional; for v1, implement a two-layer approach:

- **Prompt-derived pose intent**: parse explicit tokens like “profile”, “over shoulder”, “looking back,” reusing the prompt parsing infrastructure. StableNew’s default positive keywords already include “profile,” and prompting is already structured to detect pose/composition tokens. fileciteturn24file0L1-L1 fileciteturn22file0L1-L1
- **Landmark proxy (optional, if detector yields landmarks)**: if a detector provides facial landmarks (5-point), compute a yaw proxy such as `nose_offset_ratio = abs(nose_x - eye_mid_x)/bbox_w`. Large offsets imply profile/three-quarter.

Initial banding:

- `frontal`: prompt doesn’t indicate profile **and** yaw proxy < 0.08
- `three_quarter`: yaw proxy 0.08–0.16
- `profile`: prompt indicates profile/over-shoulder **or** yaw proxy > 0.16

### Policy presets and expected effects

These presets are **runner-owned defaults** stored in a `RefinementPolicyRegistry` (not GUI state). They should be “named policies” so learning and replay can reason about them.

| Preset | When selected | Stage overrides (high-level) |
|---|---|---|
| `people_portrait_v1` | `intent=portrait` and `scale=large` | lower denoise, normal mask ratio, preserve expression |
| `people_fullbody_smallface_v1` | `intent=full_body` and `scale in {micro,small}` | lower `ad_mask_min_ratio`, possibly enable `ad_use_inpaint_width_height`, increase padding, slightly higher denoise |
| `people_profile_smallface_v1` | `intent` indicates profile/over-shoulder or `pose=profile` | lower detector confidence threshold, use a profile-friendly detector model if available, larger mask padding |
| `non_people_v1` | `intent=non_people` or `scale=no_face` | disable face ADetailer, disable face prompt patches |

Concrete ADetailer levers that StableNew already emits and records in manifests include: `ad_mask_min_ratio`, `ad_confidence`, `ad_inpaint_only_masked_padding`, and `ad_use_inpaint_width_height`. fileciteturn42file0L1-L1

## Smart prompting synergy design

### Intent extraction strategy

PromptIntentAnalyzer should produce stable features:

- **Scale intent**: portrait vs full-body vs wide shot
- **Pose intent**: frontal vs profile/over shoulder
- **People intent**: people present vs landscape/architecture
- **Face-detail preference**: whether prompt/embeddings indicate a desire for facial fidelity
- **Conflict tags**: “full_body + close-up,” “no people + face-refiner embedding,” etc.

Reuse existing prompt parsing and bucketing capabilities rather than introducing new parsing. fileciteturn27file0L1-L1 fileciteturn22file0L1-L1

### Conflict detection examples

Conflict detection should be based on provenance as much as text:

- Embeddings extracted via `extract_embedding_entries()` already provide structured embedding names. fileciteturn26file0L1-L1
- LoRA usage is visible both in `lora_tags` on NJR and by detecting `<lora:...>` syntax. fileciteturn16file0L1-L1 fileciteturn27file0L1-L1

Typical conflicts the system should flag (and record, not silently “fix” unless the user opted in):

- **Full-body intent** + a heavy “portrait/close-up” cluster (risk: model centers face, crops body).
- **Non-people intent** + face-specific embeddings (risk: wasted tokens or unintended faces).
- **Profile intent** + “looking at viewer” tokens (risk: inconsistent gaze/pose).

### Runtime prompt rewriting rules

The smart-prompt component should produce a *stage-scoped prompt patch* rather than mutating the canonical NJR prompt. Rationale: StableNew already records stage manifests and stage history; stage-scoped changes can be recorded as “patches” in those manifests without breaking the job envelope. fileciteturn17file0L1-L1

Proposed patch schema (stored in the decision bundle and copied into manifests):

```json
{
  "prompt_patch": {
    "add_positive": ["subtle skin texture", "stable eye alignment"],
    "remove_positive": ["close-up"],
    "add_negative": ["warped eyes", "misaligned pupils"],
    "remove_negative": [],
    "lora_weight_overrides": [{"name": "DetailedEyes_V3", "weight": 0.55}],
    "embedding_weight_overrides": [{"name": "face_refiner", "weight": 0.8}]
  }
}
```

Stage rules (illustrative, for v1):

- **ADetailer stage (face)**:
  - If `scale=micro/small`: add micro-face stabilizers (eye alignment, preserve structure), remove tokens that force extreme close-ups, *unless* user explicitly requested portrait.
  - If `pose=profile`: add “profile face, preserve original angle” cues, and avoid “looking at viewer.”
- **Upscale stage (img2img upscale mode)**:
  - If selected: add minimal “preserve composition” tokens and avoid reintroducing strong composition changes.

These patches should be merged *before* the existing prompt optimizer runs, so deduping and ordering remain consistent with StableNew’s prompt optimizer settings. fileciteturn24file0L1-L1

## Metadata, replay, and learning loop design

### Where to store policy inputs and decisions

To support replay and future automated tuning, store data in three places:

- **NJR intent_config**: user-facing toggle and policy profile selection (e.g., `adaptive_refinement_enabled`, `refinement_profile_id`, and a version id). StableNew currently filters intent_config keys via a whitelist; adding one nested key (e.g., `adaptive_refinement`) is the cleanest extension point. fileciteturn7file0L1-L1
- **Stage manifests + embedded metadata**: for each stage output, include the `RefinementDecisionBundle` (or a compact “bundle summary”) so the artifact is self-describing. StableNew’s embedded metadata payload already includes stage history and stage manifest config. fileciteturn17file0L1-L1
- **LearningRecord.metadata**: include `scale_band`, `pose_band`, `policy_id`, and outcome metrics so `RecommendationEngine` can stratify and recommend improvements. fileciteturn14file0L1-L1 fileciteturn15file0L1-L1

### Proposed intent_config addition (v2.6-compatible)

`src/pipeline/config_contract_v26.py` currently canonicalizes intent keys to a fixed set. Extend it by adding a single top-level key, e.g. `adaptive_refinement`, so the rest of the detail can live under that dict without expanding the whitelist repeatedly. fileciteturn7file0L1-L1

Example:

```json
{
  "intent_config": {
    "run_mode": "queue",
    "source": "add_to_queue",
    "prompt_source": "pack",
    "prompt_pack_id": "Beautiful_people_fullbody_PhotoMomentum_v26",
    "adaptive_refinement": {
      "schema": "stablenew.adaptive-refinement.v1",
      "enabled": true,
      "profile_id": "auto_v1",
      "algorithm_version": "v1",
      "detector_preference": "opencv",
      "record_full_decisions": true
    }
  }
}
```

### Stage manifest extension

StableNew stage manifests are already written and then embedded into images. The cleanest implementation is to add optional fields to the manifest writer (executor) so they get embedded automatically, rather than doing post-hoc JSON edits. fileciteturn17file0L1-L1

Add something like:

```json
{
  "adaptive_refinement": {
    "bundle_schema": "stablenew.refinement-decision.v1",
    "algorithm_version": "v1",
    "scale_band": "small",
    "pose_band": "profile",
    "policy_id": "people_profile_smallface_v1",
    "applied_overrides": {
      "ad_mask_min_ratio": 0.002,
      "ad_use_inpaint_width_height": true,
      "ad_inpaint_width": 768,
      "ad_inpaint_height": 768
    },
    "prompt_patch": { "...": "..." }
  }
}
```

This aligns with StableNew’s “artifacts/manifests enrich the contract” principle and preserves replay-ability without creating a second job model. fileciteturn25file0L1-L1

### Evaluation metrics and the learning loop

StableNew learning already supports:

- storing user rating + rating details in metadata
- analyzing records to recommend parameters via `RecommendationEngine`
- context-aware weighting including a “has_people” signal. fileciteturn15file0L1-L1 fileciteturn14file0L1-L1

To tune adaptive refinement policies, add:

- **Automatic metrics (cheap, local)**:
  - `face_detected`: bool
  - `face_area_ratio`: float
  - `face_crop_sharpness`: use Laplacian variance if OpenCV present; otherwise a PIL edge-energy proxy
  - `face_count`: number of detections
  - `pose_band`: from analyzer
- **Rating heuristics**:
  - If `has_people=True` (intent analyzer) and `face_detected=False` on final artifact, auto-flag “face failure” for review.
- **Automated tuning approach**:
  - v1: “banded grid” tuning (adjust `ad_mask_min_ratio`, `ad_confidence`, `ad_use_inpaint_width_height`) stratified by (`intent_band`, `scale_band`, `pose_band`).
  - v2: Bayesian optimization / bandits, where each policy preset is an “arm” and user ratings provide reward (safe because it operates only on StableNew-owned parameters, not backend internals).

Privacy/data retention: keep all learning data local and configurable (e.g., retention window, purging). This matches StableNew’s local-first architecture and avoids any backend-driven history model. fileciteturn25file0L1-L1

## Tests, CI architecture guards, and a PR plan

### Architecture guardrails to enforce

StableNew already has an AST-based test preventing GUI imports inside `src/utils`. fileciteturn39file0L1-L1 Use the same pattern to harden the adaptive refinement feature:

- `tests/refinement/test_no_gui_imports_in_refinement.py`  
  Blocklist: `tkinter`, `src.gui`, `src.gui_v2`, etc.
- `tests/gui_v2/test_no_refinement_detector_imports_in_gui.py`  
  Ensure GUI doesn’t import `src.refinement.detectors.*` directly (only through narrow controller/service ports).

### Functional tests to add

PipelineRunner is already tested with a stubbed Pipeline that records stage calls. fileciteturn46file0L1-L1 Add tests that assert:

- When a small face is detected, ADetailer stage config dict is overridden (e.g., lower `ad_mask_min_ratio`, enable `ad_use_inpaint_width_height`).
- When no face is detected, face refinement is disabled (or no face-specific prompt patch).
- Decisions are captured in per-stage result metadata (even if via a simplified placeholder in v1).

A low-fi approach for unit tests: monkeypatch `SubjectScalePolicyService.assess()` to return specific bands, so tests do not depend on OpenCV.

### Prioritized migration/implementation plan with concrete diffs

This plan keeps changes “shim-light” and aligned with v2.6 invariants.

#### PR one — Contracts and registries

- Add `src/refinement/*` files (models, registry, analyzer skeletons).
- Extend `config_contract_v26.py` to allow a single `adaptive_refinement` key in `intent_config`. fileciteturn7file0L1-L1
- Add tests for schema roundtrip and “no imports” guard.

Minimal illustrative diff (conceptual):

```diff
diff --git a/src/pipeline/config_contract_v26.py b/src/pipeline/config_contract_v26.py
@@
 _INTENT_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
   "run_mode",
   "source",
   "prompt_source",
   "prompt_pack_id",
+  "adaptive_refinement",
   "config_snapshot_id",
   "requested_job_label",
   "selected_row_ids",
   "tags",
   "pipeline_state_snapshot",
 })
```

#### PR two — Runner wiring (no heavy detector dependency)

- Instantiate `PromptIntentAnalyzer` once per job in `PipelineRunner.run_njr`.
- For each image entering `adetailer` and `upscale` loops, call policy service (assessment may be “null detector” initially).
- Apply stage overrides by merging into a copy of `config_dict` before stage calls.
- Record chosen policy id + bands into `variants` metadata (v1) and later into manifests (PR three). fileciteturn11file0L1-L1

#### PR three — Manifest/metadata integration

- Add an optional `extra_manifest_fields` or `analysis_payload` parameter to executor stage methods so runner can attach structured decision bundles to manifests before embedding. This ensures artifacts are self-describing using the existing metadata contract. fileciteturn17file0L1-L1

#### PR four — Optional detector enablement

- Implement `OpenCvFaceDetector` behind optional dependency guard; document install via `stablenew[svd]` (already present). fileciteturn45file0L1-L1
- Add integration test guarded by `pytest.importorskip("cv2")`.

#### PR five — Learning loop integration

- Extend learning record builder to include `scale_band`, `pose_band`, `policy_id`, and cheap quality metrics. fileciteturn14file0L1-L1
- Extend `RecommendationEngine` query context to stratify by those bands (without changing its evidence-tier logic). fileciteturn15file0L1-L1

### Short PR checklist for reviewers

- The change does not introduce a second runtime path: everything remains NJR → queue → `PipelineRunner.run_njr`. fileciteturn25file0L1-L1
- New policy decisions are runner-owned and recorded in manifests/learning records; no backend workflow JSON leaks into GUI/controller code.
- `intent_config` changes are minimal (single nested key) and remain canonicalized.
- Unit tests cover policy banding and stage override application (no dependency on OpenCV in base CI).
- Architecture guard tests prevent GUI imports into refinement/policy modules (pattern similar to existing utils guard). fileciteturn39file0L1-L1
- Replay story is explicit: policies are versioned and decisions are included in artifacts.

