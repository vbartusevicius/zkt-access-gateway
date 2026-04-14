# ZKTeco Access Gateway

A Dockerized gateway designed to bridge ZKTeco C3 and C4 Access Controllers to modern integrations (like Home Assistant) over MQTT, featuring a beautiful real-time Web UI.

## Working Principles

ZKTeco C3 and C4 devices use a proprietary Windows "PULL SDK" (`pl*.dll`). This application circumvents compatibility issues, allowing deployment straight to an ARM64 system like a Raspberry Pi:

1. **Dual-Environment Docker**: The Dockerfile builds `linux/amd64` images that run via QEMU cross-platform emulation on ARM. 
2. **Native API**: A lightning-fast Python FastAPI application manages your device state, SQLite cache, and MQTT publishing.
3. **Wine Bridge**: When the device needs to sync, the API spins up a short-lived Wine subprocess. This strictly executes the Windows PULL SDK via `pyzkaccess`, preventing Wine-related long-running memory leaks.

## How to Run

The simplest way is using Docker Compose. Ensure your Pi or server has Docker installed.

1. Create a `data/` directory adjacent to the Compose file if needed.
2. Build and start the infrastructure:
```bash
docker compose up --build -d
```
3. Access the Control Panel via **http://your-ip:8000** completely through your browser. 
4. Configure your connection string and MQTT Broker via the Settings panel to discover events!

## How to Develop

The project enforces strict separation of concerns for development ease:

### Frontend
Situated in `/frontend`, built with standard Vite and Vanilla JS/CSS (No Tailwind!). 
* Run `npm install` followed by `npm run dev` to tinker entirely with the User Interface.

### Backend
Situated in `/backend`. Uses `uv` for blistering-fast dependency management.
* Edit `main.py` for API Endpoints.
* Edit `mqtt_manager.py` to change Home Assistant discovery payloads.
* Edit `/backend/wine_script/zk_client.py` to add new functionality communicating directly with the `pyzkaccess` framework.
