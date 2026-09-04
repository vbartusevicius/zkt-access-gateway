import subprocess
import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# A global hardware connection lock to prevent SDK Error -2 collisions
ZK_LOCK = threading.Lock()

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wine_script", "zk_client.py")
WINE_CMD = ["wine", "python", SCRIPT_PATH]
DEBUG = os.environ.get("ZK_DEBUG", "").lower() in ("1", "true", "yes")

def run_zk_command(connstr: str, action: str, **kwargs) -> dict:
    from backend.wine_script.zk_commands import REGISTRY
    cmd_cls = REGISTRY.get(action)
    if not connstr and (cmd_cls is None or cmd_cls.needs_connection):
        return {"success": False, "error": "Connection string is empty"}

    cmd = WINE_CMD + ["--connstr", connstr, "--action", action]

    for key, value in kwargs.items():
        if isinstance(value, bool):
            if value:
                cmd.append(f"--{key}")
        elif isinstance(value, (dict, list)):
            cmd.extend([f"--{key}", json.dumps(value)])
        else:
            cmd.extend([f"--{key}", str(value)])

    queued_at = time.monotonic()
    logger.info("[BRIDGE] queued action=%s%s", action,
                " (waiting for hardware lock)" if ZK_LOCK.locked() else "")

    with ZK_LOCK:
        waited = time.monotonic() - queued_at
        started_at = time.monotonic()
        logger.info("[BRIDGE] start  action=%s (lock wait %.1fs)", action, waited)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("ZK_BRIDGE_TIMEOUT", 60))
            )
            logger.info("[BRIDGE] done   action=%s rc=%s in %.1fs (lock wait %.1fs)",
                        action, result.returncode, time.monotonic() - started_at, waited)

            if result.returncode != 0:
                logger.error(
                    "[BRIDGE] Wine process exited with %s. Stdout: %s | Stderr: %s",
                    result.returncode, result.stdout.strip(), result.stderr.strip()
                )
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
                logger.debug("[BRIDGE] action=%s response=%s", action, json.dumps(data, indent=2))

            return data

        except subprocess.TimeoutExpired:
            logger.error("[BRIDGE] timeout action=%s after %.1fs", action, time.monotonic() - started_at)
            return {"success": False, "error": "Connection to ZK device timed out"}
        except Exception as e:
            logger.error("[BRIDGE] failed action=%s: %s", action, e)
            return {"success": False, "error": f"Subprocess execution failed: {str(e)}"}
