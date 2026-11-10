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

StableNew launches ComfyUI on demand through `ComfyProcessManager` when a queued video workflow needs it, using the
managed-Comfy configuration in StableNew's own machine-local `presets/settings.json`. That file's
`comfy_command` array is the supported way to configure the managed runtime: each executable and argument is
its own array element, so a path containing spaces is represented correctly.

**In the app (recommended):** open Engine Settings > Video runtime (ComfyUI) and click **Use managed install**.
StableNew reads `config/managed_comfy_runtime.json`, finds `<release>-py<minor>` under the install root, checks the
interpreter, source version, runtime folders and model path config (file checks only; it imports nothing and
starts nothing), and fills `comfy_command`, `comfy_workdir` and `comfy_base_url` with exactly the command the
verifier prints below, keeping the port of the configured URL. StableNew applies required flags automatically
when it launches ComfyUI. Save changes with **Save & Close**. Restart StableNew to replace an already registered launcher. If the
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
   in order.
3. Set `comfy_workdir` to the install's `source` folder.
4. Keep `comfy_base_url` and the command's `--port` aligned (same loopback port).

`STABLENEW_COMFY_COMMAND` is **not** the recommended path for the managed runtime. The launch resolver
(`src/video/comfy_process_manager.py`) will split it on whitespace, so it cannot hold the JSON
array above and cannot represent an executable or argument path containing spaces; do not paste the verifier's
output into it. If it is set in the environment it overrides the settings array when StableNew configures the launcher, so leave
it unset when using the settings configuration. When it is set and differs from the saved command, Engine
Settings and the Video Workflow runtime readiness strip say that the command comes from the environment and that
the saved one is not in force; StableNew never edits the variable, so remove or change it outside StableNew and
restart.

**When a video workflow is blocked on the launch command.** The Runtime readiness strip reports missing configuration,
unsupported switches, and whether a serving runtime can prove its launch flags. A successful offline CLI check
verifies the declared arguments only. If the configured launcher cannot be inspected, select a compatible direct
Python launch for ComfyUI's `main.py`. A running owned process with incompatible flags stays in place until its
existing lifecycle releases it. When an external ComfyUI occupies the endpoint, workflows that require verified flags
must wait for that runtime to finish and its operator to close it. **Fix ComfyUI Setup** opens Engine Settings when a
launch command is missing or an older direct ComfyUI launch rejects the saved `--disable-pinned-memory` switch.
For a workflow such as Wan2.2 TI2V-5B that has no required launch flags, choose **Remove unsupported flag** in
Engine Settings, save, then restart StableNew. The repair applies to the saved custom launch command. If an
environment override supplies the command, update that override before restarting. Workflows such as Wan-Animate-2
that require the switch still need a compatible installation. Use the Video Workflow readiness strip to check the
selected workflow's models. Debug Hub's Model Resources tab reports the global ControlNet and auxiliary inventory.

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
