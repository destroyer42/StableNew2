"""Help text definitions for Img2Img inpaint configuration options.

PR-GUI-TOOLTIPS-001: Comprehensive tooltips and inline help for Inpaint settings.
"""

from __future__ import annotations


# Inpaint help text dictionary
INPAINT_HELP_TEXT = {
    "mask_blur": {
        "short": "Blur amount applied to inpaint mask edges",
        "long": (
            "Blurs the edges of the inpaint mask to create a smoother transition "
            "between the inpainted area and the original image. Higher values create "
            "softer, more gradual transitions. Range: 0-64 pixels. Recommended: 4-8."
        ),
    },
    "inpaint_full_res": {
        "short": "Inpaint at full resolution vs masked area only",
        "long": (
            "When enabled, inpaints the entire image at full resolution. When disabled, "
            "only inpaints the masked region (faster but may have visible seams). "
            "Full resolution produces better quality but takes longer."
        ),
    },
    "inpaint_full_res_padding": {
        "short": "Padding around masked area when inpainting",
        "long": (
            "When 'Inpaint full res' is disabled, this adds padding pixels around "
            "the masked area to provide context for the inpaint algorithm. "
            "Higher values give more context but increase processing area. Range: 0-256 pixels."
        ),
    },
    "inpainting_fill": {
        "short": "Method for filling masked area before inpainting",
        "long": (
            "Determines how the masked area is initialized before the inpaint process. "
            "Options: 'Fill' (solid color), 'Original' (keep original pixels), "
            "'Latent noise' (random noise), 'Latent nothing' (zeros). "
            "Latent noise often produces the best results for creative inpainting."
        ),
    },
    "inpainting_mask_invert": {
        "short": "Invert the mask (paint outside instead of inside)",
        "long": (
            "When enabled, inverts the mask so that the inpaint affects everything "
            "EXCEPT the masked area. Useful when you want to preserve a specific "
            "region and regenerate everything around it."
        ),
    },
}


__all__ = ["INPAINT_HELP_TEXT"]
