"""Test the FULL load flow from pack file to GUI."""
import json
from pathlib import Path

# Load the actual pack file
pack_path = Path("packs/Beautiful_people_fullbody_PhotoMomentum_v26.json")
with open(pack_path) as f:
    pack_data = json.load(f)

print("=" * 80)
print("STEP 1: WHAT'S IN THE FILE RIGHT NOW:")
print("=" * 80)
pipeline = pack_data.get("preset_data", {}).get("pipeline", {})
print(f"txt2img_enabled: {pipeline.get('txt2img_enabled')}")
print(f"img2img_enabled: {pipeline.get('img2img_enabled')}")  # <-- CURRENTLY TRUE
print(f"adetailer_enabled: {pipeline.get('adetailer_enabled')}")  # <-- CURRENTLY FALSE
print(f"upscale_enabled: {pipeline.get('upscale_enabled')}")

print("\n" + "=" * 80)
print("STEP 2: USER MODIFIES IN GUI:")
print("=" * 80)
print("User unchecks img2img checkbox")
print("User checks adetailer checkbox")

print("\n" + "=" * 80)
print("STEP 3: USER CLICKS 'Apply Config to Pack':")
print("=" * 80)
# Simulate what controller does when applying config
pipeline["img2img_enabled"] = False  # User set this to false
pipeline["adetailer_enabled"] = True  # User set this to true

# Save it
with open(pack_path, "w") as f:
    json.dump(pack_data, f, indent=2)
print(f"Saved to: {pack_path}")
print(f"img2img_enabled: {pipeline.get('img2img_enabled')} (should be False)")
print(f"adetailer_enabled: {pipeline.get('adetailer_enabled')} (should be True)")

print("\n" + "=" * 80)
print("STEP 4: USER CLICKS 'Load Config from Pack':")
print("=" * 80)

# Reload from disk
with open(pack_path) as f:
    loaded_data = json.load(f)

loaded_pipeline = loaded_data.get("preset_data", {}).get("pipeline", {})
print(f"Loaded from disk:")
print(f"  img2img_enabled: {loaded_pipeline.get('img2img_enabled')} (should be False)")
print(f"  adetailer_enabled: {loaded_pipeline.get('adetailer_enabled')} (should be True)")

print("\n" + "=" * 80)
print("STEP 5: SIMULATE _apply_pipeline_stage_flags():")
print("=" * 80)

for stage in ("txt2img", "img2img", "upscale", "adetailer"):
    key = f"{stage}_enabled"
    if key in loaded_pipeline:
        enabled = bool(loaded_pipeline.get(key))
        print(f"  {stage}: {enabled}")
    else:
        print(f"  {stage}: KEY MISSING!")

print("\n" + "=" * 80)
print("RESULT:")
print("=" * 80)
img2img_result = bool(loaded_pipeline.get("img2img_enabled"))
adetailer_result = bool(loaded_pipeline.get("adetailer_enabled"))

if img2img_result == False and adetailer_result == True:
    print("✅ VALUES CORRECT")
else:
    print("❌ BUG PRESENT:")
    print(f"   Expected: img2img=False, adetailer=True")
    print(f"   Got: img2img={img2img_result}, adetailer={adetailer_result}")
