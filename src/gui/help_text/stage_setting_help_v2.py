"""Centralized operator help text for stage-card and video setting tooltips.

PR-UX-267: Expand in-product setting guidance across stage cards and related
video settings surfaces.
"""

from __future__ import annotations


BASE_GENERATION_SETTING_HELP = {
    "model": "Chooses the checkpoint used as the generation baseline. Switch models when style, anatomy, or composition bias is wrong for the prompt. Model changes usually have the largest quality and compatibility impact.",
    "vae": "Controls the VAE used for encode and decode. Leave this on the model default unless colors or contrast look wrong, or a workflow explicitly requires a matching VAE.",
    "sampler": "Chooses the denoising algorithm. Change it when images feel too soft, too brittle, or composition drifts. Euler variants are fast baselines; DPM++ variants usually trade a little speed for cleaner detail.",
    "scheduler": "Adjusts how the sampler distributes noise over the run. Karras-style schedules often help smoothness and detail, while other schedules can preserve different texture or timing characteristics.",
    "steps": "Sets how many denoising steps are used. Raising it can improve coherence and detail up to a point, but it also costs time. Around 20-35 is a common safe range for most general image work.",
    "cfg": "Classifier-Free Guidance strength. Raise it when the image ignores the prompt, lower it when results look overcooked or unnatural. Around 5-9 is a common safe range for balanced prompting.",
    "preset": "A convenience shortcut for common width and height pairs. Width and Height still remain authoritative, so use presets to start quickly and then fine-tune dimensions directly if needed.",
    "width": "Final generation width in pixels. Higher values can improve detail but increase memory use and runtime. Keep dimensions aligned to model-friendly multiples, typically 64 or 128 depending on the workflow.",
    "height": "Final generation height in pixels. Taller or wider aspect ratios change composition pressure as well as cost, so adjust it alongside Width instead of treating it as a cosmetic afterthought.",
    "seed": "Controls reproducibility. Leave blank or use -1 for a fresh random seed; reuse a fixed value when you want to compare config changes against the same composition baseline.",
    "subseed": "Optional secondary seed used for controlled variation. Leave blank or -1 to disable it; use it when you want related alternatives without fully abandoning the original seed direction.",
    "subseed_strength": "Blends between the main seed and subseed. Low values keep the original composition mostly intact, while higher values allow stronger variation. Around 0.1-0.4 is a practical exploratory range.",
}

TXT2IMG_SETTING_HELP = {
    "model": BASE_GENERATION_SETTING_HELP["model"],
    "vae": BASE_GENERATION_SETTING_HELP["vae"],
    "sampler": BASE_GENERATION_SETTING_HELP["sampler"],
    "steps": BASE_GENERATION_SETTING_HELP["steps"],
    "cfg": BASE_GENERATION_SETTING_HELP["cfg"],
    "clip_skip": "Skips later text-encoder layers before prompt conditioning. Raise it only when a model or LoRA expects it; otherwise keep the default because the wrong value can reduce prompt fidelity or produce odd styling.",
    "final_size": "Read-only preview of the size that will actually be rendered after hires-related multipliers are applied. Use this to catch accidental oversized outputs before queueing work.",
    "refiner_enabled": "Turns on the SDXL refiner pass. Enable it when you want an extra late-stage polish pass, but expect additional runtime and make sure the selected model family supports the refiner flow.",
    "refiner_model": "Selects the refiner checkpoint. Usually keep it matched to the base SDXL family unless you intentionally want a different final-detail bias.",
    "refiner_start": "Controls how late the refiner takes over. Higher values keep more of the base model structure; lower values hand off earlier for stronger refiner influence. Around 70%-85% is a practical default-safe zone.",
    "hires_enabled": "Turns on a second upscale-and-redetail pass. Use it when the base render is good but needs more final resolution or cleaner fine detail, knowing that it increases time and memory pressure.",
    "hires_upscaler": "Chooses how the latent or image upscale is performed before the hires pass. Different upscalers trade speed, sharpness, and texture preservation differently.",
    "hires_model": "Optional model override for the hires pass. Keep it on the base model unless you intentionally want the second pass to impose a different style or detail bias.",
    "hires_factor": "Multiplier applied before the hires pass. Larger values produce more pixels and more cost. Around 1.5x-2.0x is a common safe range before artifacts and runtime start climbing sharply.",
    "hires_steps": "Extra denoising steps for the hires pass. Raise it when the upscale looks under-resolved, but avoid pushing it too high because the second pass can drift or waste time.",
    "hires_denoise": "How aggressively the hires pass is allowed to redraw content. Lower values preserve the original composition; higher values can add detail but also alter pose, face, or clothing structure. Around 0.2-0.4 is a common safe band.",
    "hires_use_base_model": "When enabled, the hires pass keeps using the base checkpoint. Disable it only when you deliberately want the hires pass to use a separate model override.",
}

