"""
Test script to confirm WebUI returns HTTP 500 during model loading.
"""
import time
import requests
import json

BASE_URL = "http://127.0.0.1:7860"

def test_endpoint(endpoint, method="GET", json_data=None):
    """Test an endpoint and return status code."""
    try:
        if method == "GET":
            resp = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
        else:
            resp = requests.post(f"{BASE_URL}{endpoint}", json=json_data, timeout=5)
        return resp.status_code, resp.text[:200] if resp.text else ""
    except Exception as e:
        return None, str(e)

def main():
    print("Testing WebUI endpoint responses during model loading...")
    print("=" * 80)
    
    # Minimal txt2img payload
    payload = {
        "prompt": "test",
        "steps": 1,
        "width": 512,
        "height": 512,
    }
    
    for i in range(60):  # Test for 60 seconds
        models_status, models_resp = test_endpoint("/sdapi/v1/sd-models")
        options_status, options_resp = test_endpoint("/sdapi/v1/options")
        progress_status, progress_resp = test_endpoint("/sdapi/v1/progress")
        txt2img_status, txt2img_resp = test_endpoint("/sdapi/v1/txt2img", "POST", payload)
        
        print(f"\n[{i:02d}s] Endpoint Status:")
        print(f"  /sd-models:  {models_status}")
        print(f"  /options:    {options_status}")
        print(f"  /progress:   {progress_status} -> {progress_resp[:100]}")
        print(f"  /txt2img:    {txt2img_status} -> {txt2img_resp[:100]}")
        
        if txt2img_status == 200:
            print("\n✅ txt2img returned 200 OK - WebUI is ready for generation!")
            break
        elif txt2img_status == 500:
            print("\n❌ txt2img returned 500 - Model still loading!")
        
        time.sleep(2)

if __name__ == "__main__":
    main()
