# Managed Forge Neo runtime (Windows)

How to build, verify and launch the StableNew-**managed** Forge Neo runtime (runtime identity `forge_webui`).
It is independent of the StableNew application environment (standard-GIL CPython 3.14,
`constraints/windows-py314-cu130.txt`) and of the managed ComfyUI runtime: different interpreter, venv,
constraints and bootstrap. None is installed into, imported by, or derived from another.

It replaces the hand-qualified Forge environment used in PR-IMG-FORGE-100 with one that can be rebuilt from
nothing and proven identical. It is the **product default** for new still-image work (`PR-IMG-FORGE-120`): when `webui_runtime_identity` is unset
StableNew selects this runtime. `a1111_webui` remains a supported, explicit rollback (see Rollback).

An external Forge or A1111 install is **not** covered here and is never adopted, upgraded, modified or
stopped by this tooling. `WebUIProcessManager` remains the only lifecycle authority for both
`a1111_webui` and `forge_webui`; the bootstrap and verifier never start, stop, adopt or kill anything.

## What is pinned

| Authority | File |
|---|---|
| Installation identity (Forge and ADetailer-Neo revisions, Python minor, Torch build, launch policy, known conflict, detectors, model references) | `config/managed_forge_runtime.json` |
| Every installed package at an exact version (the complete 147-distribution accepted set, including `pip`, `setuptools`, `uv` and Torch `+cu130`) | `constraints/forge-windows-py313-cu130-neo-d70373eb.txt` |
| Build / verify | `scripts/bootstrap_managed_forge_windows.ps1`, `tools/runtime/verify_managed_forge.py` |

- Forge: `Haoming02/sd-webui-forge-classic` at commit `d70373ebcf1a96d210b78cd6f77196459e783e2a`. The branch
  name `neo` is provenance only; the commit is the identity and no mutable ref is ever followed.
- ADetailer-Neo: `Haoming02/ADetailer-Neo` at commit `af228eba7a3f3691a25bcd1fc94aa95e600dd3e6`.
- Official standard-GIL CPython 3.13.x (accepted 3.13.16), JIT off. Torch `2.13.0+cu130`, torchvision
  `0.28.0+cu130`, CUDA 13.0.
- Loopback only (`127.0.0.1`). Default port `7871`.

## Prerequisites

- An official 64-bit standard-GIL CPython 3.13.x (not `3.13t`; `PYTHON_JIT` unset). Pass it with `-PythonPath`.
- `git`, network access to GitHub, PyPI and `download.pytorch.org/whl/cu130`, and an NVIDIA GPU with a CUDA 13.0
  capable driver.
- An existing A1111 home whose `models` folder holds the accepted checkpoint
  (`cyberrealisticXL_v90-16fp.safetensors`), LoRA (`add-detail-xl.safetensors`) and upscaler
  (`4xUltrasharp_4xUltrasharpV10.pth`). It is **referenced** (`--forge-ref-a1111-home`), never copied,
  modified or downloaded into the managed runtime. Pass it with `-ModelReferenceHome`.
- A local directory that already holds the two accepted YOLO detectors, `face_yolov8n.pt` and
  `hand_yolov8n.pt`. Pass it with `-DetectorSourceDir`.
- Windows long paths are off by default and torch ships a 192-character-deep licenses tree, so the install
  root must be short. The default (`%LOCALAPPDATA%\StableNew\Forge`) fits with headroom; the bootstrap
  refuses a root that is too long *before* creating anything, and the verifier re-checks it.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_managed_forge_windows.ps1 `
  -PythonPath "C:\Path\to\Python313\python.exe" `
  -ModelReferenceHome "C:\Path\to\stable-diffusion-webui" `
  -DetectorSourceDir "C:\Path\to\directory\with\yolo\detectors"
```

The install is `%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb\{source,venv,data,runtime}`:

| Directory | Contents |
|---|---|
| `source` | the exact Forge commit (clean checkout) |
| `venv` | the isolated interpreter and the exact accepted package set |
| `data` | Forge's `--data-dir`: the declared `config.json`, `extensions/adetailer-neo` (exact commit) and `models/adetailer` (the two YOLO files) |
| `runtime` | StableNew-owned Hugging Face / Matplotlib / YOLO / uv state, isolated from every other runtime |

The helper:

1. validates the interpreter (standard-GIL 3.13, JIT off) and refuses anything else;
2. creates the install directory and writes the ownership marker **first** (see below);
3. fetches **only the exact Forge commit** and requires `git rev-parse HEAD` to equal the pinned SHA, then does the
   same for ADetailer-Neo. It never clones a branch, pulls or updates;
4. creates the venv and installs the **complete** accepted package set with `pip install --no-deps`: the
   accepted dependency graph is internally inconsistent (below), so it is reproduced, not re-resolved. The
   Torch family comes from the CUDA 13 index; nothing is resolved from PyPI at install time beyond the pinned
   exact versions;
5. writes the StableNew-owned `data/config.json` (BOM-less UTF-8, declaring only `VERSION_UID`,
   `disabled_extensions: []` and `ad_extra_models_dir: ""`). `VERSION_UID` (`PY313` for the pinned revision) is
   Forge's own compatibility marker: a `config.json` without it makes Forge print a "clean reinstall" alert and
   wait for Enter, which `WebUIProcessManager` cannot answer, so the unattended launch dies before it binds a
   port;
6. copies **only** `face_yolov8n.pt` and `hand_yolov8n.pt` from `-DetectorSourceDir`, after validating each
   SHA256. The source files are never modified or deleted. No detector or model is ever downloaded, and no
   MediaPipe model is installed;
7. runs the verifier and, only if it passes, marks the install `verified`.

It does **not** launch Forge, run the extension's own installer, download models, or touch A1111, an external
Forge, ComfyUI, the StableNew application environment or any process.

### Ownership

The moment the helper creates the install directory — before any fetch, venv or `pip` step — it writes
`.stablenew-managed-forge.json` (status `installing`, updated to `verified` only after the checks pass). A failed
or interrupted build therefore always leaves a marked directory that `-Recreate` can rebuild. A directory that
already exists **without** the marker is never modified, adopted, recreated or deleted, with or without
`-Recreate`; move it aside or choose another `-InstallRoot`. `-Recreate` rebuilds only a directory this tooling
created and marked. `-CheckOnly` is strictly read-only.

## Verify (drift detection)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_managed_forge_windows.ps1 `
  -CheckOnly -ModelReferenceHome "C:\Path\to\stable-diffusion-webui"
