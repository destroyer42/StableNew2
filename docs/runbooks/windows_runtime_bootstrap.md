# Windows native-SVD runtime bootstrap

This is the canonical setup procedure for a Windows StableNew environment
that will run the native Stable Video Diffusion (SVD) XT backend. It supports
official standard-GIL Python 3.14, an NVIDIA CUDA runtime, and FFmpeg/ffprobe.

## Prerequisites

Install an official 64-bit standard-GIL Python 3.14 (not the free-threaded
`3.14t` build; the experimental JIT stays off). A per-user, side-by-side
installation is enough: no PATH or file-association change is required. A Python
launcher that resolves `py -3.14` is preferred; an explicit executable can also be passed to the helper. The
machine must have a working NVIDIA driver and an NVIDIA GPU suitable for the
accepted SVD profile.

Install FFmpeg so both `ffmpeg.exe` and its sibling `ffprobe.exe` execute from
the same installation or are available on `PATH`. StableNew resolves these
through its existing production resolver; the repository does not bundle or
install FFmpeg.

## Launching StableNew

Day to day, use the canonical launcher from the repository (no venv activation, any working directory):

```powershell
.\scripts\launch_stablenew.bat        # or launch_stablenew.ps1; arguments are forwarded to src.main
```

It always runs `<repo>\.venv\Scripts\python.exe -m src.main` and returns the application's exit code.

- **No `.venv`:** it runs the bootstrap below once (`-SkipSvdReadiness`, see next section), then launches.
  System Python is used only there, as the source for creating the venv.
- **Healthy `.venv`:** one read-only check (interpreter policy and the exact pins from the constraints; no pip, no
  install), then launch.
- **Incomplete, unsupported or drifted `.venv`:** the launcher stops with guidance (exit 11) and changes
  nothing; it never falls back to another Python. Diagnose with
  `.\scripts\bootstrap_windows.ps1 -CheckOnly -SkipSvdReadiness`; recreate only deliberately with `-Recreate`.
- Bootstrap failure exits 10; a folder that is not a StableNew checkout exits 12.
- It starts, stops and selects no A1111, Forge, Comfy or SVD runtime; the application owns those.

`launch_stablenew_advanced.bat` only forwards to `launch_stablenew.bat`.

### Desktop shortcut and autostart at sign-in

`scripts\manage_stablenew_shortcuts.ps1` installs, reports and removes two per-user shortcuts to the checkout it
lives in. Run it from the checkout the app should start from (the live app uses the `StableNew-main` checkout):

```powershell
cd <StableNew-main checkout>
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1           # install both
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1 -Status   # report only
```

| Shortcut | File | Window |
| --- | --- | --- |
| Desktop | `<Desktop>\StableNew.lnk` | normal |
| Autostart | `shell:startup\StableNew.lnk` (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) | minimized |

Windows opens everything in the user's Startup folder at each sign-in, including the first sign-in after a
restart or a reboot. It does not start StableNew before someone signs in: a reboot that stops at the sign-in screen
leaves StableNew stopped until the owner (or Windows automatic sign-in, if the owner set that up separately) signs
in. Nothing machine-wide changes: no registry Run key, no Scheduled Task, no service, no admin rights. Task Manager >
Startup apps lists the entry and can disable it too.

- `-Desktop` or `-Autostart` limits the run to one shortcut; with neither, both are acted on.
- Install is idempotent: a second run prints `already installed` and rewrites nothing. A StableNew shortcut that points
  at another checkout's `launch_stablenew.bat` is retargeted to this one, and the old target is printed.
- A `StableNew.lnk` whose target is not a `launch_stablenew.bat` is never overwritten or removed; the script reports
  it and exits 2.
- StableNew's single-instance lock keeps an autostarted app and a later manual launch from both running.
- If the launch fails at sign-in, the minimized launcher window stays open with the reason (`launch_stablenew.bat`
  pauses on failure).

To undo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1 -Autostart -Remove   # stop starting at sign-in
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1 -Desktop -Remove     # remove the desktop shortcut
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage_stablenew_shortcuts.ps1 -Remove              # remove both
```

`scripts\create_desktop_shortcut.ps1` still works and forwards to `manage_stablenew_shortcuts.ps1 -Desktop`.

## Bootstrap

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
```

The default target is the repository `.venv`. To select a particular Python
or an isolated environment, use explicit paths:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 `
  -PythonPath "C:\Path\to\python.exe" `
  -VenvPath "$env:TEMP\StableNew-svd-verify"
