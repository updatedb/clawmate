# ── ClawMate v1.5 — File Browser + Preview + Feedback ──────────────
# Build:
#   docker build -t clawmate .
# Run:
#   docker run -d -p 5533:5533 \
#     -v /path/to/config.json:/app/config.json:ro \
#     -v /path/to/data:/data:ro \
#     -e CLAWMATE_HOOK_TOKEN=xxx \
#     -e CLAWMATE_PUBLIC_BASE_URL=https://your-domain.com:5533 \
#     clawmate
# 字幕功能：构建时设置 CLAWMATE_ENABLE_SUBTITLE=1 安装 faster-whisper（~2GB）
#   docker build --build-arg CLAWMATE_ENABLE_SUBTITLE=1 -t clawmate:latest dev/
ARG CLAWMATE_ENABLE_SUBTITLE=0

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

# copy python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# copy application
COPY *.py task_templates.json ./
COPY static/ static/

ENV CLAWMATE_PORT=5533
EXPOSE 5533

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5533/clawmate/').read()" || exit 1

CMD ["python", "-u", "main.py"]