```

The verifier is read-only and runs on the managed venv's interpreter. It checks:

- the contract itself (shape, full 40-hex revisions, exactly one declared conflict, no mutable ref);
- Python is the supported standard-GIL minor with the JIT off;
- the Forge and ADetailer-Neo checkouts are at **exactly** the pinned `HEAD`, are clean (no modified or untracked
  files) and have the pinned `origin`;
- every package in the lock is installed at its exact version **and no package outside the lock is installed**;
- `pip check` reports the one declared conflict and nothing else;
- Torch/torchvision are the pinned `+cu130` builds, CUDA is 13.0 and available, and the qualified GPU is visible;
- `data/extensions` holds only `adetailer-neo`; `data/models/adetailer` holds exactly the two YOLO files with the
  accepted SHA256s (no MediaPipe, no extra detector);
- the StableNew-owned runtime/config directories exist, `config.json` declares the contract's settings, and the
  declared `VERSION_UID` is the one the pinned Forge source (`modules/launch_utils.py`) defines;
- the model references resolve to the accepted checkpoint, LoRA and upscaler with the accepted SHA256s;
- the launch profile carries the required flags and nothing tuned.

Exit 0 is clean; 1 is drift (each problem is listed and tagged `MANAGED_FORGE_DRIFT` where it is a lock/source
mismatch); 2 is an unreadable contract. `--skip-model-hashes` skips hashing the large external model files.

### The one known dependency conflict

`gradio 4.40.0` requires `pillow<11.0,>=8.0` while the accepted runtime runs `pillow 12.3.0`. The contract
declares this single conflict (`known_conflicts`, id `gradio-pillow`) and the verifier accepts **exactly that
`pip check` line and no other**. Do not downgrade Pillow, upgrade Gradio, patch package metadata or suppress
`pip check`. A second conflict, a missing requirement or a changed version is drift. If the declared conflict
ever *disappears* the verifier fails with a request to stop: the runtime's identity has changed and the
contract must be deliberately re-qualified, never silently redefined.

## Launch

Do not start it by hand for StableNew work. StableNew launches it through `WebUIProcessManager` with the
`forge_webui` identity. Print the exact profile (it starts nothing):

```powershell
& "$env:LOCALAPPDATA\StableNew\Forge\neo-d70373eb\venv\Scripts\python.exe" `
  .\tools\runtime\verify_managed_forge.py `
  --install-dir "$env:LOCALAPPDATA\StableNew\Forge\neo-d70373eb" `
  --model-reference-home "C:\Path\to\stable-diffusion-webui" `
  --port 7871 --print-profile
```

The profile is a JSON object with `command`, `working_dir`, `env_overrides`, `endpoint` and
`startup_timeout_seconds`, ready for `--runtime-profile` of `tools/acceptance/img_forge_100_acceptance.py`. The
command preserves the physically qualified semantics:

```
<venv>\Scripts\python.exe launch.py --uv --api --port <port> --data-dir <install>\data
  --forge-ref-a1111-home <A1111 home> --ad-no-huggingface --skip-install
```

Nothing is tuned: no SageAttention, FlashAttention, xformers, allocator, CUDA-stream or FP8 option, no `--listen`,
and `--nowebui` is not required (deferred to later work). The environment keeps Hugging Face, Matplotlib, YOLO
and uv state in the install's `runtime` folder and forces offline operation (`HF_HUB_OFFLINE`,
`YOLO_AUTOINSTALL=False`), so a missing model fails loudly instead of downloading.

If anything already answers on that endpoint, StableNew refuses to launch and reports it; it does not adopt,
stop or replace it. Choose another loopback port or stop the other service yourself. Run the profile from the
StableNew repository root; the evidence directory must not become the application's working directory.

### Known first-launch behavior

- A fresh install has no `sd_model_checkpoint`, so Forge selects the first checkpoint in the referenced A1111
  library at startup and StableNew's normal `/options` write switches to the frozen one on the first job (one
  model switch, a first-time hash, a cold first start of roughly half a minute). Output is unaffected; Forge then
  persists the selection in `data/config.json` and later launches start on it. Seeding the checkpoint in the
  contract is a candidate improvement that needs its own qualification (see PR-IMG-FORGE-100, section 23).
- Forge never prompts when its `config.json` carries the declared `VERSION_UID`; do not remove it by hand.
- Harmless startup noise: `GET /sdapi/v1/cmd-flags` answers 500 on this Forge (StableNew treats it as optional),
  ADetailer-Neo warns that it cannot read branch data from a detached HEAD, and gradio rewrites one `.pyi` stub
  in the venv. None changes the package set; the verifier stays green.

## Production default (PR-IMG-FORGE-120)

Forge is the default still-image backend. With no `webui_runtime_identity` in `presets/settings.json` (and no
`STABLENEW_WEBUI_RUNTIME_IDENTITY`), StableNew:

- stamps new image work `forge_webui`;
- uses the identity-aware default endpoint `http://127.0.0.1:7871` (the manifest's default port; the flat `7860` that
  older settings files persist is not treated as a Forge choice, while any other explicit loopback URL is honored);
