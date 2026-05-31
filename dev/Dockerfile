# ── ClawMate v0.1 ──────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

WORKDIR /app

# copy python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# copy application
COPY main.py routes.py service.py ./
COPY static/ static/

ENV CLAWMATE_PORT=5533
EXPOSE 5533

CMD ["python", "-u", "main.py"]
