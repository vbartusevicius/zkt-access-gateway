# Stage 1: Build Frontend
FROM node:18 AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
# Don't fail if package.json doesn't exist yet, we will create it shortly
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Main Image
FROM tobix/pywine:3.8

# Install native linux dependencies and python3 for the API
RUN apt-get update \
    && apt-get install -y python3 curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Install UV for fast package management of the native backend
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

WORKDIR /app

# The pyzkaccess package requires the PULL SDK dlls to be installed in the Wine windows/system32 directory.
# This requires installing pyzkaccess in the WINE python environment.
RUN wine python -m pip install --no-cache-dir pyzkaccess

# We extract the pull sdk and place the pl*.dll files into wine system32
COPY resources/pull_sdk.zip .
RUN unzip -q pull_sdk.zip -d /sdk_temp \
    && cp /sdk_temp/SDK-Ver2.2.0.220/pl*.dll ${WINEPREFIX}/drive_c/windows/system32/ \
    && rm -rf /sdk_temp pull_sdk.zip

# Setup the native Linux backend
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into the backend's static directory to serve it
COPY --from=frontend-builder /build/dist ./backend/static

EXPOSE 8000

ENV ZKT_CONNSTR=""
ENV MQTT_BROKER=""

ENV PATH="/app/.venv/bin:$PATH"

# Start the API server, explicitly enforcing a 0-byte core dump limit to prevent QEMU memory dumps on failure
CMD ["/bin/sh", "-c", "ulimit -c 0 && exec uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