IMG2IMG_SETTING_HELP = {
    "sampler": BASE_GENERATION_SETTING_HELP["sampler"],
    "steps": BASE_GENERATION_SETTING_HELP["steps"],
    "cfg": BASE_GENERATION_SETTING_HELP["cfg"],
    "denoise": "How far img2img is allowed to move away from the source image. Lower values preserve structure and pose; higher values allow stronger reinterpretation but raise the risk of losing the original image identity. Around 0.2-0.45 is a common safe range.",
    "mask_mode": "Controls how masked or unmasked regions are treated during img2img work. Use conservative modes when preserving surrounding context matters, and broader modes when you want stronger regeneration.",
    "width": BASE_GENERATION_SETTING_HELP["width"],
    "height": BASE_GENERATION_SETTING_HELP["height"],
}

UPSCALE_SETTING_HELP = {
    "upscaler": "Chooses the upscale engine. Different upscalers trade speed, texture reconstruction, and artifact risk differently, so change this when the default result is too soft or too synthetic.",
    "mode": "Controls whether upscale jobs are handled as one-off or batched behavior. Confirm this before queueing because it affects throughput and how the destination workflow should be interpreted.",
    "steps": "Denoising steps used during upscale refinement. More steps can improve cleanup and texture rebuild, but they increase runtime and can overprocess a strong starting image.",
    "denoise": "How much the upscale pass is allowed to redraw details. Lower values preserve the input more closely; higher values can improve texture but also risk changing identity or introducing artifacts.",
    "scale": "Overall upscale multiplier. Higher factors increase output size and memory cost quickly, so confirm the final size before queueing. Around 1.5x-2.0x is a common safe starting point.",
    "tile_size": "Tile size for tiled upscale workflows. Larger tiles can preserve continuity but cost more memory; smaller tiles are safer on VRAM but can introduce seam-related artifacts if pushed too low.",
    "sampler": BASE_GENERATION_SETTING_HELP["sampler"],
    "scheduler": BASE_GENERATION_SETTING_HELP["scheduler"],
    "face_restore": "Enables a face-restoration pass after upscale. Use it when faces soften or break during enlargement, but review results carefully because restoration tools can oversmooth or alter expression.",
    "face_restore_method": "Chooses the face-restoration backend. CodeFormer often preserves more identity control, while GFPGAN can be stronger at aggressive cleanup.",
    "final_size": "Read-only final size preview after the current scale factor is applied. Use it to catch accidental oversized outputs before you queue the upscale job.",
}

