# 13f — the public demo of the 13F screener.
#
# Two stages, one runtime container. The edge proxies one hostname to one port,
# so unlike local development (Vite on 5173, FastAPI on 9001) the deployed demo
# has to answer both the page and the API from the same process: the Node stage
# builds the React bundle, and FastAPI serves it through F8_STATIC_DIR.
#
# Nothing in the image reaches SEC, and nothing writes to a real database. The
# only data it has is the frozen snapshot committed at demo/fixtures/.

ARG NODE_VERSION=20
ARG PYTHON_VERSION=3.12

# --- stage 1: the React bundle --------------------------------------------
FROM node:${NODE_VERSION}-alpine AS frontend
WORKDIR /src
# Lockfile first so a source change does not reinstall the toolchain.
COPY repo/frontend/package.json repo/frontend/package-lock.json ./
RUN npm ci
COPY repo/frontend/ ./
RUN npm run build

# --- stage 2: the API that serves it --------------------------------------
FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies before source, so editing a route does not reinstall pandas.
COPY repo/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY repo/src/ /app/src/
COPY repo/demo/ /app/demo/
COPY --from=frontend /src/dist /app/frontend/dist

# src/core/paths.py creates its data and log directories at import time. The
# container runs read-only, so those mkdir calls would fail -- unless the
# directories already exist, in which case mkdir(exist_ok=True) returns without
# writing anything. Compose also mounts a tmpfs over each of them, so a
# directory added to that list later cannot break the demo either.
RUN mkdir -p \
      /app/src/core/data/realtime/notifications/queue \
      /app/src/core/data/historical/catalog \
      /app/src/core/data/historical/holdings \
      /app/src/core/data/historical/tracking \
      /app/src/core/data/messages \
      /app/src/core/data/cache \
      /app/src/core/logs \
      /app/src/core/config \
      /app/cache/dashboard

# Stamp the shipped ticker index against the snapshot's mtime *in this layer*.
# Without it the first request decides the index is stale and rebuilds it,
# which means calling SEC for the ticker reference from a container that is
# supposed to reach nothing. Done at build time so it also holds when the
# filesystem is read-only at runtime.
RUN DEMO_MODE=true \
    DEMO_SESSION_SECRET=build-time-only \
    DEMO_PUBLIC_URL=http://build-time-only \
    F8_DASHBOARD_DB=/app/demo/fixtures/13f_demo.duckdb \
    python -c "from src.api import demo; demo.stamp_ticker_index()"

RUN useradd --create-home --uid 10001 demo && chown -R demo:demo /app/cache
USER demo

EXPOSE 8000
CMD ["python", "-m", "src.api"]
