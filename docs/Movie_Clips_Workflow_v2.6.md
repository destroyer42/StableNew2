# Movie Clips Workflow v2.6

**Status**: Active  
**Phase**: Video MVP  
**Updated**: 2026-03-11

---

## 1. Purpose

This document describes the Movie Clips MVP feature: how users turn selected still images into short video artifacts directly inside StableNew, without leaving the application or manually invoking FFmpeg.

It defines:

- The supported user workflows (source modes)
- The architecture boundary between clip assembly and the canonical generation pipeline
- Output location semantics
- Settings and their meanings
- Future work boundaries relative to AnimateDiff

---

## 2. Architecture Boundary

Movie Clips is a **post-processing** feature. It is explicitly **not** a pipeline stage.

```
PromptPack → Builder Pipeline → NJR → Queue → Runner → History → Learning
                                                                       ↑
                                           Movie Clips sits here ──────┘
                                           (post-execution artifact assembly)
```

Movie Clips assembles already-generated images into a video artifact. It does **not**:

- Alter the PromptPack → NJR execution path
- Add a new stage type to `stage_models.py`
- Read from or write to the job queue via `src/queue/`
- Use AnimateDiff or any motion diffusion model

These boundaries are enforced by the PR scope for this series (PR-GUI-VIDEO-001 through PR-TEST-VIDEO-003).

---

## 3. User Workflow

### 3.1 Open the Movie Clips Tab

The **Movie Clips** tab appears as a top-level tab in the main window, alongside Pipeline, Learning, Review, and Photo Optimize.

### 3.2 Select Image Sources

Two source modes are supported:

| Mode | Description |
|------|-------------|
| **From Run Folder** | Browse to a run output directory; all images in that folder are loaded automatically |
| **Manual File List** | Add individual image files one by one |

After selecting a source, the **Selected Images** list shows the images in deterministic alphabetical order by filename.

### 3.3 Manage the Image List

- **Load Images**: (Folder mode) Scans the selected folder for image files and populates the list.
- **Add Images…**: (Manual mode) Open a file picker to add individual files.
- **Remove Selected**: Remove the highlighted entries from the list.
- **Clear All**: Clear the entire list.

Image ordering is always alphabetical by filename. This ensures reproducible clip output.

### 3.4 Configure Clip Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **FPS** | Frames per second for the output clip | 24 |
| **Codec** | Video codec (`libx264`, `libx265`, `vp9`) | `libx264` |
| **Quality** | FFmpeg speed/quality preset | `medium` |
| **Mode** | `sequence` (frame stream) or `slideshow` (each image held for a duration) | `sequence` |

### 3.5 Build the Clip

Click **Build Clip**. The status area below the button shows:

- `Building…` while the background worker is running
- `Done: <filename>` on success
- `Error: <reason>` on failure

Build errors do not crash the application. A clear reason is always surfaced.

### 3.6 Settings Restore

All clip settings and the last-used folder path are persisted via `UIStateStore` and restored automatically on the next application launch.

---

## 4. Output Location

Clips are written to:

```
output/movie_clips/<clip_name>.mp4
```

A manifest JSON is written alongside each successful clip:

```
output/movie_clips/<clip_name>_manifest.json
```

### 4.1 Manifest Schema v1.0

```json
{
  "schema_version": "1.0",
  "clip_name": "clip",
  "output_path": ".../output/movie_clips/clip.mp4",
  "source_images": ["/path/a.png", "/path/b.png"],
  "settings": {
    "fps": 24,
    "codec": "libx264",
    "quality": "medium",
    "mode": "sequence"
  },
  "frame_count": 12,
  "duration_seconds": 0.5,
  "created_at": "2026-03-11T12:00:00+00:00"
}
```

Manifests are deterministic: given the same inputs and settings, the manifest content is always identical (except `created_at`).

---

## 5. FFmpeg Requirement

Movie Clips requires **FFmpeg** to be available on the system PATH. The service validates availability before attempting any build and returns a clear error if FFmpeg is absent.

FFmpeg is not bundled with StableNew. Install it from https://ffmpeg.org or via your system package manager.

---

## 6. Code Architecture

| Layer | Location | Responsibility |
|-------|----------|----------------|
| View contract | `src/gui/view_contracts/movie_clips_contract.py` | UI formatting helpers, default values |
| Tab frame | `src/gui/views/movie_clips_tab_frame_v2.py` | UI shell, source selection, image list, settings |
| Data models | `src/video/movie_clip_models.py` | Typed request/result/manifest objects |
| Service | `src/video/movie_clip_service.py` | Validation, ordering, VideoCreator delegation, manifest write |
| Controller | `src/controller/app_controller.py` | `on_build_movie_clip`, `on_load_movie_clip_source` entrypoints |
| FFmpeg wrapper | `src/pipeline/video.py` | `VideoCreator` — low-level FFmpeg invocation |

The tab frame delegates all assembly work to the controller. The controller runs assembly on a background thread and calls back on the GUI thread via `_run_in_gui_thread`.

---

## 7. Testing Coverage

| Scope | File |
|-------|------|
| Contract helpers | `tests/gui_v2/test_movie_clips_tab_v2.py` |
| Tab GUI regression | `tests/gui_v2/test_movie_clips_tab_v2.py` |
| Service unit tests | `tests/video/test_movie_clip_service.py` |
| Journey smoke | `tests/journeys/test_movie_clips_mvp.py` |

All tests are deterministic, headless-safe, and require no real FFmpeg or network calls.

---

## 8. Future Work Boundary

The following enhancements are out of scope for the MVP and must be planned separately:

| Feature | Future PR |
|---------|-----------|
| Queue-backed clip jobs | Post-MVP |
| AnimateDiff / motion diffusion | Separate AnimateDiff series |
| Stage-chain integration | Not planned (clips are post-processing) |
| History/Preview deep integration | Post-MVP |
| Clip playback inside the app | Post-MVP |

**AnimateDiff** involves motion generation via a diffusion model as a pipeline stage. It is a distinct feature from clip assembly and must not be conflated with the Movie Clips MVP.

---

## 9. References

- `docs/D-VIDEO-002-Movie-Clips-Tab-MVP-Discovery.md`
- `docs/PR_MAR26/PR-GUI-VIDEO-001-Movie-Clips-Tab-Spine-and-Selection.md`
- `docs/PR_MAR26/PR-CORE-VIDEO-002-Clip-Build-Service-and-Controller.md`
- `docs/PR_MAR26/PR-TEST-VIDEO-003-Movie-Clips-Journeys-and-Documentation.md`
- `docs/ARCHITECTURE_v2.6.md`
