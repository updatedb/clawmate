"""
ClawMate Request Logging Middleware — 结构化访问日志。

记录每个请求的 method、path、status_code、response_time_ms。
日志格式为 JSON Lines，方便后续接入日志分析工具。
"""

from __future__ import annotations

import logging
import time
import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("clawmate.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的方法、路径、状态码、耗时。"""

    # 不记录日志的路径前缀（健康检查等高频请求）
    _SKIP_PREFIXES = ("/api/health",)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 跳过不需要记录的健康检查等路径
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000, 1)

        client_ip = request.client.host if request.client else "-"
        logger.info(
            json.dumps(
                {
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                    "client": client_ip,
                },
                ensure_ascii=False,
            )
        )

        return response
