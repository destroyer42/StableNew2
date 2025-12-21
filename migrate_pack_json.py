"""Migrate existing prompt pack JSON files to unified format.

This script finds all .json files in packs/ folder and converts them
to the new unified format with pack_data and preset_data sections.
"""

import json
from pathlib import Path
import shutil

def migrate_pack_json(json_path: Path) -> bool:
    """Migrate a single pack JSON to unified format.
    
    Args:
        json_path: Path to the JSON file
        
    Returns:
        True if migrated, False if already unified or error
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        
        # Check if already unified
        if "pack_data" in data or "preset_data" in data:
            print(f"  ✓ {json_path.name} - Already unified format")
            return False
        
        # Backup original
        backup_path = json_path.with_suffix(".json.bak")
        shutil.copy2(json_path, backup_path)
        
        # Detect type: pack data (has slots/matrix) or preset data (has pipeline/txt2img)
        is_pack_data = "slots" in data or "matrix" in data
        is_preset_data = "pipeline" in data or "txt2img" in data or "img2img" in data
        
        if is_pack_data and not is_preset_data:
            # Pure pack data - wrap in pack_data section
            unified = {
                "pack_data": data,
                "preset_data": {}
            }
            print(f"  ✓ {json_path.name} - Migrated pack data")
            
        elif is_preset_data and not is_pack_data:
            # Pure preset data - wrap in preset_data section, create empty pack_data
            unified = {
                "pack_data": {
                    "name": json_path.stem,
                    "slots": [],
                    "matrix": {
                        "enabled": False,
                        "mode": "fanout",
                        "limit": 8,
                        "slots": []
                    }
                },
                "preset_data": data
            }
            print(f"  ✓ {json_path.name} - Migrated preset data")
            
        elif is_pack_data and is_preset_data:
            # Already has both (shouldn't happen, but handle it)
            # This is the old collision case - probably corrupted
            print(f"  ⚠ {json_path.name} - Has both pack and preset at root (corrupted?)")
            print(f"    Creating backup and attempting split...")
            
            # Try to salvage what we can
            pack_keys = {"name", "slots", "matrix"}
            preset_keys = {"pipeline", "txt2img", "img2img", "refiner", "hires", "upscale", "adetailer"}
            
            pack_data = {k: v for k, v in data.items() if k in pack_keys}
            preset_data = {k: v for k, v in data.items() if k in preset_keys}
            
            unified = {
                "pack_data": pack_data,
                "preset_data": preset_data
            }
            print(f"    Split into pack_data (keys={list(pack_data.keys())}) and preset_data (keys={list(preset_data.keys())})")
        
        else:
            # Unknown format
            print(f"  ✗ {json_path.name} - Unknown format, skipping")
            return False
        
        # Write unified format
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(unified, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"  ✗ {json_path.name} - Error: {e}")
        return False

def main():
    """Migrate all pack JSON files."""
    packs_dir = Path("packs")
    
    if not packs_dir.exists():
        print("No packs/ directory found")
        return
    
    json_files = list(packs_dir.glob("*.json"))
    
    if not json_files:
        print("No JSON files found in packs/")
        return
    
    print(f"Found {len(json_files)} JSON files in packs/")
    print("="*60)
    
    migrated = 0
    skipped = 0
    errors = 0
    
    for json_path in sorted(json_files):
        result = migrate_pack_json(json_path)
        if result is True:
            migrated += 1
        elif result is False and "Already unified" in str(result):
            skipped += 1
        else:
            skipped += 1
    
    print("="*60)
    print(f"Migration complete:")
    print(f"  - Migrated: {migrated}")
    print(f"  - Skipped: {skipped}")
    print(f"  - Total: {len(json_files)}")
    print()
    print("Backups saved as *.json.bak")
    print("="*60)

if __name__ == "__main__":
    main()
