import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler

from backend.database import init_db, get_setting, set_setting, save_events, get_latest_events
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
    """Periodic job pulling events and status."""
    connstr = get_setting("zkt_connstr") or os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return
        
    # Poll status
    status_res = run_zk_command(connstr, "status")
    if status_res and status_res.get("success"):
        app_state["zk_connected"] = True
        app_state["zk_ip"] = status_res.get("ip", "")
        app_state["zk_sn"] = status_res.get("serial_number", "")
        app_state["users_count"] = status_res.get("users_count", 0)
        mqtt.publish_status(True, app_state["zk_ip"])
    else:
        app_state["zk_connected"] = False
        mqtt.publish_status(False)
        return

    # Poll events
    events_res = run_zk_command(connstr, "events")
    if events_res and events_res.get("success"):
        events = events_res.get("events", [])
        if events:
            # Check newly arrived events (assuming db deduplicates them)
            save_events(events)
            # Publish newest event to HA
            latest = events[-1]
            mqtt.publish_event(
                latest["timestamp"],
                latest["door_id"],
                latest["card_id"],
                latest["event_type"]
            )

scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting ZKAccess Gateway...")
    init_db()

    # Init MQTT
    broker = get_setting("mqtt_broker") or os.environ.get("MQTT_BROKER")
    if broker:
        port = int(get_setting("mqtt_port") or os.environ.get("MQTT_PORT", 1883))
        user = get_setting("mqtt_user") or os.environ.get("MQTT_USER")
        password = get_setting("mqtt_password") or os.environ.get("MQTT_PASSWORD")
        mqtt.connect(broker, port, user, password)

    # Start scheduler with an immediate first run
    from datetime import datetime
    scheduler.add_job(sync_job, 'interval', seconds=15, next_run_time=datetime.now())
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

@app.get("/api/settings")
def get_all_settings():
    return {
        "zkt_connstr": get_setting("zkt_connstr") or os.environ.get("ZKT_CONNSTR", ""),
        "mqtt_broker": get_setting("mqtt_broker") or os.environ.get("MQTT_BROKER", ""),
        "mqtt_port": get_setting("mqtt_port") or os.environ.get("MQTT_PORT", "1883"),
        "mqtt_user": get_setting("mqtt_user") or os.environ.get("MQTT_USER", ""),
        "mqtt_password": get_setting("mqtt_password") or os.environ.get("MQTT_PASSWORD", "")
    }

@app.post("/api/settings")
def update_settings(payload: dict = Body(...)):
    for key, value in payload.items():
        set_setting(key, value)
        
    # Reinit MQTT if changed
    if "mqtt_broker" in payload:
        mqtt.connect(
            payload.get("mqtt_broker"),
            int(payload.get("mqtt_port", 1883)),
            payload.get("mqtt_user"),
            payload.get("mqtt_password")
        )
    return {"success": True}

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
