"""Help text definitions for ADetailer configuration options.

PR-GUI-TOOLTIPS-001: Comprehensive tooltips and inline help for ADetailer.
"""

from __future__ import annotations


# ADetailer help text dictionary
# Format: "key": {"short": "Brief one-line description", "long": "Detailed hover tooltip"}
ADETAILER_HELP_TEXT = {
    "confidence": {
        "short": "Detection confidence threshold",
        "long": (
            "Minimum confidence score (0.1-1.0) required for face/object detection. "
            "Higher values reduce false positives but may miss some faces. "
            "Recommended: 0.3-0.4 for faces, 0.5+ for stricter detection."
        ),
    },
    "max_detections": {
        "short": "Maximum number of detections per image",
        "long": (
            "Limits how many faces/objects will be detected and processed in a single image. "
            "Useful for performance control and avoiding over-processing. "
            "Set to 1-3 for portraits, higher (5-10) for group photos."
        ),
    },
    "mask_blur": {
        "short": "Blur amount applied to detection mask edges",
        "long": (
            "Blurs the edges of the detection mask to create a smoother transition "
            "between the refined area and the original image. Higher values create "
            "softer, more gradual transitions. Range: 0-64 pixels. Recommended: 4-8."
        ),
    },
    "mask_merge_mode": {
        "short": "How multiple masks are combined",
        "long": (
            "Determines how overlapping detection masks are merged when multiple "
            "faces/objects are found. 'None' keeps masks separate, 'Merge' combines "
            "overlapping regions, 'Merge and Invert' inverts the final merged mask."
        ),
    },
    "filter_method": {
        "short": "Algorithm for filtering detected masks",
        "long": (
            "Selects the algorithm used to refine which detections to keep based on "
            "size, aspect ratio, and other criteria. Different methods work better "
            "for different types of images and detection scenarios."
        ),
    },
    "max_k": {
        "short": "Maximum K value for mask filtering",
        "long": (
            "Maximum threshold parameter used by the selected filter method. "
            "Controls the upper bound of the filtering criteria. Exact behavior "
            "depends on the chosen filter_method."
        ),
    },
    "min_ratio": {
        "short": "Minimum aspect ratio for detected masks",
        "long": (
            "Filters out detection masks with aspect ratios below this threshold. "
            "Helps eliminate false positives from elongated or oddly-shaped detections. "
            "Range: 0.0-1.0. Lower values are more permissive."
        ),
    },
    "max_ratio": {
        "short": "Maximum aspect ratio for detected masks",
        "long": (
            "Filters out detection masks with aspect ratios above this threshold. "
            "Helps eliminate false positives from extremely wide or tall detections. "
            "Range: 0.0-10.0. Higher values are more permissive."
        ),
    },
    "dilate_erode": {
        "short": "Expand or shrink detection masks",
        "long": (
            "Dilates (expands) or erodes (shrinks) the detection mask. Positive values "
            "expand the mask to include more surrounding area, negative values shrink "
            "the mask. Useful for adjusting mask boundaries. Range: -128 to +128 pixels."
        ),
    },
    "feather": {
        "short": "Edge feathering amount",
        "long": (
            "Applies feathering (gradual fade) to the mask edges for smoother blending. "
            "Higher values create softer, more gradual transitions between the refined "
            "area and original image. Range: 0-64 pixels. Recommended: 2-8."
        ),
    },
}


__all__ = ["ADETAILER_HELP_TEXT"]
