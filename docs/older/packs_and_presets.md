# Packs, Configs, and Lists

StableNew stores per-pack configuration alongside presets and pack lists so you can quickly rehydrate a working setup. Use the UI actions in the action bar to manage each type.

## Loading a Pack Config

1. Select a pack from the Prompt Packs list.
2. Click **Load Pack Config**.
3. If a JSON file exists in `packs/<pack_name>.json`, the controls panel and pipeline settings are updated.  
   If there is no saved config, the app notifies you and keeps the current defaults.

Pack configs are plain JSON files; you can version-control them or copy between machines.

## Working with Lists

- Lists live under the `lists/` directory (one `<name>.json` file per list).
- Each file contains a simple object: `{"packs": ["PackA", "PackB"]}`.
- The **List** dropdown reflects everything returned by `lists/*.json`.
- Use **Load List** to select every pack stored in that file, or **Save Selection as List** to write the current selection.

Lists are ideal for curating themed pack groups or reproducing QA runs. Because the files are portable, you can share them with teammates.

## Deprecated Model Matrix / Hypernet Controls

SDXL workflows no longer rely on the old SD1.x “model matrix” and “hypernetwork” UI. Those controls have been removed from the Pipeline Controls panel to reduce clutter. Existing configs and presets still retain the underlying keys, so no data is lost, but the UI focuses on SDXL-relevant options moving forward.
