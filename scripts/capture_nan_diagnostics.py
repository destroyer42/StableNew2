"""
Diagnostic script to track NaN errors and memory issues.

Run this after a NaN error occurs to capture diagnostic info.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


def capture_diagnostics():
    """Capture system state after NaN error."""
    
    diagnostics = {
        "timestamp": datetime.now().isoformat(),
        "memory": {},
        "processes": [],
        "webui_state": {},
    }
    
    # Memory info
    mem = psutil.virtual_memory()
    diagnostics["memory"] = {
        "total_gb": round(mem.total / (1024**3), 2),
        "used_gb": round(mem.used / (1024**3), 2),
        "available_gb": round(mem.available / (1024**3), 2),
        "percent": mem.percent,
    }
    
    # Python processes
    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'create_time', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower():
                diagnostics["processes"].append({
                    "pid": proc.info['pid'],
                    "ram_gb": round(proc.info['memory_info'].rss / (1024**3), 2),
                    "age_hours": round((datetime.now().timestamp() - proc.info['create_time']) / 3600, 1),
                    "cmdline": ' '.join(proc.info.get('cmdline', []))[:200],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # Try to query WebUI state
    try:
        import requests
        
        # Check if WebUI is responsive
        response = requests.get("http://127.0.0.1:7860/sdapi/v1/options", timeout=5)
        diagnostics["webui_state"]["responsive"] = response.status_code == 200
        
        if response.status_code == 200:
            options = response.json()
            diagnostics["webui_state"]["model"] = options.get("sd_model_checkpoint", "unknown")
            diagnostics["webui_state"]["vae"] = options.get("sd_vae", "unknown")
            diagnostics["webui_state"]["upcast_attention"] = options.get("upcast_attention_to_float32", "not_set")
        
        # Check progress
        progress_resp = requests.get("http://127.0.0.1:7860/sdapi/v1/progress", timeout=5)
        if progress_resp.status_code == 200:
            progress = progress_resp.json()
            diagnostics["webui_state"]["progress"] = progress.get("progress", 0)
            diagnostics["webui_state"]["eta"] = progress.get("eta_relative", 0)
            
    except Exception as exc:
        diagnostics["webui_state"]["error"] = str(exc)
    
    # Save to reports directory
    reports_dir = Path("reports/diagnostics")
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = reports_dir / f"nan_error_diagnostics_{timestamp_str}.json"
    
    with output_file.open("w") as f:
        json.dump(diagnostics, f, indent=2)
    
    print(f"\n{'='*60}")
    print("NaN ERROR DIAGNOSTICS")
    print(f"{'='*60}")
    print(f"\nMemory: {diagnostics['memory']['percent']}% used "
          f"({diagnostics['memory']['used_gb']}/{diagnostics['memory']['total_gb']} GB)")
    print(f"\nPython processes: {len(diagnostics['processes'])}")
    for proc in diagnostics["processes"]:
        print(f"  PID {proc['pid']}: {proc['ram_gb']}GB, age: {proc['age_hours']}h")
    
    print(f"\nWebUI responsive: {diagnostics['webui_state'].get('responsive', 'unknown')}")
    print(f"Model: {diagnostics['webui_state'].get('model', 'unknown')}")
    
    print(f"\n{'='*60}")
    print(f"Full diagnostics saved to: {output_file}")
    print(f"{'='*60}\n")
    
    return diagnostics


if __name__ == "__main__":
    try:
        capture_diagnostics()
    except Exception as exc:
        print(f"Error capturing diagnostics: {exc}", file=sys.stderr)
        sys.exit(1)