ADETAILER_STAGE_HELP = {
    "stage_model_override": "Optional checkpoint override for the ADetailer stage. Leave this inherited from Base Generation unless the cleanup pass needs a different specialist model.",
    "face_pass_enabled": "Turns the face cleanup pass on or off. Disable it when faces already look stable and you want to avoid extra processing time or unintended redraws.",
    "hand_pass_enabled": "Turns the hand cleanup pass on or off. Enable it when hands need correction, but leave it off for images where hand artifacts are not the primary problem.",
    "detector_model": "Chooses the detector used to find faces or hands before inpaint cleanup. Change it when detections are unreliable or the current model misses the intended targets.",
    "sampler": BASE_GENERATION_SETTING_HELP["sampler"],
    "scheduler": BASE_GENERATION_SETTING_HELP["scheduler"],
    "confidence": "Minimum detection confidence before ADetailer accepts a face or hand region. Raise it to reduce false positives, lower it if the target region is being missed. Around 0.3-0.5 is a common practical range.",
    "steps": BASE_GENERATION_SETTING_HELP["steps"],
    "cfg": BASE_GENERATION_SETTING_HELP["cfg"],
    "denoising": "How strongly the detected region is regenerated. Lower values preserve the original region more closely; higher values can fix more issues but also change identity or shape.",
    "padding": "Expands the inpaint area around the detection. Increase it when the cleanup needs more surrounding context, but keep it conservative to avoid touching unrelated regions.",
    "mask_blur": "Softens the mask edge before the pass blends back in. Slight blur usually reduces harsh seams; too much can wash cleanup into nearby details.",
    "mask_feather": "Adds extra edge feathering for smoother blend transitions. Useful when the cleanup region looks cut out, but high values can make fixes too diffuse.",
    "dilate_erode": "Expands or shrinks the mask before inpaint. Positive values cover more area; negative values tighten the region. Use it when the auto mask is slightly too tight or too loose.",
    "max_detections": "Upper limit on how many regions ADetailer will process. Lower it for portraits or speed-sensitive runs; raise it only when multiple valid targets must be cleaned in one image.",
    "mask_filter": "Controls which detected masks survive filtering. Use stricter filtering when false positives are common, and more permissive filtering when valid targets are being discarded.",
    "mask_merge": "Determines how multiple detections are combined before cleanup. Merge options can simplify overlapping regions, while keeping masks separate is safer when targets should stay isolated.",
    "mask_max_k": "Caps how many filtered masks survive when mask filtering is active. Lower values keep the pass focused; higher values allow more regions through at the cost of extra processing.",
    "mask_min_ratio": "Minimum size ratio allowed for a detected mask. Raise it to ignore tiny false positives; lower it if legitimate small targets are being skipped.",
    "mask_max_ratio": "Maximum size ratio allowed for a detected mask. Lower it when oversized masks are swallowing too much of the image; raise it when large target regions are being filtered out.",
    "inpaint_width": "Explicit width for the inpaint pass when inpaint dimensions are enabled. Increase it for more detail inside the cleaned region, but watch VRAM and consistency.",
    "inpaint_height": "Explicit height for the inpaint pass when inpaint dimensions are enabled. Pair it with Inpaint Width to control cleanup resolution rather than leaving it fully inherited.",
    "only_masked": "Restricts regeneration to the masked area. Keep it enabled when you want localized cleanup with minimal collateral redraw.",
    "use_inpaint_wh": "Lets ADetailer use its own inpaint width and height instead of inheriting the stage defaults. Turn it on only when the cleanup region needs a different working resolution.",
    "prompt": "Positive prompt override used only for this pass. Add it when the cleanup pass needs stronger local guidance than the main stage prompt provides.",
    "negative": "Negative prompt override used only for this pass. Use it to suppress repeated local defects such as extra fingers, bad eyes, or muddy skin texture.",
}

SVD_SETTING_HELP = {
    "preset": "Applies a tested group of SVD settings for a common outcome. Use presets as a safe starting point, then deviate only when you know which motion or postprocess behavior needs to change.",
    "model": "Chooses the SVD model variant. XT-style models usually give stronger quality but cost more, while lighter variants are useful when you want faster experiments.",
    "frames": "Total frame count in the generated clip. More frames increase clip length and cost; shorter runs are safer for previews and faster iteration.",
    "fps": "Playback speed of the exported clip. Higher FPS makes the output play faster and smoother if enough frames exist, while lower FPS stretches the same motion over more time.",
    "motion_bucket": "Controls how much motion SVD is encouraged to add. Lower values tend to keep motion subtle and more realistic; higher values push stronger movement but increase artifact and drift risk. Around 40-90 is a practical safe band for realism-first work.",
    "noise_aug": "Noise augmentation strength before motion generation. Lower values preserve the source image more faithfully; higher values can help stylized movement but increase instability.",
    "inference_steps": "Sampling steps used for the video generation pass. More steps can improve quality and consistency, but they also increase runtime quickly.",
    "seed": BASE_GENERATION_SETTING_HELP["seed"],
    "target_size": "Target canvas preset for the animated output. Use it to match downstream clip needs and to avoid stretching the source unexpectedly.",
    "resize_mode": "How the source image is fit into the target size. Choose crop-oriented modes when composition matters most, and letterbox-like modes when preserving the entire source frame matters more.",
    "output": "Selects whether SVD exports a video file, GIF, or raw frames. This changes packaging and downstream usability, not the core motion generation itself.",
    "route": "Controls where the produced artifacts are routed for follow-up work. Pick the route that matches whether you want reprocess-style follow-up, dedicated SVD output review, or test isolation.",
    "decode_chunk": "Chunk size used while decoding frames. Higher values may improve throughput on strong hardware, but smaller values are safer when memory is limited.",
    "save_frames": "Keeps the individual generated frames on disk in addition to packaged outputs. Enable it when you need later inspection or clip assembly, disable it when you only want the final packaged result.",
    "cpu_offload": "Moves more model work to CPU to reduce VRAM pressure. This is safer on constrained GPUs but usually slows the run.",
    "forward_chunking": "Breaks some forward passes into smaller chunks. Enable it when memory is tight; disable it only if you need maximum throughput and your hardware can handle it.",
    "local_files_only": "Prevents remote model downloads and only uses files already available locally. Keep it enabled for deterministic offline work or when avoiding accidental network fetches matters.",
    "cache_dir": "Directory where SVD model files are cached. Change it only when storage layout or manual model management requires a different location.",
    "face_cleanup": "Runs an optional face restoration cleanup after SVD output. Useful when faces soften during animation, but review carefully because cleanup tools can alter expression or identity.",
    "face_method": "Chooses the face-cleanup backend. Use the method that best matches the tradeoff you want between preservation and aggressive repair.",
    "face_fidelity": "How strongly the face cleanup should preserve source identity versus aggressively correcting defects. Midrange values are safest until you know the subject tolerates stronger cleanup.",
    "rife_interpolate": "Enables frame interpolation after SVD generation. Use it when the clip needs smoother playback, knowing it adds processing time and can hallucinate motion between frames.",
    "rife_multiplier": "How many in-between frames RIFE should synthesize. Higher multipliers smooth motion more, but they also increase processing time and interpolation artifact risk.",
    "rife_exe": "Path to the RIFE executable used for interpolation. Set it only when local post-processing is available and you want interpolation in this workflow.",
    "upscale_frames": "Upscales generated frames after motion generation. Use it when final delivery size matters more than raw turnaround speed.",
}

