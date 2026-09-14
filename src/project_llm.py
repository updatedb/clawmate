"""Small, deliberately constrained LLM adapter for project task discovery.

The adapter is intentionally injectable: production integrations may register a
backend client, while discovery remains deterministic and offline-safe when no
client is available. It never executes a model-supplied command.
"""
from __future__ import annotations

import json
from collections.abc import Callable

_clients: dict[str, Callable[[str, float], str | dict | list | None]] = {}


def build_prompt(project_type: str, documents: dict[str, str], template: str) -> str:
    corpus = "\n\n".join(f"## {name}\n{text}" for name, text in documents.items())
    return (
        "你是项目管理任务提炼器。只根据以下本地文档提炼任务，不执行任何操作，"
        "不输出凭据、命令、路径或文档原文。返回 JSON 数组，每项仅含 "
        "label、kind、priority、reason 和可选 script。label 为简短中文动作。\n"
        f"项目类型：{project_type}\n管理模板：{template}\n文档：\n{corpus}"
    )


def extract(backend: str, project_type: str, documents: dict[str, str], template: str,
            timeout: float = 8.0) -> object | None:
    """Invoke a trusted configured adapter; unavailable backends return None.

    ``auto`` selects an explicitly registered adapter in stable order. The
    application does not shell out to a CLI here: discovery must not create an
    unbounded agent process merely to refresh an overview.
    """
    backend = (backend or "auto").lower()
    if backend == "auto":
        backend = next((name for name in ("openclaw", "codex", "claude") if name in _clients), "")
    client = _clients.get(backend)
    if not client:
        return None
    try:
        result = client(build_prompt(project_type, documents, template), timeout)
    except Exception:
        return None
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None
    return result
