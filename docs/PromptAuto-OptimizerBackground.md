Here’s a practical prompt auto-optimizer algorithm for StableNew that reorganizes prompts into a stronger SDXL-friendly order before sending them to A1111.

It is designed to be:

deterministic

readable

easy to tune

safe by default

compatible with your PromptPack-style flow

Goal

Take a raw positive prompt like:

masterpiece, best quality, cinematic lighting, beautiful woman, japanese garden, autumn leaves, 85mm lens, natural skin texture, standing, photorealistic

and reorder it into:

beautiful woman, japanese garden, standing, autumn leaves, cinematic lighting, 85mm lens, natural skin texture, photorealistic, masterpiece, best quality

That gives you a stronger SDXL semantic order:

subject → environment → pose/composition → lighting → camera → detail/style → quality
High-level approach
Positive prompt

Split prompt into chunks

Normalize and classify each chunk into a semantic bucket

Preserve unknown chunks

Reassemble in priority order

Optionally deduplicate and lightly compress

Negative prompt

Split prompt into chunks

Classify into:

anatomy

artifact/render

composition

style blockers

text/watermark/logos

nsfw blockers or custom safety

Reassemble in stable negative order

Recommended bucket order for SDXL
Positive bucket order

subject

environment

pose_action

composition

lighting_atmosphere

camera_lens

material_surface_detail

style_medium

quality_tokens

leftover_unknown

Negative bucket order

anatomy_defects

face_hand_defects

render_artifacts

composition_defects

text_logo_watermark

style_blockers

leftover_unknown

Core algorithm design
Step 1: split prompt safely

You should split on commas, but preserve grouped phrases and weighted tokens when possible.

Examples to preserve:

(beautiful woman:1.2)

[dramatic lighting]

<lora:some_style:0.8>

85mm lens

natural skin texture

Step 2: normalize

For classification only:

lowercase

trim whitespace

collapse repeated spaces

But preserve original text for output.

Step 3: classify by rules

Use keyword heuristics, scored rules, and fallback.

A chunk like:

beautiful woman → subject

japanese garden → environment

looking at viewer → pose_action

soft cinematic lighting → lighting_atmosphere

85mm lens → camera_lens

photorealistic → style_medium

masterpiece → quality_tokens

Step 4: stable dedupe

Remove near-duplicates while keeping the strongest form.

Example:

beautiful woman

beautiful female

woman

Keep:

beautiful woman

Step 5: rebuild

Concatenate buckets in optimal order, keeping original phrasing and weights.

Practical Python implementation
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


POSITIVE_BUCKET_ORDER = [
    "subject",
    "environment",
    "pose_action",
    "composition",
    "lighting_atmosphere",
    "camera_lens",
    "material_surface_detail",
    "style_medium",
    "quality_tokens",
    "leftover_unknown",
]

NEGATIVE_BUCKET_ORDER = [
    "anatomy_defects",
    "face_hand_defects",
    "render_artifacts",
    "composition_defects",
    "text_logo_watermark",
    "style_blockers",
    "leftover_unknown",
]


@dataclass(slots=True)
class PromptOptimizationResult:
    original_prompt: str
    optimized_prompt: str
    buckets: Dict[str, List[str]] = field(default_factory=dict)
    dropped_duplicates: List[str] = field(default_factory=list)


