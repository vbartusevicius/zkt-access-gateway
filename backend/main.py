import os
import re
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from apscheduler.schedulers.background import BackgroundScheduler

from backend.database import init_db, save_events, save_users, save_hardware, save_user_name, \
    get_events_filtered, get_latest_event_timestamp, get_latest_event_per_door, \
    get_users, get_hardware
from backend.bridge_manager import run_zk_command
from backend.mqtt_manager import mqtt, EVENT_TYPE_MAP
from backend.wine_script.zk_commands import REGISTRY
from backend.wine_script.zk_commands.spec import TABLE_SCHEMAS, DOOR_PARAM_SPECS, DEVICE_PARAM_SPECS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
app_state = {
    "zk_connected": False,
    "zk_ip": "",
    "zk_sn": "",
    "users_count": 0,
}

def _ingest_events(events):
    """Save events from pyzkaccess into the local database (single source of truth)."""
    if not events:
        return
    save_events(events)

def _publish_door_states():
    """Read the latest event per door from the database and publish to MQTT.
    Called every poll cycle so HA never falls into 'Unknown' state."""
    for event in get_latest_event_per_door():
        if not event["door_id"]:
            continue  # skip device-level events (no door context for HA)
        mqtt.publish_event(
            event["timestamp"],
            event["door_id"],
            event["card_id"],
            event["event_type"],
            user_name=event.get("user_name") or ""
        )

def poll_job():
    """Event job — pulls new events via the SDK RTLog (fast snapshot; full
    history is backfilled by full_sync_job from the Transaction table, so
    events survive gateway downtimes). Set ZK_EVENT_SOURCE=table to poll the
    Transaction table directly instead."""
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return

    if os.environ.get("ZK_EVENT_SOURCE", "rt") == "table":
        res = run_zk_command(connstr, "poll_events", since=get_latest_event_timestamp())
        if res and res.get("events_error"):
            logger.warning(f"Device poll reported a transactions read error: {res['events_error']}")
    else:
        rt_timeout = int(os.environ.get("ZK_RT_POLL_TIMEOUT", 3))
        res = run_zk_command(connstr, "rt_events", timeout=rt_timeout)
    if res and res.get("success"):
        app_state["zk_connected"] = True
        _ingest_events(res.get("events", []))
        _publish_door_states()
        mqtt.publish_status(True, app_state["zk_ip"], app_state["zk_sn"])
    else:
        app_state["zk_connected"] = False
        mqtt.publish_status(False)

def _ensure_mqtt(serial=""):
    """Connect MQTT once after device info is known."""
    if mqtt.connected:
        return
    broker = os.environ.get("MQTT_BROKER")
    if not broker:
        return
    port = int(os.environ.get("MQTT_PORT", 1883))
    user = os.environ.get("MQTT_USER")
    password = os.environ.get("MQTT_PASSWORD")
    mqtt.connect(broker, port, user, password, serial=serial, on_command_callback=handle_mqtt_command)
    for _ in range(50):
        if mqtt.connected:
            break
        time.sleep(0.1)

def full_sync_job():
    """Heavy job — pulls hardware, users, doors, and events."""
    connstr = os.environ.get("ZKT_CONNSTR")
    if not connstr:
        return

    since = get_latest_event_timestamp()
    res = run_zk_command(connstr, "state_dump", since=since)
    if res and res.get("success"):
        app_state["zk_connected"] = True
        hw = res.get("hardware", {})
        app_state["zk_ip"] = hw.get("ip", "")
        app_state["zk_sn"] = hw.get("serial_number", "")
        app_state["users_count"] = len(res.get("users", []))

        save_users(res.get("users", []))
        save_hardware(hw, res.get("doors", []))

        _ensure_mqtt(serial=app_state["zk_sn"])
        mqtt.publish_hardware_discovery(hw, res.get("doors", []))
        _ingest_events(res.get("events", []))
        _publish_door_states()
        mqtt.publish_status(True, app_state["zk_ip"], app_state["zk_sn"])
    else:
        app_state["zk_connected"] = False
        mqtt.publish_status(False)

scheduler = BackgroundScheduler()

def _execute_command(cmd_cls, kwargs):
    """Uniform command executor for both HTTP routes and MQTT commands."""
    connstr = os.environ.get("ZKT_CONNSTR", "")
    if cmd_cls.needs_connection and not connstr:
        return {"success": False, "detail": "Missing connection string"}

    res = run_zk_command(connstr, cmd_cls.name, **cmd_cls.validate(kwargs))
    if res and res.get("success"):
        if cmd_cls.refresh_after:
            scheduler.add_job(full_sync_job)
        return res
    return {"success": False, "detail": (res or {}).get("error", "Unknown error")}

