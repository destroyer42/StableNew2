# SDXL Enhanced Randomization Pack
Standardized to ALT_MOD baseline with layered randomization.
- Model: juggernautXL_ragnarokBy.safetensors [dd08fa32f9]
- Sampler: DPM++ 2M (Karras), Steps: 34, CFG: 6.1
- Hires Fix: OFF
- Upscale: 2.0x (4xUltrasharp_4xUltrasharpV10)
- ADetailer Face: face_yolov8n.pt | conf 0.69 | feather 8 | steps 12 | denoise 0.26 | cfg 6.0
- ADetailer Person (optional): person_yolov8n-seg.pt | conf 0.62 | feather 12 | steps 8 | denoise 0.15 | cfg 5.8

Randomization:
- Search/Replace (SR)
- Wildcards: __environment__, __mood__, __lighting__, __props__
- Matrix: hair, clothes, style, environment, lighting, camera

Prompts:
- _Realistic: adds <lora:epiCRealismHelper:0.6>
- _Fantasy: adds <lora:DreamyStyle_xl:0.7> and <lora:babesByStableYogiPony_xlV4:1.0>
