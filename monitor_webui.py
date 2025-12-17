"""
Monitor WebUI process to see if it's hung or just not outputting.
Run this WHILE StableNew is running and WebUI is "stuck".
"""
import subprocess
import time

def check_process():
    # Check if python.exe running webui is alive and consuming CPU
    result = subprocess.run(
        [
            "powershell",
            "-Command",
            "Get-Process python | Where-Object {$_.Path -like '*stable-diffusion-webui*'} | Select-Object Id,CPU,WorkingSet,Threads,Responding | Format-List"
        ],
        capture_output=True,
        text=True
    )
    print("=" * 80)
    print(f"Timestamp: {time.strftime('%H:%M:%S')}")
    print(result.stdout)
    
    # Check thread count
    result2 = subprocess.run(
        [
            "powershell",
            "-Command",
            "(Get-Process python | Where-Object {$_.Path -like '*stable-diffusion-webui*'}).Threads.Count"
        ],
        capture_output=True,
        text=True
    )
    print(f"Thread count: {result2.stdout.strip()}")

if __name__ == "__main__":
    print("Monitoring WebUI process. Press Ctrl+C to stop.")
    print("Start StableNew and wait for it to 'hang' after 'Creating model from config'")
    input("Press Enter when WebUI is 'stuck'...")
    
    for i in range(10):
        check_process()
        time.sleep(2)
