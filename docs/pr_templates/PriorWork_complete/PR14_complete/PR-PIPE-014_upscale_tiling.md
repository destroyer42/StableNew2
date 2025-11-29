# PR-PIPE-014: Resilient Upscale Tiling (Auto + Profiles + Fail-safe)

## How to use this document

**For Rob**

- Save this file into the repo, e.g.:
  - `docs/codex/prs/PR-PIPE-014_upscale_tiling.md`
- In Codex (cloud or VS Code), tell it explicitly:
  - “Open `docs/codex/prs/PR-PIPE-014_upscale_tiling.md` and implement everything in this file. Do not change anything outside the described scope.”

**For Codex**

- This document is a **source of truth** for this PR.
- Follow the **scope and constraints** exactly.
- Prefer **small, focused commits** and keep changes limited to the files and areas called out below.
- After code changes, you **must**:
  - Run the tests mentioned in the **Test Plan**.
  - Fix any style/CI issues (ruff/black/mypy/etc.) that arise from this work.

---

## 1. Background

Recent runs show that:

- WebUI upscale calls can still crash or 500, especially when tile sizes are too large for VRAM.
- The logs show large defaults being applied, e.g.:

  > `Applied WebUI upscale defaults: img_max_size_mp=16, ESRGAN_tile=1920, DAT_tile=1920`

- Rob wants:
  - Safe, automatic behavior that “just works” most of the time.
  - A way to explicitly choose tile behavior (conservative/balanced/aggressive/custom).
  - A fail-safe retry when upscale fails, instead of hard-crashing the pipeline.

We already log when defaults are applied, and the pipeline is otherwise working well. This PR focuses **only** on improving upscale robustness and control.

---

## 2. Objectives

Implement a **three-part** behavior:

1. **Option C – Auto tiling (default)**  
   - Compute reasonable tile settings from:
     - Input width/height  
     - Scale factor  
     - Upscale config
   - Avoid huge tiles that trigger 500s / VRAM issues.

2. **Option A – Manual tile profile override (UI dropdown)**  
   - Add a **“Tile profile”** dropdown in the Upscale tab:
     - `auto` (recommended default)
     - `conservative`
     - `balanced`
     - `aggressive`
     - `custom`
   - If user selects anything other than `auto`, that profile **overrides** the auto logic.

3. **Option D – Fail-safe retry (always on)**  
   - For every upscale call:
     - First attempt uses the chosen tiles (auto or profile/custom).
     - On error, automatically shrink tiles and retry once.
     - On second failure, log clearly and skip upscale gracefully — **do not crash the pipeline**.

---

## 3. Scope

### In scope

- **Config schema** for upscale tiling preferences.
- **Upscale tab UI** in the config panel:
  - Tile profile dropdown.
  - Optional custom fields (only visible when profile = `custom`).
- **API client upscale logic**:
  - Auto computation of tiles.
  - Profile overrides.
  - Fail-safe retry with smaller tiles.
- **Executor** wiring:
  - Pass relevant upscale config and dimensions into the client call.
- Logging that makes tile decisions and retries visible in the log output.

### Out of scope

- Changing the actual upscaler models, ADetailer logic, or NSFW prevention.
- Changing unrelated config sections or GUI layout outside the Upscale tab.
- Adding new prompt packs or presets (this PR is about robustness, not creative content).

---

## 4. Design Overview

### 4.1 Config keys (shared schema)

Extend the `upscale` config section (default + presets) with:

```jsonc
"upscale": {
  // …existing keys…

  // Option A + C
  "tile_profile": "auto",           // "auto" | "conservative" | "balanced" | "aggressive" | "custom"
  "tile_img_max_size_mp": 16.0,     // used for "custom" and as default baseline
  "tile_esrgan": 0,                 // 0 means "let WebUI decide"
  "tile_dat": 0,                    // 0 means "let WebUI decide"

  // Option D
  "tile_retry_enabled": true        // always true by default
}
Existing configs must continue to load. Missing keys should be filled with the defaults above.

Presets can override tile_profile and the numbers if desired.

4.2 UI: Upscale tab
In the Upscale tab (in config_panel.py or equivalent), add:

Tile profile dropdown:

Backed by a StringVar (or equivalent) holding the raw value:

"auto", "conservative", "balanced", "aggressive", "custom".

When profile = "custom":

Show three numeric inputs:

tile_img_max_size_mp (float; e.g. range 4–64)

tile_esrgan (int; e.g. 0 or 256–2048)

tile_dat (int; e.g. 0 or 256–2048)

When profile != "custom", those fields should be hidden or disabled.

load_from_config / save_to_config (or equivalent methods) must:

Read and write these keys under the "upscale" config section.

Default to tile_profile="auto" if missing.

4.3 Client auto-tiling and profiles
In src/api/client.py:

Add a helper, e.g. a method on the client:

python
Copy code
def _compute_upscale_tiles(
    self,
    width: int,
    height: int,
    scale: float,
    upscale_cfg: dict | None,
) -> dict:
    """
    Decide img_max_size_mp, ESRGAN_tile, DAT_tile based on:
    - upscale_cfg["tile_profile"] ("auto", "conservative", "balanced", "aggressive", "custom")
    - upscale_cfg custom numbers (for "custom")
    - image size and scale (for "auto")
    Returns dict with keys: img_max_size_mp, esrgan_tile, dat_tile
    """
Behavior:

Read from upscale_cfg (may be None, so handle robustly).

Implement profiles:

python
Copy code
if profile == "conservative":
    img_max_size_mp = 8.0
    esrgan_tile = 512
    dat_tile = 384

elif profile == "balanced":
    img_max_size_mp = 12.0
    esrgan_tile = 768
    dat_tile = 512

elif profile == "aggressive":
    img_max_size_mp = 20.0
    esrgan_tile = 1024
    dat_tile = 768

elif profile == "custom":
    # use user values, clamped:
    img_max_size_mp = clamp(cfg["tile_img_max_size_mp"], 4.0, 64.0)
    esrgan_tile = clamp_or_zero(cfg["tile_esrgan"], 256, 2048)
    dat_tile = clamp_or_zero(cfg["tile_dat"], 256, 2048)
For profile == "auto" (or unknown):

Estimate target MP:

python
Copy code
target_w = max(1, int(width * scale))
target_h = max(1, int(height * scale))
mp = (target_w * target_h) / (1024 * 1024)
Rough policy (tweakable but start here):

python
Copy code
if mp <= 6.0:
    img_max_size_mp = max(mp + 2.0, 8.0)
    esrgan_tile = 0
    dat_tile = 0
elif mp <= 16.0:
    img_max_size_mp = 16.0
    esrgan_tile = 768
    dat_tile = 512
else:
    img_max_size_mp = min(mp + 4.0, 24.0)
    esrgan_tile = 640
    dat_tile = 448
Log once at debug/info level when tiles are computed, e.g.:

python
Copy code
self._logger.info(
    "Upscale tiles: profile=%s mp=%.2f max_mp=%.1f esrgan_tile=%d dat_tile=%d",
    profile,
    mp,
    img_max_size_mp,
    esrgan_tile,
    dat_tile,
)
4.4 Client fail-safe retry
Still in src/api/client.py, update upscale_image (or the method that calls /sdapi/v1/extra-single-image) to:

Accept an optional upscale_cfg argument:

python
Copy code
def upscale_image(
    self,
    image_b64: str,
    upscaler_1: str,
    scale: float,
    gfpgan_visibility: float = 0.0,
    codeformer_visibility: float = 0.0,
    codeformer_weight: float = 0.0,
    upscale_cfg: dict | None = None,
) -> dict:
Before constructing the payload:

Determine width/height:

Prefer actual image dimensions if already available in upscale_cfg (e.g. input_width, input_height).

Otherwise fall back to 1024×1024 as a reasonable default.

Call _compute_upscale_tiles.

Build the payload including these tile settings, reusing the same field names the client already uses today to talk to WebUI.
Examples (adjust to match existing code):

python
Copy code
payload = {
    "image": image_b64,
    "upscaler_1": upscaler_1,
    "upscaling_resize": float(scale),
    "gfpgan_visibility": gfpgan_visibility,
    "codeformer_visibility": codeformer_visibility,
    "codeformer_weight": codeformer_weight,

    # New / adjusted:
    "image_max_size": img_max_size_mp,
    "esrgan_tile": esrgan_tile,
    "dat_tile": dat_tile,
}
Important: Do not rename or remove existing options that WebUI depends on. Only add/override the tile-related keys.

Implement fail-safe retry:

Read tile_retry_enabled = bool(upscale_cfg.get("tile_retry_enabled", True)).

Attempt 1:

Call the existing request path:

python
Copy code
resp = self._request("POST", url, json=payload, timeout=self.timeout)
return resp.json()
except block:

Log a warning that includes the tiles and the exception.

If tile_retry_enabled is False, re-raise immediately.

If retry is enabled:

Construct safer tiles:

python
Copy code
# Example heuristic
img_max_size_mp = min(img_max_size_mp, 12.0)
esrgan_tile = max(256, esrgan_tile // 2) if esrgan_tile else esrgan_tile
dat_tile = max(256, dat_tile // 2) if dat_tile else dat_tile
Log an info line:

“Retrying upscale with safer tiles: …”

Build a second payload with the shrunken values.

Call _request again; if this second attempt fails, let the exception propagate to the executor, which already logs “Upscale request failed or returned no image”.

5. Executor wiring
In src/pipeline/executor.py (or the module that orchestrates txt2img → ADetailer → upscale):

Wherever upscale_image is called, pass the upscale config:

python
Copy code
upscale_cfg = pack_config.get("upscale", {})  # or equivalent
# Optionally annotate with known dimensions if you have them
if img is not None and "input_width" not in upscale_cfg:
    upscale_cfg = dict(upscale_cfg)  # shallow copy
    upscale_cfg["input_width"], upscale_cfg["input_height"] = img.size

resp = self.client.upscale_image(
    image_b64,
    upscaler_name,
    scale=upscale_cfg.get("upscaling_resize", 2.0),
    gfpgan_visibility=upscale_cfg.get("gfpgan_visibility", 0.0),
    codeformer_visibility=upscale_cfg.get("codeformer_visibility", 0.0),
    codeformer_weight=upscale_cfg.get("codeformer_weight", 0.0),
    upscale_cfg=upscale_cfg,  # NEW
)
Do not change the surrounding success/failure handling logic (it already logs and moves on). The new behavior should just make failures rarer and more graceful.

6. Logging & Diagnostics
Add or retain logs so Rob can see:

Which profile was used and which tiles were chosen.

When the fail-safe retry fires and what values it retries with.

When upscale ultimately fails even after retry.

Examples:

python
Copy code
self._logger.info(
    "Upscale tiles: profile=%s img_max_size_mp=%.1f esrgan_tile=%d dat_tile=%d",
    profile,
    img_max_size_mp,
    esrgan_tile,
    dat_tile,
)

self._logger.warning(
    "Upscale request failed on first attempt (tiles=%s): %s",
    tiles1,
    exc,
)

self._logger.info(
    "Retrying upscale with safer tiles: %s",
    tiles2,
)
7. Test Plan
Codex must run these tests and confirm behavior manually where appropriate.

7.1 Automated tests
If relevant tests already exist, extend them; otherwise add new ones:

Unit tests for _compute_upscale_tiles:

Profiles:

auto

conservative

balanced

aggressive

custom (with edge values).

Different (width, height, scale) combos (small, medium, large).

Assert clamping and zero-handling behave as intended.

Client tests for fail-safe (can use mocking):

Mock _request to:

Raise on first call, succeed on second, assert that tile values shrink.

Raise on both calls, assert that the second exception propagates.

Run:

bash
Copy code
pytest tests/api -k "upscale or tiles"
pytest tests/pipeline -k "upscale"
(Adjust selectors if your test layout differs.)

7.2 Manual tests
On Rob’s machine:

Baseline auto:

Set tile profile to auto, upscale mode = single, scale = 2.0, 1024×1024 txt2img.

Confirm:

No crashes.

Log lines show reasonable tiles.

No “Upscale request failed…” errors.

Profile overrides:

Try conservative, balanced, aggressive in the UI.

For each, trigger an upscale and confirm:

Logs show the correct profile and tile values.

No pipeline crash.

Custom:

Switch to custom and set explicit values (e.g., img_max_size_mp=10, tile_esrgan=512, tile_dat=384).

Confirm these values are used.

Fail-safe:

Temporarily simulate a failure (e.g., by mocking or temporarily forcing an exception in the client).

Observe:

First attempt logs a warning.

Second attempt logs a retry with smaller tiles.

If second attempt is forced to succeed, upscale completes.

If second attempt is forced to fail, pipeline logs “Upscale request failed or returned no image” but doesn’t crash the GUI.

8. Completion Checklist
Codex should verify all of the following before considering this PR “done”:

 Config schema extended with tile_profile, tile_img_max_size_mp, tile_esrgan, tile_dat, tile_retry_enabled (with defaults).

 Upscale tab UI exposes tile profile dropdown and custom fields.

 load_from_config / save_to_config correctly persist these settings.

 Client has _compute_upscale_tiles with profiles and auto logic implemented.

 Client upscale_image:

 Accepts upscale_cfg.

 Applies tiles to payload using existing WebUI field names.

 Implements fail-safe retry that shrinks tiles.

 Executor passes the upscale config (and width/height if available) into upscale_image.

 Logging clearly shows profile choice, tiles, and any retries.

 All relevant tests pass (pytest), and no style/lint regressions.

 Manual runs on Rob’s machine confirm:

 No more crashes due to tile size.

 Profiles behave as expected.

 Fail-safe retry works.