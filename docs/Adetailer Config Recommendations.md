Below is what I’d use for SDXL full-body @ 768×1280, with 1–3 faces close enough to matter, and 2 ADetailer passes (faces → hands) via A1111’s API alwayson_scripts → ADetailer → args.

Key detail: the ADetailer wiki recommends explicitly including the first two args entries (ad_enable, skip_img2img) because omitting them can be “unpredictable.” 
GitHub

1) Minimal “mandatory but sane” ADetailer block (2 passes)

This is the ADetailer portion only (you’ll embed it under alwayson_scripts in the full payload):

{
  "ADetailer": {
    "args": [
      true,
      false,

      {
        "ad_model": "face_yolov8n.pt",
        "ad_tab_enable": true,

        "ad_confidence": 0.35,
        "ad_mask_filter_method": "Area",
        "ad_mask_k": 3,
        "ad_mask_min_ratio": 0.01,
        "ad_mask_max_ratio": 1.0,

        "ad_dilate_erode": 4,
        "ad_mask_blur": 4,
        "ad_mask_merge_invert": "None",

        "ad_inpaint_only_masked": true,
        "ad_inpaint_only_masked_padding": 32,

        "ad_use_steps": true,
        "ad_steps": 14,
        "ad_use_cfg_scale": true,
        "ad_cfg_scale": 5.5,
        "ad_denoising_strength": 0.32,

        "ad_use_sampler": true,
        "ad_sampler": "DPM++ 2M Karras",
        "ad_scheduler": "Use same scheduler",

        "ad_prompt": "natural skin texture, clear eyes, detailed eyelashes, subtle film grain",
        "ad_negative_prompt": "melted face, face mush, asymmetrical eyes, deformed nose, overexposed highlights"
      },

      {
        "ad_model": "hand_yolov8n.pt",
        "ad_tab_enable": true,

        "ad_confidence": 0.30,
        "ad_mask_filter_method": "Area",
        "ad_mask_k": 6,
        "ad_mask_min_ratio": 0.003,
        "ad_mask_max_ratio": 1.0,

        "ad_dilate_erode": 6,
        "ad_mask_blur": 4,
        "ad_mask_merge_invert": "None",

        "ad_inpaint_only_masked": true,
        "ad_inpaint_only_masked_padding": 16,

        "ad_use_steps": true,
        "ad_steps": 12,
        "ad_use_cfg_scale": true,
        "ad_cfg_scale": 5.0,
        "ad_denoising_strength": 0.25,

        "ad_use_sampler": true,
        "ad_sampler": "DPM++ 2M Karras",
        "ad_scheduler": "Use same scheduler",

        "ad_prompt": "well-formed fingers, natural knuckles, correct hand anatomy, sharp details",
        "ad_negative_prompt": "extra fingers, fused fingers, broken fingers, deformed hands, missing fingers"
      }
    ]
  }
}


Why these defaults are “safe” for your use case:

Face pass: mask_k=3 matches your “1–3 faces that matter” goal; min_ratio=0.01 filters tiny background detections. 
GitHub

Hands pass: lower denoise + modest steps reduces “new hands” artifacts, while mask_k=6 can catch up to ~2 hands × 3 people.

2) Full JSON payload example: /sdapi/v1/txt2img (SDXL @ 768×1280 + ADetailer)
{
  "prompt": "…your SDXL prompt…",
  "negative_prompt": "…your base negative…",

  "width": 768,
  "height": 1280,

  "steps": 30,
  "cfg_scale": 6.0,
  "sampler_name": "DPM++ 2M Karras",
  "scheduler": "Karras",
  "seed": -1,

  "alwayson_scripts": {
    "ADetailer": {
      "args": [
        true,
        false,

        {
          "ad_model": "face_yolov8n.pt",
          "ad_tab_enable": true,
          "ad_confidence": 0.35,
          "ad_mask_filter_method": "Area",
          "ad_mask_k": 3,
          "ad_mask_min_ratio": 0.01,
          "ad_mask_max_ratio": 1.0,
          "ad_dilate_erode": 4,
          "ad_mask_blur": 4,
          "ad_mask_merge_invert": "None",
          "ad_inpaint_only_masked": true,
          "ad_inpaint_only_masked_padding": 32,
          "ad_use_steps": true,
          "ad_steps": 14,
          "ad_use_cfg_scale": true,
          "ad_cfg_scale": 5.5,
          "ad_denoising_strength": 0.32,
          "ad_use_sampler": true,
          "ad_sampler": "DPM++ 2M Karras",
          "ad_scheduler": "Use same scheduler",
          "ad_prompt": "natural skin texture, clear eyes, detailed eyelashes, subtle film grain",
          "ad_negative_prompt": "melted face, face mush, asymmetrical eyes, deformed nose, overexposed highlights"
        },

        {
          "ad_model": "hand_yolov8n.pt",
          "ad_tab_enable": true,
          "ad_confidence": 0.30,
          "ad_mask_filter_method": "Area",
          "ad_mask_k": 6,
          "ad_mask_min_ratio": 0.003,
          "ad_mask_max_ratio": 1.0,
          "ad_dilate_erode": 6,
          "ad_mask_blur": 4,
          "ad_mask_merge_invert": "None",
          "ad_inpaint_only_masked": true,
          "ad_inpaint_only_masked_padding": 16,
          "ad_use_steps": true,
          "ad_steps": 12,
          "ad_use_cfg_scale": true,
          "ad_cfg_scale": 5.0,
          "ad_denoising_strength": 0.25,
          "ad_use_sampler": true,
          "ad_sampler": "DPM++ 2M Karras",
          "ad_scheduler": "Use same scheduler",
          "ad_prompt": "well-formed fingers, natural knuckles, correct hand anatomy, sharp details",
          "ad_negative_prompt": "extra fingers, fused fingers, broken fingers, deformed hands, missing fingers"
        }
      ]
    }
  }
}


