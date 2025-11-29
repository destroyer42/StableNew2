# StableNew Snapshot & Diff Workflow (ChatGPT)

This document describes how to generate a clean snapshot of the StableNew repo
and an accompanying `git diff` file that can be uploaded to ChatGPT for
deep-dive debugging or design help.

## 1. Snapshot ZIP (tools/make_snapshot.ps1)

The PowerShell script `tools/make_snapshot.ps1` creates a pruned ZIP of the
repository:

- Excludes heavy / noisy folders:
  - `output/`, `archive/`, `models/`, `venv/`, `dist/`, `build/`
  - `__pycache__/`, `.pytest_cache/`, `.git/`, and `*.log` files
- Writes a version file at `.stableNew_version.txt` and bumps the patch number
  automatically on each run (e.g. `1.0.0` → `1.0.1`).
- Produces a ZIP on the Desktop by default with a name like:

  ```text
  StableNew_v1.0.1_20251115_214500.zip
  ```

### Running the script

1. Update the user configuration block at the top of the script if your repo or
   output locations differ from the defaults.
2. From PowerShell, run:

   ```powershell
   pwsh -File tools\make_snapshot.ps1
   ```

3. After the script completes, look for the generated ZIP in the configured
   output folder. The `.stableNew_version.txt` file in the repo root will track
   the next patch number for you.

## 2. Last change diff (tools/make_patch.cmd)

To provide reviewers with recent context, capture the diff of the latest commit
by running the Windows Command Prompt helper:

```cmd
tools\make_patch.cmd
```

The script writes `tools\last_change.diff`, which you can upload alongside the
snapshot ZIP. Regenerate the diff whenever you make new commits you want to
share.

## 3. Sharing with ChatGPT

- Upload the snapshot ZIP and the `last_change.diff` file together for the most
  useful analysis.
- Mention any specific files or areas you want reviewed so ChatGPT can focus on
  them.
- If the repo includes sensitive data, double-check that the excluded folders
  list in the snapshot script covers them before uploading.