# Compile MQTT command topics declared by WriteCommands into matchers:
# pattern like "relay_{relay_id}" matches the middle of zkt/<device>/<pattern>/set
MQTT_COMMANDS = [
    (
        re.compile(re.sub(r"\{(\w+)\}", lambda m: f"(?P<{m.group(1)}>[^/]+)", cmd_cls.mqtt_topic)),
        cmd_cls
    )
    for cmd_cls in REGISTRY.values()
    if cmd_cls.mqtt_topic
]

def handle_mqtt_command(topic: str, payload: str):
    logger.info(f"Received MQTT command via {topic}")
    prefix = f"zkt/{mqtt.device_id}/"
    if not topic.startswith(prefix) or not topic.endswith("/set"):
        return
    middle = topic[len(prefix):-len("/set")]

    for matcher, cmd_cls in MQTT_COMMANDS:
        match = matcher.fullmatch(middle)
        if match:
            result = _execute_command(cmd_cls, match.groupdict())
            if not result.get("success"):
                logger.error(f"MQTT command {cmd_cls.name} failed: {result.get('detail')}")
            return

    logger.warning(f"Unhandled MQTT command topic: {topic}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting ZKAccess Gateway...")
    init_db()

    from datetime import datetime
    poll_interval = int(os.environ.get("ZK_SYNC_INTERVAL", 60))
    full_sync_interval = int(os.environ.get("ZK_FULL_SYNC_INTERVAL", 600))
    scheduler.add_job(full_sync_job, 'interval', seconds=full_sync_interval, next_run_time=datetime.now(),
                       id='full_sync', coalesce=True, misfire_grace_time=full_sync_interval)
    scheduler.add_job(poll_job, 'interval', seconds=poll_interval,
                       id='poll', coalesce=True, misfire_grace_time=poll_interval)
    scheduler.start()

    yield
    # Shutdown
    scheduler.shutdown()
    if mqtt.client:
        mqtt.client.disconnect()
        mqtt.client.loop_stop()

app = FastAPI(lifespan=lifespan)

# --- Generated command routes declared by WriteCommands in zk_commands ---
def _make_command_handler(cmd_cls):
    async def handler(request: Request):
        payload = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    payload = body
            except Exception:
                payload = {}
        kwargs = {**request.path_params, **payload}
        return await run_in_threadpool(_execute_command, cmd_cls, kwargs)
    handler.__name__ = f"cmd_{cmd_cls.name}"
    return handler

for _cmd_cls in REGISTRY.values():
    if _cmd_cls.http_path:
        app.add_api_route(
            f"/api/{_cmd_cls.http_path}",
            _make_command_handler(_cmd_cls),
            methods=[_cmd_cls.http_method.upper()]
        )

# --- Queries served from the local cache/database ---
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
def get_events(limit: int = 100, door_id: int = None, event_type: int = None,
               q: str = None, dt_from: str = None, dt_to: str = None):
    events = get_events_filtered({
        "limit": limit, "door_id": door_id, "event_type": event_type,
        "q": q, "dt_from": dt_from, "dt_to": dt_to,
    })
    for ev in events:
        ev["description"] = EVENT_TYPE_MAP.get(ev.get("event_type"), f"Unknown ({ev.get('event_type')})")
    return {"events": events}

@app.get("/api/schemas")
def get_schemas():
    """Pure-data specs that drive form generation in the UI (and the REST of the app)."""
    return {
        "tables": TABLE_SCHEMAS,
        "door_params": DOOR_PARAM_SPECS,
        "device_params": DEVICE_PARAM_SPECS,
        "event_types": EVENT_TYPE_MAP,
    }

@app.get("/api/users")
def get_users_api():
    return {"users": get_users()}

@app.post("/api/users")
def create_or_update_user(payload: dict = Body(...)):
    """Explicit route (supersedes registry generation for create_user) so the
    gateway-local cardholder name is persisted alongside the device write."""
    result = _execute_command(REGISTRY["create_user"], payload)
    if result.get("success") and "name" in payload:
        save_user_name(payload.get("pin", ""), payload.get("name") or "")
    return result

@app.get("/api/hardware")
def get_hardware_api():
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
