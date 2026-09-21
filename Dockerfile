# ─────────────────────────────────────────────
# Stage 1: build the React/Vite frontend
# ─────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ─────────────────────────────────────────────
# Stage 2: Python runtime + prototype API
# ─────────────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r server/requirements.txt gunicorn

COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY frontend/public ./frontend/public
COPY server/ ./server/

EXPOSE 8080
WORKDIR /app/server

CMD ["sh", "-c", "gunicorn --bind=0.0.0.0:${PORT:-8080} --workers=2 --timeout=120 --worker-class=uvicorn.workers.UvicornWorker api:app"]
