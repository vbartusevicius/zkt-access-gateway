import subprocess
import json
import os
import threading

# A global hardware connection lock to prevent SDK Error -2 collisions
ZK_LOCK = threading.Lock()

WINE_CMD = ["wine", "python", "backend/wine_script/zk_client.py"]
DEBUG = os.environ.get("ZK_DEBUG", "").lower() in ("1", "true", "yes")

def run_zk_command(connstr: str, action: str, **kwargs) -> dict:
    if not connstr:
        return {"success": False, "error": "Connection string is empty"}
        
    cmd = WINE_CMD + ["--connstr", connstr, "--action", action]
    
    for key, value in kwargs.items():
        if isinstance(value, bool):
            if value:
                cmd.append(f"--{key}")
        else:
            cmd.extend([f"--{key}", str(value)])
    
    with ZK_LOCK:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("ZK_BRIDGE_TIMEOUT", 60))
            )
            
            if result.returncode != 0:
                print(f"[BRIDGE] Wine process exited with {result.returncode}. Stdout: {result.stdout.strip()} | Stderr: {result.stderr.strip()}", flush=True)
                try:
                    data = json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"success": False, "error": f"Wine process error: {result.stderr.strip()}"}
            else:
                try:
                    data = json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"success": False, "error": f"Invalid JSON returned: {result.stdout.strip()[:100]}"}

            if DEBUG:
                print(f"[BRIDGE] action={action} response={json.dumps(data, indent=2)}", flush=True)

            return data
                
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Connection to ZK device timed out"}
        except Exception as e:
            return {"success": False, "error": f"Subprocess execution failed: {str(e)}"}
