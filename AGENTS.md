# zkt-access-gateway — project notes

Dockerized gateway bridging ZKTeco C3/C4 controllers (Windows PULL SDK via Wine) to
MQTT/Home Assistant and a web UI. Full ZKAccess 3.5 desktop-software replacement.

## Commands

- Install deps: `uv sync` (dev group includes pytest/httpx/pyzkaccess for tests)
- Tests: `uv run pytest` (native, no Wine needed — SDK calls are stubbed; real
  pyzkaccess models/enums validate data shapes), or replicated inside the
  production image: `docker build --target test -t zkt-access-gateway:test . &&
  docker run --rm zkt-access-gateway:test` (CI/publish workflows use this form)
- Compile check: `uv run python -m compileall -q backend tests`
- Frontend build: `cd frontend && npm install && npm run build`
- Docker build/publish: `.github/workflows/docker.yml` (GHCR, linux/amd64 only;
  ARM hosts run it through QEMU — compose pins `platform: linux/amd64`)
- Run locally (needs a device and Wine): only inside the Docker image —
  `docker compose up --build -d`

## Architecture rules (keep when extending)

1. **One command registry.** All device operations are `ReadCommand`/`WriteCommand`
   subclasses in `backend/wine_script/zk_commands/` (`read.py`, `write.py`). The
   class metadata (`name`, `args`, `http_path`, `http_method`, `mqtt_topic`,
   `refresh_after`) auto-generates: CLI `argparse` choices, REST routes
   (`backend/main.py`), and MQTT command topics. Never hand-add a route or MQTT
   parser for a new command.
2. **`zk_commands/` must stay pyzkaccess-import-free at module level** — the same
   files cross the Wine boundary (Wine Python 3.8 runs `zk_client.py`, native
   Python imports the registry). Import SDK classes lazily inside `execute()`.
   Keep all type syntax Python 3.8 compatible (no PEP 604 `X | None`, etc.).
3. **All device SDK calls are short-lived subprocesses** (`bridge_manager.py`,
   serialized via `ZK_LOCK`). Never spawn long-lived Wine *python/SDK*
   processes; process exit is the memory-leak defense. `wineserver -p` (started
   in the Dockerfile CMD) is the exception and is required: it holds only
   Wine's own service daemon, and without it each call re-bootstraps the Wine
   prefix (measured 10.1s -> 5.3s per request).
   **Latency budget per device command:** ~1.2s python+pyzkaccess import,
   plus the SDK round-trips, plus queue wait behind `ZK_LOCK`. Because of this,
   prefer ONE command that returns everything a page needs over several small
   ones, and batch SDK reads (see `_batch_read_params`: all door+device params
   in <=3 `get_device_param` calls instead of one call per property).
   **Never call the bridge from the event loop.** `run_zk_command` blocks for
   seconds; `async def` routes must wrap it in `run_in_threadpool` (sync `def`
   routes are fine — FastAPI threadpools them). Regression coverage:
   `tests/test_concurrency.py`. Symptom if broken: DB-only endpoints return
   empty bodies / NetworkError while a device read is in flight.
   Correspondingly, the UI only auto-refreshes DB-backed views
   (`AUTO_REFRESH_VIEWS` in `frontend/src/main.js`); device-reading views
   (Doors/Access/Device) refresh on demand and are `guardLoad`-wrapped so
   overlapping loads can't queue up on the hardware lock.
   All device-backed calls from the UI must go through `apiGetDevice`/
   `apiSendDevice`, which serialize them in `deviceQueue` and drive the
   `#device-busy` indicator. Browsers allow only ~6 connections per host, so
   unqueued multi-second device requests head-of-line block even DB calls.
   Wide tables (Timezone etc.) need a bigger query buffer than pyzkaccess
   estimates or the SDK fails with errors like -112 — see `ReadTable.WIDE_TABLES`
   and its escalating retry.
4. **Schemas with free/SPEC data** live in `zk_commands/spec.py` (`TABLE_SCHEMAS`,
   `DOOR_PARAM_SPECS`, `DEVICE_PARAM_SPECS`) — it drives backend validation *and*
   the web UI form generation via `/api/schemas`.
5. **Cardholder names are gateway-side only** (`user_names` table) — the device
   User table has no name field. Door access = `UserAuthorize` table (doors is a
   bitmask, bit0 = Door 1).
6. **Read path is cache-first.** Device reads that back UI pages declare
   `cache_key` (e.g. `ReadTable.cache_key = "table:{table}"`); `_execute_command`
   serves them from the `device_cache` table and only talks to the controller
   when the cache is empty or `?refresh=1` is passed. Mutating commands declare
   `invalidates` (templates, trailing `*` clears a family) so the next read is
   authoritative. `state_dump` also returns the batched door/device params, so
   one full-sync subprocess warms every parameter cache. Cached page loads are
   ~5-20ms vs ~5s for a controller round-trip.
   In the UI, only the explicit "Reload from Device"/Refresh buttons pass
   `{refresh: true}`; views show `cacheBadge()` so the data's age is visible.
   Never add a periodic job that re-reads config — the only recurring device
   traffic is the event poll.
7. **Events**: poll uses RTLog (`rt_events` command, `GetRTLog` consumes the
   device read pointer) — full history backfill from the Transaction table in
   `full_sync`. `ZK_EVENT_SOURCE=table` reverts to polling the table directly.
   `EVENT_TYPE_MAP` mirrors `pyzkaccess.enums.EVENT_TYPES` — the API/HA/frontend
   share it via `/api/schemas`; do not re-duplicate it on the frontend.
8. Event descriptions/contact topics in HA come from the DB (`get_latest_event_per_door`),
   re-published each cycle so HA sensors never go Unknown.

## Env vars

`ZKT_CONNSTR`, `MQTT_BROKER/PORT/USER/PASSWORD`, `DB_PATH`, `ZK_SYNC_INTERVAL`,
`ZK_FULL_SYNC_INTERVAL`, `ZK_RT_POLL_TIMEOUT`, `ZK_EVENT_SOURCE` (rt|table),
`ZK_BRIDGE_TIMEOUT`, `ZK_DEBUG`, `TZ`.
