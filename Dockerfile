# ── ClawMate v1.5 — File Browser + Preview + Feedback ──────────────
# Build:
#   docker build -t clawmate .
# Run:
#   docker run -d -p 5533:5533 \
#     -v /path/to/config.json:/app/config.json:ro \
#     -v /openclaw/store/data:/data \
#     -e CLAWMATE_PUBLIC_BASE_URL=https://your-domain.com:5533 \
#     clawmate
# 字幕功能：构建时设置 CLAWMATE_ENABLE_SUBTITLE=1 安装 faster-whisper（~2GB）
#   docker build --build-arg CLAWMATE_ENABLE_SUBTITLE=1 -t clawmate:latest .
ARG CLAWMATE_ENABLE_SUBTITLE=0

FROM node:22-alpine AS frontend

WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY dev/frontend ./dev/frontend
RUN npm run build:terminal

FROM node:22-bookworm-slim AS node-runtime

FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
COPY requirements-opt.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$CLAWMATE_ENABLE_SUBTITLE" = "1" ]; then \
         pip install --no-cache-dir -r requirements-opt.txt; \
       fi

FROM python:3.11-slim AS runtime

WORKDIR /app

# Node/npm are required to install the agent CLIs on container startup.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

# runtime dependencies: ripgrep for content search, ffmpeg for subtitle extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
      ripgrep \
    && rm -rf /var/lib/apt/lists/*

# copy python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# copy application (dev/ 子目录)
COPY dev/*.py ./
COPY task_templates.json ./
COPY dev/static/ static/
COPY --from=frontend /src/dev/static/dist/ static/dist/

ENV CLAWMATE_PORT=5533
EXPOSE 5533

# Health check — 每 30s 探测一次，启动 10s 后开始
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5533/api/health').read()" || exit 1

CMD ["sh", "-c", "if [ \"${CLAWMATE_INSTALL_AGENT_CLIS:-1}\" != \"0\" ]; then command -v claude >/dev/null 2>&1 || npm install --global @anthropic-ai/claude-code; command -v codex >/dev/null 2>&1 || npm install --global @openai/codex; fi; exec python -u main.py"]
