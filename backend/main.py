import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

from backend.database import init_db, save_events, get_latest_events
from backend.bridge_manager import run_zk_command
from backend.mqtt_manager import mqtt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
app_state = {
    "zk_connected": False,
    "zk_ip": "",
    "zk_sn": "",
    "users_count": 0
}

def sync_job():
    """Periodic job pulling full state dump."""
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return
        
    res = run_zk_command(connstr, "state_dump")
    if res and res.get("success"):
        app_state["zk_connected"] = True
        hw = res.get("hardware", {})
        app_state["zk_ip"] = hw.get("ip", "")
        app_state["zk_sn"] = hw.get("serial_number", "")
        app_state["users_count"] = len(res.get("users", []))
        
        # Save payload
        from backend.database import save_users, save_hardware
        save_users(res.get("users", []))
        save_hardware(hw, res.get("doors", []))
        
        # Publish deep HA integration structure
        mqtt.publish_hardware_discovery(hw)
        
        events = res.get("events", [])
        if events:
            save_events(events)
            # Find the actual newest event locally after merge to accurately publish
            # Or just publish the last one from the fetched list
            latest = events[-1]
            mqtt.publish_event(
                latest["timestamp"],
                latest["door_id"],
                latest["card_id"],
                latest["event_type"]
            )
            
        mqtt.publish_status(True, app_state["zk_ip"])
    else:
        app_state["zk_connected"] = False
        mqtt.publish_status(False)

scheduler = BackgroundScheduler()

def handle_mqtt_command(topic: str, payload: str):
    logger.info(f"Received MQTT command via {topic}")
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return
        
    try:
        if topic.endswith("/reboot/set"):
            run_zk_command(connstr, "restart")
        elif topic.endswith("/sync_time/set"):
            run_zk_command(connstr, "sync_time")
        elif "/relay_" in topic and topic.endswith("/set"):
            relay_id = int(topic.split("/relay_")[1].split("/")[0])
            run_zk_command(connstr, "trigger_relay", relay_id=relay_id)
    except Exception as e:
        logger.error(f"Failed to handle incoming MQTT command: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting ZKAccess Gateway...")
    init_db()

    # Init MQTT
    broker = os.environ.get("MQTT_BROKER")
    if broker:
        port = int(os.environ.get("MQTT_PORT", 1883))
        user = os.environ.get("MQTT_USER")
        password = os.environ.get("MQTT_PASSWORD")
        mqtt.connect(broker, port, user, password, on_command_callback=handle_mqtt_command)

    # Start scheduler with an immediate first run
    from datetime import datetime
    sync_interval = int(os.environ.get("ZK_SYNC_INTERVAL", 30))
    scheduler.add_job(sync_job, 'interval', seconds=sync_interval, next_run_time=datetime.now())
    scheduler.start()
    
    yield
    # Shutdown
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# API routes
@app.get("/api/status")
def get_status():
    return {
        "connected": app_state["zk_connected"],
        "ip": app_state["zk_ip"],
        "serial_number": app_state["zk_sn"],
        "users_count": app_state["users_count"],
        "mqtt_connected": mqtt.connected
    }

@app.get("/api/events")
def get_events():
    return {"events": get_latest_events(50)}

@app.get("/api/users")
def get_users_api():
    from backend.database import get_users
    return {"users": get_users()}

@app.get("/api/hardware")
def get_hardware_api():
    from backend.database import get_hardware
    return get_hardware()

@app.get("/api/settings")
def get_all_settings():
    pw = os.environ.get("MQTT_PASSWORD", "")
    return {
        "zkt_connstr": os.environ.get("ZKT_CONNSTR", ""),
        "mqtt_broker": os.environ.get("MQTT_BROKER", ""),
        "mqtt_port": os.environ.get("MQTT_PORT", "1883"),
        "mqtt_user": os.environ.get("MQTT_USER", ""),
        "mqtt_password": "*" * len(pw) if pw else ""
    }

@app.post("/api/settings")
def update_settings(payload: dict = Body(...)):
    return {"success": False, "error": "Settings are now statically managed via environment variables (docker-compose.yml)"}

@app.post("/api/users")
def create_user(payload: dict = Body(...)):
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "create_user", 
                         pin=payload.get("pin", ""),
                         card=payload.get("card", ""),
                         group=payload.get("group", "1"),
                         admin=bool(payload.get("super_authorize", False)))
    
    if res and res.get("success"):
        # Kick off a fast background sync to immediately update local SQLite DB
        scheduler.add_job(sync_job)
        return {"success": True}
    return {"success": False, "detail": res.get("error", "Unknown error")}

@app.delete("/api/users/{pin}")
def delete_user(pin: str):
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "delete_user", pin=pin)
    if res and res.get("success"):
        scheduler.add_job(sync_job)
        return {"success": True}
    return {"success": False, "detail": res.get("error", "Unknown error")}

@app.post("/api/relays/{relay_id}/trigger")
def trigger_relay(relay_id: int):
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "trigger_relay", relay_id=relay_id)
    if res and res.get("success"):
        return {"success": True}
    return {"success": False, "detail": res.get("error", "Unknown error")}

@app.post("/api/device/sync-time")
def sync_device_time():
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "sync_time")
    if res and res.get("success"):
        return {"success": True}
    return {"success": False, "detail": res.get("error", "Unknown error")}

@app.post("/api/device/reboot")
def reboot_device():
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "restart")
    if res and res.get("success"):
        return {"success": True}
    return {"success": False, "detail": res.get("error", "Unknown error")}

@app.post("/api/test_connection")
def test_connection(payload: dict = Body(...)):
    connstr = payload.get("zkt_connstr")
    if not connstr:
        return {"success": False, "detail": "Missing connection string"}
        
    res = run_zk_command(connstr, "test")
    if res and res.get("success"):
        return {"success": True, "ip": res.get("ip")}
    return {"success": False, "detail": res.get("error", "Unknown error")}

# Serve frontend if exists
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    assets_dir = os.path.join(STATIC_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        path = os.path.join(STATIC_DIR, full_path)
        if os.path.exists(path) and os.path.isfile(path):
            return FileResponse(path)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