The field names above (ad_model, ad_confidence, ad_mask_k, ad_mask_min_ratio, ad_denoising_strength, etc.) and the args structure are directly from the ADetailer REST API doc. 
GitHub

3) What the “manifest” could look like (stage record)

You didn’t specify a strict schema, so here’s a practical manifest shape that mirrors the kind of stage records you’ve been saving (stage name + timestamp + config snapshot), but with the ADetailer “two pass” config embedded.

{
  "name": "adetailer_20251224_231500_000",
  "stage": "adetailer",
  "timestamp": "20251224_231500",
  "input_image": "output/.../txt2img_20251224_231450_000.png",
  "output_image": "output/.../adetailer_20251224_231500_000.png",
  "config": {
    "width": 768,
    "height": 1280,
    "alwayson_scripts": {
      "ADetailer": {
        "args": [
          true,
          false,
          {
            "ad_model": "face_yolov8n.pt",
            "ad_tab_enable": true,
            "ad_confidence": 0.35,
            "ad_mask_filter_method": "Area",
            "ad_mask_k": 3,
            "ad_mask_min_ratio": 0.01,
            "ad_mask_max_ratio": 1.0,
            "ad_dilate_erode": 4,
            "ad_mask_blur": 4,
            "ad_mask_merge_invert": "None",
            "ad_inpaint_only_masked": true,
            "ad_inpaint_only_masked_padding": 32,
            "ad_use_steps": true,
            "ad_steps": 14,
            "ad_use_cfg_scale": true,
            "ad_cfg_scale": 5.5,
            "ad_denoising_strength": 0.32,
            "ad_use_sampler": true,
            "ad_sampler": "DPM++ 2M Karras",
            "ad_scheduler": "Use same scheduler",
            "ad_prompt": "natural skin texture, clear eyes, detailed eyelashes, subtle film grain",
            "ad_negative_prompt": "melted face, face mush, asymmetrical eyes, deformed nose, overexposed highlights"
          },
          {
            "ad_model": "hand_yolov8n.pt",
            "ad_tab_enable": true,
            "ad_confidence": 0.30,
            "ad_mask_filter_method": "Area",
            "ad_mask_k": 6,
            "ad_mask_min_ratio": 0.003,
            "ad_mask_max_ratio": 1.0,
            "ad_dilate_erode": 6,
            "ad_mask_blur": 4,
            "ad_mask_merge_invert": "None",
            "ad_inpaint_only_masked": true,
            "ad_inpaint_only_masked_padding": 16,
            "ad_use_steps": true,
            "ad_steps": 12,
            "ad_use_cfg_scale": true,
            "ad_cfg_scale": 5.0,
            "ad_denoising_strength": 0.25,
            "ad_use_sampler": true,
            "ad_sampler": "DPM++ 2M Karras",
            "ad_scheduler": "Use same scheduler",
            "ad_prompt": "well-formed fingers, natural knuckles, correct hand anatomy, sharp details",
            "ad_negative_prompt": "extra fingers, fused fingers, broken fingers, deformed hands, missing fingers"
          }
        ]
      }
    }
  }
}

Quick knobs you’ll likely tune (but these defaults are safe)

If it’s still hitting background faces: raise ad_mask_min_ratio on the face pass (e.g. 0.015) or increase ad_confidence.

If hands get “overfixed”: lower hand ad_denoising_strength to 0.20.