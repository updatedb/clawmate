"""
ClawMate shared constants — imported by routes.py, service.py, feedback_api.py.
"""

# Config env var names
PUBLIC_BASE_URL_ENV = "CLAWMATE_PUBLIC_BASE_URL"
CONFIG_PATH_ENV = "CLAWMATE_CONFIG"
ONLYOFFICE_JWT_SECRET_ENV = "CLAWMATE_ONLYOFFICE_JWT_SECRET"
ONLYOFFICE_URL_ENV = "CLAWMATE_ONLYOFFICE_URL"

# Graceful shutdown budget. uvicorn's own default is None, which waits forever
# for connections/tasks to drain. Long-lived WebSocket proxies (OpenClaw chat,
# terminal v2) and the idle reaper never drain on their own, so an unbounded
# wait leaves the process stuck in "deactivating" until the service manager
# SIGKILLs it. A bounded budget lets uvicorn cancel those tasks and exit.
GRACEFUL_SHUTDOWN_TIMEOUT_ENV = "CLAWMATE_GRACEFUL_SHUTDOWN_SECONDS"
DEFAULT_GRACEFUL_SHUTDOWN_SECONDS = 15