class SDXLPromptOptimizer:
    """
    Rule-based SDXL prompt organizer for A1111 / StableNew.
    Safe default behavior:
    - preserve original chunk text
    - classify by normalized text
    - reorder only
    - optionally dedupe
    """

    def __init__(self) -> None:
        self.quality_keywords = {
            "masterpiece", "best quality", "ultra detailed", "high detail",
            "highly detailed", "8k", "4k", "absurdres", "sharp focus"
        }

        self.style_keywords = {
            "photorealistic", "realistic", "hyperrealistic", "cinematic",
            "film still", "digital painting", "oil painting", "anime",
            "illustration", "concept art", "3d render"
        }

        self.camera_keywords = {
            "85mm", "50mm", "35mm", "telephoto", "wide angle", "macro",
            "depth of field", "shallow depth of field", "bokeh",
            "professional photography", "dslr", "f/1.8", "f/2.8"
        }

        self.lighting_keywords = {
            "cinematic lighting", "soft lighting", "dramatic lighting",
            "rim lighting", "backlighting", "volumetric lighting",
            "sunset light", "golden hour", "studio lighting",
            "moody lighting", "warm glow", "volumetric atmosphere",
            "misty atmosphere", "fog", "ambient light"
        }

        self.pose_keywords = {
            "standing", "sitting", "walking", "running", "kneeling",
            "looking at viewer", "looking toward camera", "smiling",
            "full body", "upper body", "portrait", "close-up",
            "from side", "profile", "dynamic pose"
        }

        self.environment_keywords = {
            "garden", "forest", "street", "city", "temple", "room",
            "bedroom", "office", "castle", "beach", "mountains",
            "snow", "rain", "autumn", "maple trees", "stone path",
            "japanese garden", "background", "indoors", "outdoors"
        }

        self.material_keywords = {
            "natural skin texture", "detailed skin", "freckles",
            "hair detail", "fabric detail", "detailed eyes",
            "detailed face", "skin pores", "glossy", "matte"
        }

        self.subject_markers = {
            "woman", "man", "girl", "boy", "person", "female", "male",
            "soldier", "warrior", "knight", "doctor", "astronaut",
            "mother", "father", "child", "couple", "portrait of"
        }

        self.anatomy_negative = {
            "bad anatomy", "deformed", "mutated", "malformed",
            "extra limbs", "missing limbs", "extra arms", "extra legs",
            "long neck", "bad proportions", "twisted body"
        }

        self.face_hand_negative = {
            "bad hands", "extra fingers", "missing fingers", "mutated hands",
            "deformed hands", "bad face", "deformed face", "ugly face",
            "cross-eyed", "asymmetrical eyes", "bad eyes"
        }

        self.render_negative = {
            "blurry", "low quality", "jpeg artifacts", "artifact",
            "grainy", "noisy", "oversaturated", "overexposed",
            "underexposed", "washed out", "duplicate"
        }

        self.composition_negative = {
            "cropped", "out of frame", "cut off", "bad composition",
            "poor framing", "off center", "extra people", "multiple views"
        }

        self.text_negative = {
            "text", "watermark", "logo", "signature", "caption", "username"
        }

        self.style_blockers_negative = {
            "cartoon", "anime", "3d", "cgi", "painting", "sketch"
        }

    def optimize_positive(self, prompt: str, dedupe: bool = True) -> PromptOptimizationResult:
        chunks = self._split_prompt(prompt)
        buckets = {name: [] for name in POSITIVE_BUCKET_ORDER}
        dropped_duplicates: List[str] = []

        seen = OrderedDict()

        for chunk in chunks:
            original = chunk.strip()
            if not original:
                continue

            normalized = self._normalize_for_match(original)
            if dedupe:
                dedupe_key = self._dedupe_key(normalized)
                if dedupe_key in seen:
                    dropped_duplicates.append(original)
                    continue
                seen[dedupe_key] = original

            bucket = self._classify_positive(original)
            buckets[bucket].append(original)

        optimized = self._join_buckets(buckets, POSITIVE_BUCKET_ORDER)
        return PromptOptimizationResult(
            original_prompt=prompt,
            optimized_prompt=optimized,
            buckets=buckets,
            dropped_duplicates=dropped_duplicates,
        )

    def optimize_negative(self, prompt: str, dedupe: bool = True) -> PromptOptimizationResult:
        chunks = self._split_prompt(prompt)
        buckets = {name: [] for name in NEGATIVE_BUCKET_ORDER}
        dropped_duplicates: List[str] = []

        seen = OrderedDict()

        for chunk in chunks:
            original = chunk.strip()
            if not original:
                continue

            normalized = self._normalize_for_match(original)
            if dedupe:
                dedupe_key = self._dedupe_key(normalized)
                if dedupe_key in seen:
                    dropped_duplicates.append(original)
                    continue
                seen[dedupe_key] = original

            bucket = self._classify_negative(original)
            buckets[bucket].append(original)

        optimized = self._join_buckets(buckets, NEGATIVE_BUCKET_ORDER)
        return PromptOptimizationResult(
            original_prompt=prompt,
            optimized_prompt=optimized,
            buckets=buckets,
            dropped_duplicates=dropped_duplicates,
        )

    def optimize_pair(
        self,
        positive_prompt: str,
        negative_prompt: str,
        dedupe: bool = True,
    ) -> Tuple[PromptOptimizationResult, PromptOptimizationResult]:
        return (
            self.optimize_positive(positive_prompt, dedupe=dedupe),
            self.optimize_negative(negative_prompt, dedupe=dedupe),
        )

    def _split_prompt(self, prompt: str) -> List[str]:
        """
        Split on commas not inside (), [], <>.
        Good enough for most A1111 prompts with weights and LoRAs.
        """
        parts: List[str] = []
        current: List[str] = []
        depth_round = depth_square = depth_angle = 0

        for char in prompt:
            if char == "(":
                depth_round += 1
            elif char == ")":
                depth_round = max(0, depth_round - 1)
            elif char == "[":
                depth_square += 1
            elif char == "]":
                depth_square = max(0, depth_square - 1)
            elif char == "<":
                depth_angle += 1
            elif char == ">":
                depth_angle = max(0, depth_angle - 1)

            if char == "," and depth_round == 0 and depth_square == 0 and depth_angle == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            parts.append("".join(current).strip())

        return [p for p in parts if p]

    def _normalize_for_match(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def _dedupe_key(self, text: str) -> str:
        # remove weight syntax but preserve the concept
        text = re.sub(r"[\(\)\[\]]", "", text)
        text = re.sub(r":\s*\d+(\.\d+)?", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _contains_any(self, text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _classify_positive(self, chunk: str) -> str:
        text = self._normalize_for_match(chunk)

        # Keep LoRAs/control fragments late unless explicitly style-related
        if text.startswith("<lora:"):
            return "style_medium"

        if self._contains_any(text, self.subject_markers):
            return "subject"

        if self._contains_any(text, self.environment_keywords):
            return "environment"

        if self._contains_any(text, self.pose_keywords):
            return "pose_action"

        if any(term in text for term in {"rule of thirds", "centered", "symmetrical composition", "wide shot", "close shot"}):
            return "composition"

        if self._contains_any(text, self.lighting_keywords):
            return "lighting_atmosphere"

        if self._contains_any(text, self.camera_keywords):
            return "camera_lens"

        if self._contains_any(text, self.material_keywords):
            return "material_surface_detail"

        if self._contains_any(text, self.style_keywords):
            return "style_medium"

        if self._contains_any(text, self.quality_keywords):
            return "quality_tokens"

        return "leftover_unknown"

    def _classify_negative(self, chunk: str) -> str:
        text = self._normalize_for_match(chunk)

        if self._contains_any(text, self.anatomy_negative):
            return "anatomy_defects"

        if self._contains_any(text, self.face_hand_negative):
            return "face_hand_defects"

        if self._contains_any(text, self.render_negative):
            return "render_artifacts"

        if self._contains_any(text, self.composition_negative):
            return "composition_defects"

        if self._contains_any(text, self.text_negative):
            return "text_logo_watermark"

        if self._contains_any(text, self.style_blockers_negative):
            return "style_blockers"

        return "leftover_unknown"

    def _join_buckets(self, buckets: Dict[str, List[str]], order: List[str]) -> str:
        output: List[str] = []
        for bucket_name in order:
            output.extend(buckets.get(bucket_name, []))
        return ", ".join(output)
Example use
positive = (
    "masterpiece, best quality, cinematic lighting, beautiful woman, japanese garden, "
    "autumn maple trees, standing, looking toward camera, 85mm lens, natural skin texture, photorealistic"
)

negative = (
    "watermark, text, blurry, low quality, bad anatomy, bad hands, extra fingers, "
    "cropped, anime, cartoon"
)

optimizer = SDXLPromptOptimizer()
pos_result, neg_result = optimizer.optimize_pair(positive, negative)

print("POSITIVE:")
print(pos_result.optimized_prompt)
print()
print("NEGATIVE:")
print(neg_result.optimized_prompt)

Expected output:

POSITIVE:
beautiful woman, japanese garden, autumn maple trees, standing, looking toward camera, cinematic lighting, 85mm lens, natural skin texture, photorealistic, masterpiece, best quality

NEGATIVE:
bad anatomy, bad hands, extra fingers, blurry, low quality, cropped, watermark, text, anime, cartoon
How to use this in StableNew

The cleanest placement is:

PromptPack -> prompt build -> prompt optimize -> final payload -> A1111

So your flow becomes:

build positive prompt from PromptPack

build negative prompt from PromptPack

run optimizer

optionally compare original vs optimized

send optimized prompts to A1111

Safe production pattern

Use config flags so this is not always forced.

Example config:

{
  "prompt_optimizer": {
    "enabled": true,
    "dedupe": true,
    "optimize_positive": true,
    "optimize_negative": true,
    "preserve_lora_order": true,
    "max_prompt_chunks_warning": 2,
    "log_bucket_assignments": true
  }
}
Recommended extra rules for StableNew
1. Preserve LoRA placement

If your pipeline relies on LoRA ordering, you may want either:

keep LoRAs at the end, or

preserve original relative order of LoRAs only

Example helper logic:

if text.startswith("<lora:"):
    return "style_medium"

You could instead create a dedicated lora_tokens bucket placed just before quality_tokens.

2. Preserve weighted expressions

Do not rewrite:

(term:1.2)

[term]

<lora:name:0.8>

Only move them.

3. Optional “anchor boost”

You can optionally repeat the strongest subject term once if it is missing from the first bucket cluster.

Example:

first subject phrase appears only once and prompt is long

prepend strongest subject phrase again near front

This should be optional because it can overconstrain prompts.

Better version: score-based classification

The simple rules above are good enough to start.
A stronger version assigns weighted scores to each bucket.

Example idea:

def classify_with_scores(chunk: str) -> str:
    scores = {
        "subject": 0,
        "environment": 0,
        "pose_action": 0,
        ...
    }

    if "woman" in text:
        scores["subject"] += 3
    if "portrait of" in text:
        scores["subject"] += 4
    if "garden" in text:
        scores["environment"] += 3
    if "standing" in text:
        scores["pose_action"] += 2
    if "cinematic lighting" in text:
        scores["lighting_atmosphere"] += 4

    return max(scores, key=scores.get)

This helps with ambiguous phrases like:

cinematic portrait

dramatic full body shot

moody studio photo

Recommended output logging

For debugging, log both the original and optimized prompts.

Example:

logger.info("PROMPT OPTIMIZER ENABLED")
logger.info("Original positive: %s", positive_prompt[:400])
logger.info("Optimized positive: %s", optimized_positive[:400])
logger.info("Original negative: %s", negative_prompt[:400])
logger.info("Optimized negative: %s", optimized_negative[:400])
logger.debug("Positive buckets: %s", pos_result.buckets)
logger.debug("Negative buckets: %s", neg_result.buckets)

That makes it much easier to see whether the optimizer is helping or hurting.

Suggested StableNew file layout
src/
  prompting/
    sdxl_prompt_optimizer.py
    prompt_classifier_rules.py
    prompt_optimizer_config.py

Core public API:

def optimize_sdxl_prompts(
    positive_prompt: str,
    negative_prompt: str,
    enabled: bool = True,
    dedupe: bool = True,
) -> tuple[str, str]:
    ...

Example wrapper:

def optimize_sdxl_prompts(
    positive_prompt: str,
    negative_prompt: str,
    enabled: bool = True,
    dedupe: bool = True,
) -> tuple[str, str]:
    if not enabled:
        return positive_prompt, negative_prompt

    optimizer = SDXLPromptOptimizer()
    pos_result, neg_result = optimizer.optimize_pair(
        positive_prompt,
        negative_prompt,
        dedupe=dedupe,
    )
    return pos_result.optimized_prompt, neg_result.optimized_prompt
Important limitations

This kind of optimizer is useful, but it is not magic.

It can help with:

ordering

dedupe

cleaner SDXL semantic flow

It cannot reliably fix:

contradictory concepts

bad LoRA combinations

overstuffed prompt packs

model mismatch issues

Also, if your prompt system intentionally uses ordering tricks already, you should make this feature toggleable.

Best practical version for you

Given your StableNew setup, I would use this policy:

optimize only final merged prompt

preserve all exact token text

only reorder comma-delimited chunks

dedupe only obvious duplicates

log before/after

allow per-pipeline opt-out

That gives you a safe first implementation without breaking your existing PromptPack architecture.