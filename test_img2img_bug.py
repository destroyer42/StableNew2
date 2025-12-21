"""Test to reproduce img2img_enabled defaulting bug."""
import json
from pathlib import Path

# Load the actual pack file
pack_path = Path("packs/Beautiful_people_fullbody_PhotoMomentum_v26.json")
with open(pack_path) as f:
    pack_data = json.load(f)

print("=" * 80)
print("CURRENT STATE IN PACK FILE:")
print("=" * 80)
pipeline = pack_data.get("preset_data", {}).get("pipeline", {})
print(f"txt2img_enabled: {pipeline.get('txt2img_enabled')}")
print(f"img2img_enabled: {pipeline.get('img2img_enabled')}")
print(f"adetailer_enabled: {pipeline.get('adetailer_enabled')}")
print(f"upscale_enabled: {pipeline.get('upscale_enabled')}")

print("\n" + "=" * 80)
print("USER WANTS TO SET:")
print("=" * 80)
print("txt2img_enabled: True")
print("img2img_enabled: False")
print("adetailer_enabled: True")
print("upscale_enabled: False")

print("\n" + "=" * 80)
print("SIMULATING SAVE:")
print("=" * 80)
# Modify the config
pipeline["txt2img_enabled"] = True
pipeline["img2img_enabled"] = False
pipeline["adetailer_enabled"] = True
pipeline["upscale_enabled"] = False

print(f"txt2img_enabled: {pipeline.get('txt2img_enabled')}")
print(f"img2img_enabled: {pipeline.get('img2img_enabled')}")
print(f"adetailer_enabled: {pipeline.get('adetailer_enabled')}")
print(f"upscale_enabled: {pipeline.get('upscale_enabled')}")

# Save it
test_pack_path = Path("test_pack_modified.json")
with open(test_pack_path, "w") as f:
    json.dump(pack_data, f, indent=2)

print(f"\nSaved modified config to: {test_pack_path}")

print("\n" + "=" * 80)
print("SIMULATING LOAD (reading file back):")
print("=" * 80)

# Load it back
with open(test_pack_path) as f:
    loaded_data = json.load(f)

loaded_pipeline = loaded_data.get("preset_data", {}).get("pipeline", {})
print(f"txt2img_enabled: {loaded_pipeline.get('txt2img_enabled')}")
print(f"img2img_enabled: {loaded_pipeline.get('img2img_enabled')}")
print(f"adetailer_enabled: {loaded_pipeline.get('adetailer_enabled')}")
print(f"upscale_enabled: {loaded_pipeline.get('upscale_enabled')}")

print("\n" + "=" * 80)
print("NOW SIMULATING app_controller._apply_executor_config_to_gui():")
print("=" * 80)

# This is what the code does
executor_config = loaded_data.get("preset_data", {})
pipeline_section = executor_config.get("pipeline") or {}

# Get stage flags directly from config without defaults - if missing, will be None
txt2img_val = pipeline_section.get("txt2img_enabled")
img2img_val = pipeline_section.get("img2img_enabled") 
adetailer_val = pipeline_section.get("adetailer_enabled")
upscale_val = pipeline_section.get("upscale_enabled")

stage_defaults = {
    "txt2img": bool(txt2img_val) if txt2img_val is not None else True,
    "img2img": bool(img2img_val) if img2img_val is not None else False,
    "adetailer": bool(adetailer_val) if adetailer_val is not None else False,
    "upscale": bool(upscale_val) if upscale_val is not None else False,
}

print(f"txt2img: {stage_defaults['txt2img']}")
print(f"img2img: {stage_defaults['img2img']}")
print(f"adetailer: {stage_defaults['adetailer']}")
print(f"upscale: {stage_defaults['upscale']}")

print("\n" + "=" * 80)
print("RESULT:")
print("=" * 80)
if stage_defaults["img2img"] == False and stage_defaults["adetailer"] == True:
    print("✅ BUG FIXED - Values are correct!")
else:
    print("❌ BUG STILL PRESENT")
    print(f"   Expected: img2img=False, adetailer=True")
    print(f"   Got: img2img={stage_defaults['img2img']}, adetailer={stage_defaults['adetailer']}")

# Cleanup
test_pack_path.unlink()
print(f"\nCleaned up test file: {test_pack_path}")