```

An existing valid venv is reused. `-Recreate` is an explicit opt-in for a
dedicated venv path; do not use it against an environment containing unrelated
work. `-CheckOnly` validates an existing venv without installing or changing
packages:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 `
  -VenvPath .\.venv -CheckOnly
```

### Core application check vs native-SVD readiness

`-SkipSvdReadiness` (used by the launcher) runs the same interpreter validation, installs (when bootstrapping),
`pip check` and exact-pin verification, then stops before the native-SVD capability checks (CUDA device,
FFmpeg/ffprobe, cached SVD model). It installs exactly the same packages. An image-only operator can therefore launch
StableNew without those SVD prerequisites; the application's own readiness panel still reports them. Without the
switch the full native-SVD verification below is unchanged and remains the proof for SVD work.

## What the helper does

The supported runtime is reproducible from repository-owned authority:

- `requirements.txt` / `requirements-svd.txt` stay the human-readable direct
  dependencies of the **core** profile (StableNew and native SVD).
  `requirements-postprocess.txt` is the **optional** profile: local face
  restoration and upscaling (Spandrel model loading, plus the `codeformer`
  wheel that provides CodeFormer's face helper). Core SVD, including
  postprocess-disabled jobs, never requires it.
- `constraints/windows-py314-cu130.txt` is the single exact-version authority
  for the supported Windows / CPython 3.14 / CUDA 13.0 environment, including
  the resolver itself (`pip`). It has a core section and a
  `# profile: postprocess` section. Every install the helper performs is
  constrained by it, so a rebuild resolves the same packages instead of
  whatever is newest. It is Windows-specific; Linux/GitHub CI does not use it.
- Changing any pin is its own reviewed, qualified change. Do not regenerate the
  file with `pip freeze` from a developer environment.

The helper installs exactly the pinned pip (never `--upgrade`), installs
`torch` and `torchvision` (the latter backs transformers' default image
processor used by SVD conditioning) at their pinned `+cu130` builds from the
official PyTorch CUDA index (default `https://download.pytorch.org/whl/cu130`;
PyPI is an extra index only for their ordinary dependencies), and then installs
`requirements.txt` followed by `requirements-svd.txt`. Pass `-WithPostprocess`
to also install `requirements-postprocess.txt`. A CPU-only Torch cannot satisfy
or replace the pinned CUDA build. It then runs `pip check` and
`tools/runtime/verify_runtime_pins.py` (a stdlib comparison of installed
distributions against the constraints, which ignores unpinned extras) in both
bootstrap and `-CheckOnly` modes. The core profile is always required; the
optional profile is required only with `-WithPostprocess` (or when its
`spandrel` markers are installed), is reported as absent-by-design otherwise,
and any installed pinned package that has drifted fails either way. It also verifies
Python, CUDA-enabled Torch, the detected GPU, Diffusers and
`StableVideoDiffusionPipeline`, Transformers, Accelerate, imageio-ffmpeg,
and executable FFmpeg/ffprobe.

The helper never downloads a model. It checks the production default
per-user Hugging Face cache through StableNew's existing cache/model helpers.
If the accepted plain XT model is absent, it exits with an actionable model
acquisition message. Acquire the model deliberately through the approved
operator process, then rerun the helper; model acquisition is not an
import-time, bootstrap, or inference side effect.

Stable Diffusion WebUI/A1111 remains a separate externally managed runtime.
Its environment is not replaced by StableNew's `.venv`, and this helper does
not start, stop, adopt, or configure it.

## Migrating an existing environment to Python 3.14

An existing Python 3.12 `.venv` keeps working for the old interpreter but is no
longer the supported runtime. Migrate without losing the rollback:

1. Install the official standard (GIL) Python 3.14 per-user and side by side
   (no PATH or file-association change needed).
2. Keep the current environment as the rollback: rename `.venv` to
   `.venv-py312` (do not delete it).
3. Build the new environment from merged `main` with a short path if Windows
   long paths are not enabled, for example
   `.\scripts\bootstrap_windows.ps1 -PythonPath <Python314\python.exe>`
   (add `-WithPostprocess` if local face restoration/upscaling is wanted).
4. Verify with `.\scripts\bootstrap_windows.ps1 -CheckOnly` (pin verifier,
   `pip check`, CUDA, SVD pipeline, cached model, FFmpeg).
5. Only after the new environment passes, retire `.venv-py312`.

A1111, Forge and ComfyUI keep their own interpreters and are not touched.

## Common failures

- **Unsupported Python:** install official 3.14 (3.12, 3.13, 3.15+ and the
  free-threaded build are rejected), or pass `-PythonPath` to a standard
  3.14 executable.