- builds the launch profile itself from `config/managed_forge_runtime.json` and the canonical install
  `%LOCALAPPDATA%\StableNew\Forge\neo-d70373eb` through the same code the verifier uses (no profile file is needed),
  with the model-reference home taken from `webui_workdir` (your existing A1111 folder);
- starts and stops it only through `WebUIProcessManager`, and refuses to touch an external process on the endpoint.

**Setup prerequisite.** The managed install is not created automatically. If it is missing, incomplete, not marked
`verified` for the pinned revision, or the model-reference home has no `models` folder, StableNew reports exactly what is
missing and stops: it does not install Forge, download anything, or start A1111 instead. Run the bootstrap once (see
Build). An invalid or unreadable `settings.json` also stops startup with a message; nothing is guessed.

`forge_runtime_profile_path` (the output of `verify_managed_forge.py --print-profile`) remains an optional advanced
override of the launch profile; with it set, `webui_base_url` is either unset/default or must equal the profile's endpoint.

The runtime identity guard still rejects a job whose backend does not match the endpoint before any dispatch.

Known limitation (tracked separately, not a demonstrated Forge incompatibility): the Pair-D ADetailer -> upscale
chain was qualified after the progress-watchdog and module-state repairs (see PR-IMG-FORGE-100, sections 24-29).

### Forge limitations the application enforces

- **Hypernetworks** are removed in the pinned Forge Neo. A job that names one is refused before dispatch with guidance to use
  the A1111 rollback, and the Randomizer does not present the feature as usable under Forge.
- **ADetailer detectors:** the managed runtime ships exactly `face_yolov8n.pt` and `hand_yolov8n.pt` (no MediaPipe). When the
  endpoint's own detector list is unavailable, only those two are offered.

### Explicit A1111 rollback

**Engine Settings:** choose **A1111 Compatibility** under *WebUI -> Runtime* (the product default is **Default -
Managed Forge**) and save. The selection is persisted as `webui_runtime_identity` and takes effect only after StableNew
is restarted: the running runtime is never stopped, adopted or hot-switched, and until you restart, new image jobs are
refused before dispatch because the running runtime no longer matches the selection. The dialog shows the endpoint the
existing identity-aware resolver will use (Forge `127.0.0.1:7871`, A1111 `127.0.0.1:7860`) and never writes an
identity-default endpoint as an explicit URL, so switching back cannot inherit the other runtime's port.

The equivalent manual edit, in `presets/settings.json`:

```json
{
  "webui_runtime_identity": "a1111_webui",
  "webui_base_url": "http://127.0.0.1:7860"
}
```

(`webui_base_url` may instead be removed: an explicit A1111 with no URL uses `127.0.0.1:7860`. Do not leave a Forge URL
such as `:7871` in place.) The A1111 path reads no Forge profile, needs no managed install, and uses the existing
`webui_workdir`, launch-profile commands and cache; new work is stamped `a1111_webui`. Jobs created earlier with no backend
identity, or with an explicit `a1111_webui`, run only under this configuration: while Forge is configured they are
refused before dispatch with an `ACTION REQUIRED` message. There is no automatic fallback or retry in either direction.

## Rolling back the managed install itself

Builds are side by side (`neo-<revision8>`). The hand-qualified environment used by PR-IMG-FORGE-100 is not
modified by this tooling. To roll back, point the Forge runtime profile back at that environment; the managed
install can stay on disk or be removed by deleting its own directory (only a marked directory is ever removed
by the tooling).

## Changing a pin or the revision

An upgrade is its own reviewed, qualified change: update the contract, rebuild a clean disposable install,
verify, compare against the current runtime with the canonical Forge qualification, and regenerate the lock from
that clean build. Never "freeze" over `constraints/forge-windows-*.txt` from a developer environment, and never
merge it with the application or Comfy constraints.
