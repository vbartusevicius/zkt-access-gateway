import subprocess
import json
import os

WINE_CMD = ["wine", "python", "backend/wine_script/zk_client.py"]

def run_zk_command(connstr: str, action: str) -> dict:
    if not connstr:
        return {"success": False, "error": "Connection string is empty"}
        
    cmd = WINE_CMD + ["--connstr", connstr, "--action", action]
    
    try:
        # We run the command inside the Wine environment.
        # Ensure we capture stdout correctly.
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15 # Safety timeout
        )
        
        if result.returncode != 0:
            # Check if there is valid JSON in stdout despite error
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"success": False, "error": f"Wine process error: {result.stderr.strip()}"}
                
        # Parse the JSON response
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"success": False, "error": f"Invalid JSON returned: {result.stdout.strip()[:100]}"}
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Connection to ZK device timed out"}
    except Exception as e:
        return {"success": False, "error": f"Subprocess execution failed: {str(e)}"}