- **Runtime drift reported:** a pinned package is missing or at a different
  version. Rebuild with the helper (`-Recreate` only on a dedicated venv path)
  rather than editing packages by hand.
- **Path too long during install:** Windows can fail while unpacking deeply
  nested package files (for example setuptools). Use a short `-VenvPath`
  (such as `C:\sn-venv`) unless Windows long paths are enabled.
- **CPU-only Torch or CUDA unavailable:** rerun with the official CUDA index
  using `-CudaIndexUrl` if the validated index has changed; do not accept a
  CPU-only environment for native SVD.
- **FFmpeg/ffprobe missing:** install both executables and place them on
  `PATH`, or configure the existing StableNew FFmpeg resolver authority.
- **Model acquisition required:** the production per-user Hugging Face cache
  does not contain a complete accepted plain XT snapshot. The helper does not
  download it.
- **Access denied:** use an elevated/local Windows shell for the target
  environment, or pass a disposable venv under `%TEMP%` for validation.

Successful bootstrap proves runtime prerequisites and local-only model/cache
readiness. It does not submit an NJR, load a model, run portrait inference,
or constitute the broader MVP-080 release proof.

## Update and restart (LAUNCH-UPDATE-1)

The header button **Update** opens a dialog for the checkout the app is running from. Design, threat model and the
owner decisions D1–D10: `docs/work_packages/LAUNCH-UPDATE_remote_restart.md`.

- **Check for update** fetches `origin` and reports whether `main` can be fast-forwarded, and by how many commits.
- **Update and restart** asks for confirmation, then:
  1. refuses (and changes nothing) unless the checkout is on `main` tracking `origin/main`, `origin` is the
     StableNew2 repository, no tracked file is modified or staged, `origin/main` is a descendant of `HEAD`, GitHub
     reports that commit as signed by it (`web-flow`, a pull request merged on GitHub; otherwise
     `not_github_signed`, or `github_unavailable` when GitHub cannot be asked), and the
     new commit's pinned constraints pass the launcher's read-only check against the current `.venv`. Nothing is ever
     installed: an update that needs packages is refused as `environment_drift`;
  2. holds the queue in memory (not the Pause button) and waits up to 60 minutes for the running job to finish. It
     never cancels it. If the job is still running then, the queue continues and the update is refused
     `busy_timeout`;
  3. starts `scripts\update_and_restart.ps1` and closes StableNew normally. The script waits for the app to exit (it
     never kills it), checks the checkout again, runs `git merge --ff-only`, and starts
     `scripts\launch_stablenew.ps1` minimized. Queued jobs resume as after any restart;
  4. if the new version does not start (the launcher exits, for example with 11 for a drifted `.venv`), moves local
     `main` back with `git reset --keep <old commit>` and starts the old version again. `origin` is never changed.
- The dialog shows the last result: old and new commit, or the reason it was refused or rolled back.
- **Allow remote update** (off by default) is the PC-side switch for phone requests (LAUNCH-UPDATE-2, below).
  Update and restart from the desktop works with the switch off.

### From the phone (LAUNCH-UPDATE-2)

One-time setup at the desk, after the gateway release with LAUNCH-UPDATE-2 is installed:

1. **Update** dialog: tick **Allow remote update**.
2. **Phone Review** dialog: **Pair for remote update**, confirm, and enter the code on the phone within five minutes.
   This replaces the phone's earlier pairing; revoke the old entry in the list.

Then, away from the desk, the phone's inbox shows **Update the PC…**. The screen shows the PC's commit, `origin/main`
(fetched by the PC at most every 15 minutes), how many commits that is, and the queue. **Update to `<sha>`** asks for
confirmation and sends exactly that commit. The PC refuses `target_moved` if `origin/main` has moved, then runs the
same preflight, wait, update, restart and rollback as the desktop button. The phone shows the result, including
"health unconfirmed" when StableNew was started but did not report in within 180 s. Untick **Allow remote update** or
revoke the phone to turn it off.

State lives in `%LOCALAPPDATA%\StableNew\live-update` (`intent.json`, `result.json`, `started.json`,
`last_result.json`, `settings.json`, and the copy of the updater that ran), outside the checkout. Output, logs, packs,
presets, `data\` and the `.venv` are not touched: a fast-forward changes only tracked files that differ between the
two commits. If something goes wrong away from the desk, the result file says which step stopped. A `rollback_failed`
result leaves the checkout at the new commit with StableNew stopped; at the desk, run
`git reset --keep <old_sha from result.json>` and start StableNew again.
