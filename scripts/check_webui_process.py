"""
Check if WebUI process is alive and what state it's in.
"""
import subprocess
import time

def check_webui_process():
    """Find and check WebUI process."""
    # Find python.exe process running WebUI
    result = subprocess.run(
        ["powershell", "-Command", "Get-Process python | Where-Object {$_.CommandLine -like '*webui*'} | Select-Object Id,ProcessName,CPU,WorkingSet"],
        capture_output=True,
        text=True
    )
    print("WebUI Processes:")
    print(result.stdout)
    
    # Check if process is suspended/blocked
    result2 = subprocess.run(
        ["powershell", "-Command", "Get-Process python | Where-Object {$_.CommandLine -like '*webui*'} | Select-Object Id,Responding,Threads"],
        capture_output=True,
        text=True
    )
    print("\nProcess Status:")
    print(result2.stdout)

if __name__ == "__main__":
    while True:
        check_webui_process()
        time.sleep(5)