VIDEO_WORKFLOW_SETTING_HELP = {
    "workflow": "Chooses the authored workflow recipe that will drive the video job. This is the main intent selector, so change it when the clip structure or supported capabilities need to change, not just when you want more or less motion.",
    "end_anchor": "Optional image that the sequence should move toward. Use it only for workflows designed to honor end-state guidance.",
    "mid_anchors": "Optional semicolon-separated guide images for intermediate beats. Add them when a workflow supports staged transitions and the sequence needs stronger structural guidance across time.",
    "motion": "High-level motion intensity profile. Gentle preserves realism best, balanced is a safer default for general motion, and dynamic pushes stronger movement with more drift risk.",
    "output_route": "Controls where the resulting workflow artifacts are routed for follow-up work. Choose the route that best matches whether the next step is review/reprocess or clip assembly.",
    "camera_preset": "Structured camera-intent preset passed into conditioned workflows. Leave it on none for unconditioned runs, or choose a preset when the workflow should bias movement toward a specific cinematic camera move.",
    "camera_strength": "How strongly the selected camera intent should influence the workflow. Lower values keep the original anchor structure more intact; higher values push the authored camera move harder and increase drift risk.",
    "depth_mode": "Controls how depth conditioning is resolved. None keeps the legacy workflow behavior, upload uses an operator-supplied depth map, and auto generates a depth map locally before the workflow is compiled.",
    "depth_path": "Path to an uploaded depth image used when Depth Source is set to upload. The image should already be aligned to the source frame because StableNew validates it but does not manually re-author the map.",
    "controlnet_model": "StableNew ControlNet model selector for conditioned workflows. Leave the default unless the conditioned workflow contract explicitly requires a different depth-capable model name.",
    "controlnet_weight": "Overall conditioning weight for the depth-guided ControlNet path. Higher values force the video to follow the depth structure more strongly, while lower values give the generative model more freedom.",
    "controlnet_guidance_start": "Fraction of the denoising schedule where ControlNet guidance begins. Use lower values for earlier and stronger structure influence, or delay it when early frames should stay looser.",
    "controlnet_guidance_end": "Fraction of the denoising schedule where ControlNet guidance ends. Keep it at 1.0 for full-run structure guidance, or lower it when later motion should break away from the conditioning map.",
    "prompt": "Positive text guidance for the workflow. Use it to reinforce subject, mood, or motion intent that the selected workflow should preserve across the sequence.",
    "negative": "Negative guidance for workflow outputs. Add repeated failure modes here when you want the sequence to avoid artifacts, flicker traits, or unwanted motion cues.",
}

MOVIE_CLIPS_SETTING_HELP = {
    "fps": "Frames per second for the assembled clip. Higher values make playback faster and smoother if enough frames exist, while lower values stretch the same frame set over more time.",
    "codec": "Container or encoding target for the rendered clip. Change it for compatibility or file-size reasons rather than to alter the visual content itself.",
    "quality": "Export quality preset for the clip package. Higher quality usually means larger files and longer export time; medium is a safer default when you are still iterating.",
    "mode": "Controls how the current image list is assembled into the output clip. Confirm it before building because it affects the final packaging behavior more than the source images themselves.",
}


__all__ = [
    "ADETAILER_STAGE_HELP",
    "BASE_GENERATION_SETTING_HELP",
    "IMG2IMG_SETTING_HELP",
    "MOVIE_CLIPS_SETTING_HELP",
    "SVD_SETTING_HELP",
    "TXT2IMG_SETTING_HELP",
    "UPSCALE_SETTING_HELP",
    "VIDEO_WORKFLOW_SETTING_HELP",
]