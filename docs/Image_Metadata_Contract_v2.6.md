# Image Metadata Contract v2.6

Status: Canonical Addendum
Updated: 2025-12-24

## Purpose

StableNew embeds a compact, deterministic metadata capsule inside output images (PNG preferred; JPG supported).
This metadata is portable for inspection and DebugHub bundling, but History remains authoritative.

## Required Keys

All keys are namespaced to avoid collisions.

- `stablenew:schema` = `stablenew.image-metadata.v2.6`
- `stablenew:job_id`
- `stablenew:run_id`
- `stablenew:stage`
- `stablenew:created_utc`
- `stablenew:payload_sha256`

## Payload Keys (Exactly One Required)

- `stablenew:payload` (UTF-8 JSON, uncompressed)
- `stablenew:payload_gz_b64` (gzip + base64)

If payload cannot be embedded due to size:

- `stablenew:payload_omitted` = `true`
- `stablenew:payload_reason` = `SIZE_LIMIT`

## Optional Keys

- `stablenew:njr_sha256`
- `stablenew:history_ref`
- `parameters` (if an existing A1111-style block is already present)

## Payload Content

The payload is a compact capsule derived from stage manifests (not full run metadata):

```json
{
  "job_id": "...",
  "run_id": "...",
  "stage": "...",
  "image": {
    "path": "relative/or/basename.png",
    "width": 768,
    "height": 1280,
    "format": "png"
  },
  "seeds": {
    "requested_seed": -1,
    "actual_seed": 1319559905,
    "actual_subseed": 1624510708
  },
  "njr": {
    "snapshot_version": "2.6",
    "sha256": "..."
  },
  "stage_manifest": {
    "name": "...",
    "timestamp": "...",
    "config_hash": "..."
  }
}
```

## Size Policy

- Soft cap: 32 KB (raw JSON)
- Hard cap: 256 KB (compressed)

Rules:

- If raw JSON > 32 KB, payload must be compressed (`payload_gz_b64`).
- If compressed > 256 KB, payload must be omitted and flagged with `payload_omitted`.

## Canonical Serialization and Hashing

Canonical JSON serialization:

- `sort_keys = True`
- `separators = (",", ":")`
- UTF-8 bytes

`payload_sha256 = sha256(canonical_payload_bytes)`

If `njr_sha256` is present, it is computed the same way from the NJR snapshot dict.

Compression:

- gzip (level 6 or default)
- base64 standard alphabet (no line breaks)

## History and DebugHub Rules

- History is authoritative. Image metadata is a cache/portable capsule only.
- DebugHub may extract metadata for read-only diagnostics bundles.
- Metadata should never mutate History or override NJR snapshots.

## Missing or Stripped Metadata

If metadata is missing or stripped:

1) Look for sidecars:
   - `image.json` (stage manifest)
   - `run_metadata.json` (run folder)
2) If not found, attempt best-effort History lookup.
3) If still not found, display "metadata unavailable (stripped)" without error.

## JPG Limitations

JPG metadata is best-effort (EXIF UserComment). If metadata cannot be written or read, behavior must remain non-fatal.
