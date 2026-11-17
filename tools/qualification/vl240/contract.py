"""AI-VL-240: constants, vocabulary and the refusal type of the Review label export.

Nothing here touches a file. Refusals carry a stable code and an opaque record id and never a path, prompt or note, so a
message, a log line or an exception from this package cannot reveal image content.
"""

from __future__ import annotations

SCHEMA = "stablenew.vl240.review_export/1"
MANIFEST_SCHEMA = "stablenew.vl240.image_manifest/1"
EXPORTER_VERSION = 2
DOCUMENT_NAME = "review_export.json"
MANIFEST_NAME = "manifest.json"
IMAGE_DIR = "images"
DEFAULT_OUTPUT_ROOT = r"D:\StableNew-Assets\offline-ai\visual-evaluation"

# Review's own finding taxonomy (``src.review.findings.Category`` and ``Action`` values). A test pins both lists to Review.
CATEGORIES: tuple[str, ...] = (
    "Face",
    "Hands",
    "Anatomy",
    "Composition",
    "Rendering artifact",
    "Prompt adherence",
    "General / local issue",
)
ACTIONS: tuple[str, ...] = (
    "Edit mask",
    "ADetailer face pass",
    "ADetailer hand pass",
    "Reprocess with img2img",
    "Inspect manually",
)

GUIDED_CORRECTION_SCHEMA = "stablenew.guided-correction.v1"
GUIDED_IMPROVEMENT_SCHEMA = "stablenew.guided-improvement-review.v1"
GUIDED_CORRECTION_KEY = "guided_correction"
GUIDED_IMPROVEMENT_KEY = "guided_improvement_review"

# Review's region outcome vocabulary (``VISUAL_OUTCOMES`` minus ``unreviewed``) in the roadmap's words.
OUTCOME_TO_JUDGMENT: dict[str, str] = {
    "improved": "helped",
    "unchanged": "no_benefit",
    "worsened": "worse",
    "uncertain": "inconclusive",
}
JUDGMENTS: tuple[str, ...] = (*OUTCOME_TO_JUDGMENT.values(), "mixed")
PREFERENCE_TO_VALUE: dict[str, str | None] = {
    "unreviewed": None,
    "prefer original": "prefer_original",
    "prefer result": "prefer_result",
    "no preference": "no_preference",
    "uncertain": "inconclusive",
}

# The Review inspection record (``src.review.review_evidence``); a test pins these to Review.
INSPECTION_SOURCE = "review_tab_inspection"
SEVERITIES: tuple[str, ...] = ("minor", "major")
SUBJECT_COUNT_BUCKETS: tuple[str, ...] = ("1", "2", "3", "4", "5_or_more")

MODE_SFW = "sfw"
MODE_NSFW = "nsfw"
VISIBILITY_MODES: tuple[str, ...] = (MODE_SFW, MODE_NSFW)

IMAGE_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
FORMAT_EXTENSIONS: dict[str, str] = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
MAX_IMAGE_BYTES = 64 * 1024**2
MAX_IMAGE_PIXELS = 64_000_000
MAX_CANDIDATES_PER_JOB = 48
MAX_REFUSALS_LISTED = 500

# Where each label comes from, and what Review still cannot record. Each entry is exported verbatim so a consumer never has
# to infer an absence. ``review_inspection`` rows are the operator's "Save inspection" in Inspect & Improve (AI-VL-243).
AVAILABILITY: dict[str, str] = {
    "findings": "queued_guided_correction_or_saved_inspection",
    "clean_confirmed": "saved_inspection_no_defect_seen_only",
    "severity": "optional_in_saved_inspection",
    "subject_count": "optional_in_saved_inspection",
    "model_family": "not_recorded_in_review_evidence",
    "prompt_adherence_elements": "not_recorded_by_review",
    "pair_judgment": "recorded_with_both_file_digests",
}

# Target counts for the first useful set and the pilot. ``recordable`` is whether Review can produce the label at all.
TARGETS: dict[str, dict[str, dict[str, int | bool]]] = {
    "full": {
        "clean_confirmed_images": {"target": 20, "recordable": True},
        "defect_images": {"target": 30, "recordable": True},
        "defect_images_hands": {"target": 8, "recordable": True},
        "defect_images_anatomy": {"target": 8, "recordable": True},
        "defect_images_face": {"target": 8, "recordable": True},
        "multi_subject_images": {"target": 10, "recordable": True},
        "judged_pairs": {"target": 12, "recordable": True},
    },
    "pilot": {
        "clean_confirmed_images": {"target": 10, "recordable": True},
        "defect_images": {"target": 15, "recordable": True},
        "defect_images_hands": {"target": 4, "recordable": True},
        "defect_images_anatomy": {"target": 4, "recordable": True},
        "defect_images_face": {"target": 4, "recordable": True},
        "multi_subject_images": {"target": 5, "recordable": True},
        "judged_pairs": {"target": 6, "recordable": True},
    },
}
CATEGORY_TARGET: dict[str, str] = {
    "Hands": "defect_images_hands",
    "Anatomy": "defect_images_anatomy",
    "Face": "defect_images_face",
}


class Refused(Exception):
    """A record or a request the exporter will not use. ``str()`` is the code, never content."""

    def __init__(self, code: str, record_id: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.record_id = record_id

    def __str__(self) -> str:
        return self.code
