# Managed ComfyUI runtime (Windows)

How to build, verify and run the StableNew-**managed** ComfyUI runtime. It is independent of the
StableNew application environment (standard-GIL CPython 3.14, `constraints/windows-py314-cu130.txt`):
different interpreter, different venv, different constraints, different bootstrap. Neither is installed
into, imported by, or derived from the other.

An external Comfy (for example the desktop app's) is **not** covered here and is never adopted,
upgraded or stopped by StableNew. `ComfyProcessManager` remains the only lifecycle authority: it
launches only an unoccupied endpoint and terminates only a process it started.

## What is pinned

| Authority | File |
|---|---|
| Installation identity (release, revision, Python minor, Torch build, launch policy, custom-node policy) | `config/managed_comfy_runtime.json` |
| Every installed package at an exact version (the complete set, including `pip` and Torch `+cu130`) | `constraints/comfy-windows-py313-cu130-v0.38.0.txt` |
| Build / verify | `scripts/bootstrap_managed_comfy_windows.ps1`, `tools/runtime/verify_managed_comfy.py` |
| Workflow graphs, model hashes, controls, readiness floors | the workflow catalog (`src/video/workflow_catalog*.py`), not the runtime contract |

The runtime is ComfyUI `v0.38.0` (commit `6b747c0428c343e1417219641db93a4fb7cb69ae`) on an official
standard-GIL CPython 3.13.x, with Torch `2.14.0+cu130` and CUDA 13.0, and **no custom nodes**. Model
files are referenced through `extra_model_paths.yaml`, never copied or downloaded by the bootstrap.

## Prerequisites

- An official 64-bit standard-GIL CPython 3.13.x (not `3.13t`; the experimental JIT stays off). A per-user,
  side-by-side install is enough; no PATH or file-association change is required. Pass it with
  `-PythonPath`.
- `git`, and an NVIDIA driver with a CUDA 13.0 capable GPU.
- A StableNew-owned runtime folder (default `%LOCALAPPDATA%\StableNew\ComfyRuntime`) containing
  `input`, `output`, `temp`, `user` and an `extra_model_paths.yaml` that points at your existing model
  library (diffusion models, text encoders, VAE, CLIP vision). The runtime folders are StableNew's, not the
  external Comfy's.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_managed_comfy_windows.ps1 `
  -PythonPath "C:\Path\to\Python313\python.exe"
```

The default install is `%LOCALAPPDATA%\StableNew\ManagedComfy\v0.38.0-py313\{source,venv}`. Keep the
install root short on Windows (long paths break deep packages). The helper:

1. validates the interpreter (standard-GIL 3.13, JIT off) and refuses anything else, including a reused venv
   created by another interpreter;
2. clones **only the exact tag** `v0.38.0` and requires `HEAD` to equal the pinned commit before installing
   anything (it never tracks a branch or pulls);
3. creates the venv, installs exactly the pinned `pip`, then the CUDA Torch family from the PyTorch cu130
   index, then ComfyUI's own `requirements.txt` — every install under `-c` the constraints file;
4. runs `pip check` and `verify_managed_comfy.py`.

Ownership is claimed first: the moment the helper creates the install directory — before any clone, venv or
`pip` step — it writes the `.stablenew-managed-comfy.json` marker (status `installing`, updated to `verified`
only after the checks pass). A failed or interrupted build therefore always leaves a marked directory that
`-Recreate` can rebuild. A directory that already exists **without** the marker is never modified, adopted or
deleted, with or without `-Recreate`; move it aside or pick another `-InstallRoot`.

It downloads no model, installs no custom node, and touches no A1111/Forge, no external Comfy, no
StableNew application venv and no process. `-Recreate` rebuilds an install the tooling created;
`-CheckOnly` is read-only.

## Verify (drift detection)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_managed_comfy_windows.ps1 -CheckOnly
```

The verifier checks, read-only: Python is the supported standard-GIL minor; the source `HEAD` is the pinned
revision, the checkout is clean and reports `0.38.0`; every pinned package is installed at its pin **and no
package outside the pins is installed** (this runtime carries exactly its constraints, so a stray
`pip install` or a custom node's dependency is drift); `custom_nodes` holds only Comfy's own entries; Torch
reports `2.14.0+cu130` with CUDA 13.0 available; and the StableNew-owned runtime folders and model path
config exist. Exit 0 is clean; 1 is drift (each problem listed); 2 is an unreadable contract.

## Launch

Do not start it by hand for StableNew work. StableNew launches it through `ComfyProcessManager`, from the
managed-Comfy configuration in StableNew's own machine-local `presets/settings.json`. That file's
`comfy_command` array is the supported way to configure the managed runtime: each executable and argument is
its own array element, so a path containing spaces is represented correctly.

**In the app (recommended):** open Engine Settings > Video runtime (ComfyUI) and click **Use managed install**.
StableNew reads `config/managed_comfy_runtime.json`, finds `<release>-py<minor>` under the install root, checks the
interpreter, source version, runtime folders and model path config (file checks only; it imports nothing and
starts nothing), and fills `comfy_command`, `comfy_workdir` and `comfy_base_url` with exactly the command the
verifier prints below, keeping the port of the configured URL. **Add required flags** appends only the missing
contract flags to a custom command. Nothing is written until **Save & Close**, and a restart applies it. If the
installation is not found, the dialog lists what is missing and changes nothing.

**By hand (equivalent):**

1. Print the command for your install. Use the port from your `comfy_base_url`:

   ```powershell
   & "$env:LOCALAPPDATA\StableNew\ManagedComfy\v0.38.0-py313\venv\Scripts\python.exe" `
     .\tools\runtime\verify_managed_comfy.py --install-dir "$env:LOCALAPPDATA\StableNew\ManagedComfy\v0.38.0-py313" `
     --port 8000 --print-command
   ```

   The output is a JSON array of strings: the managed interpreter and `main.py`, the loopback listen address,
   the port, the StableNew-owned input/output/temp/user folders, the model path config, and the required flags
   `--disable-pinned-memory` and `--disable-auto-launch`.
2. In `presets/settings.json`, set `comfy_command` to those array elements, one element per string, unchanged and
   in order. Do not drop `--disable-pinned-memory` (the Wan-Animate-2 workflows refuse to run on a runtime that
   cannot prove it) or `--disable-auto-launch`.
3. Set `comfy_workdir` to the install's `source` folder.
4. Keep `comfy_base_url` and the command's `--port` aligned (same loopback port).

`STABLENEW_COMFY_COMMAND` is **not** the recommended path for the managed runtime. Both startup readers
(`src/main.py` and `src/video/comfy_process_manager.py`) split it on whitespace, so it cannot hold the JSON
array above and cannot represent an executable or argument path containing spaces; do not paste the verifier's
output into it. If it is set in the environment it overrides the settings array at app startup, so leave
it unset when using the settings configuration. When it is set and differs from the saved command, Engine
Settings and the Video Workflow runtime readiness strip say that the command comes from the environment and that
the saved one is not in force; StableNew never edits the variable, so remove or change it outside StableNew and
restart.

**When a video workflow is blocked on the launch command.** The Video Workflow tab's runtime readiness strip names
the reason (no command, a missing required flag, or a launcher that has not applied a saved change). For a
problem Engine Settings can fix it shows **Fix ComfyUI Setup**, which only opens Engine Settings > Video runtime
(ComfyUI) with the reason at the top; the repair is still your click on **Use managed install** or **Add required
flags** and **Save & Close**. It is never shown for RAM, GPU memory, node or model-file blockers. A saved change is
**not** active until StableNew restarts: the strip keeps blocking on the launcher this session started and says so,
and Refresh cannot apply it. A ComfyUI that StableNew did not launch cannot have its flags verified, so a workflow
that requires them stays blocked while it is serving; stop it yourself and let StableNew start its own. If
**Save & Close** cannot write the settings, the dialog stays open and says so instead of closing.

Do **not** commit the result: the paths are machine-specific and the repository default `presets/settings.json`
is unchanged.

If anything already answers on that endpoint, StableNew refuses to launch and reports it; it does not adopt,
stop or replace it. Choose another loopback port or stop the other service yourself.

## Rollback

Builds are side by side (`<release>-py<minor>`). The previous qualification runtime is not modified by this
tooling. To roll back, point the managed-Comfy command back at the previous install (or the previous
external Comfy) and restart through StableNew; the new install can stay on disk or be removed by deleting its
own directory.

## Changing a pin or the release

An upgrade is its own reviewed, qualified change: update the contract, rebuild a clean disposable install,
verify, compare against the current runtime, and regenerate the constraints from that clean build. Never
"freeze" over `constraints/comfy-windows-*.txt` from a developer environment, and never merge it with the
application constraints.
