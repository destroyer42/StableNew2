PR-WIRE-00-V2.5-11-26-2025.md

Here’s a copy/paste-ready prompt to have Copilot create this doc in src/docs/ directly from repo_inventory.json (so it’s reproducible inside the repo):

You are acting as an implementation agent for the StableNew project.

## Context

Repository root: `StableNew-cleanHouse/`

StableNew is a Python 3.11+ Tk/Ttk GUI application for orchestrating Stable Diffusion pipelines. We have a repo inventory file:

- `repo_inventory.json`

This file has a top-level key `"files"` which is a list of objects with keys (at least):

- `path` (str, repo-relative, e.g. "src/gui/main_window_v2.py")
- `module` (str, python module path)
- `line_count` (int)
- `has_tk` (bool)
- `is_gui` (bool)
- `has_v1_marker` (bool)
- `imports` (list of module strings)
- `reachable_from_main` (bool)

We want a **human-facing wiring checklist** for all modules with `reachable_from_main == true`.

Your task is to implement **PR-WIRE-00-V2.5 – Wiring Checklist Doc**.

---

## Requirements

Create a new Markdown doc:

- Path: `src/docs/WIRING_V2_5_ReachableFromMain_2025-11-26.md`

Content requirements:

1. Header:

   - Title: `StableNew Wiring Checklist (V2.5)`
   - Note that it is auto-generated from `repo_inventory.json` with `reachable_from_main = true`.
   - Include the `generated_at` timestamp from `repo_inventory.json` somewhere near the top.

2. Status legend:

   Add a short legend explaining the `Status` field values we’ll fill in manually:

   - `wired` – actively used in current V2/V2.5 flow
   - `stub` – present but not yet functionally connected
   - `legacy_candidate` – likely V1/obsolete, under review
   - `future_feature` – reserved for planned capabilities (video, cluster, etc.)
   - `unknown` – needs review

3. Group **only** files where `reachable_from_main == true` by subsystem based on the first component after `src/`:

   Use these subsystem group names:

   - `Entry / Root` – for `src/main.py` and any top-level `src/*.py`.
   - `GUI` – paths starting with `src/gui/` or `src/gui_v2/`.
   - `Controller` – `src/controller/`.
   - `Pipeline` – `src/pipeline/`.
   - `API / WebUI` – `src/api/`.
   - `Learning` – `src/learning/`.
   - `AI / Smart Defaults` – `src/ai/`.
   - `Queue / Jobs` – `src/queue/`.
   - `Cluster / Distributed` – `src/cluster/`.
   - `Config / Settings` – `src/config/`.
   - `Services` – `src/services/`.
   - `Utils` – `src/utils/`.

   If any `reachable_from_main` file does not match these prefixes, you can either:
   - put it under `Entry / Root` (if directly under `src/`), or
   - create a small `Other (<prefix>)` section, but this should not be needed with the current inventory.

4. For each subsystem section:

   Add a Markdown heading:

   ```markdown
   ## <Subsystem Name>


Then a table with header:

| Path | V1 marker | GUI-related | Tk usage | Status | Notes |
| --- | --- | --- | --- | --- | --- |


And one row per reachable_from_main file in that subsystem:

Path: backticked repo-relative path from inventory (e.g. `src/gui/main_window_v2.py`).

V1 marker: "yes" if has_v1_marker == true, otherwise blank.

GUI-related: "yes" if is_gui == true, otherwise blank.

Tk usage: "yes" if has_tk == true, otherwise blank.

Status: leave empty ("") for now.

Notes: leave empty ("") for now.

The sections should be ordered in a reasonable subsystem order, for example:

Entry / Root

GUI

Controller

Pipeline

API / WebUI

Learning

AI / Smart Defaults

Queue / Jobs

Cluster / Distributed

Config / Settings

Services

Utils

Implementation guidance

Implement a small Python script or inline code in the existing tooling (if appropriate) to:

Load repo_inventory.json.

Filter files where reachable_from_main == true.

Group by subsystem based on path.

Write the Markdown file to src/docs/WIRING_V2_5_ReachableFromMain_2025-11-26.md.

You may either:

Add a small helper under tools/ (e.g. tools/generate_wiring_checklist_v2_5.py) and run it once, or

Directly write the Markdown content into the file in this PR.

The important thing is that the resulting document matches the structure above and reflects the current inventory accurately.

Do NOT:

Modify repo_inventory.json.

Modify non-doc code (except adding a tiny helper under tools/ if necessary).

Change any CI or workflows.

Acceptance criteria

A new file src/docs/WIRING_V2_5_ReachableFromMain_2025-11-26.md exists.

It contains:

A header with title and inventory timestamp.

The status legend.

One section per subsystem containing only reachable_from_main == true files.

A table in each section with the columns described above, with Status and Notes left empty.

Paths, flags (V1 marker, GUI-related, Tk usage), and grouping by subsystem match repo_inventory.json.

Final response format

When you are finished, reply with:

A short summary of what you did.

Confirmation of the path of the new doc.

The list of subsystems and counts of files per subsystem from the inventory.