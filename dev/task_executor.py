"""Single launch point for unattended ClawMate agent tasks.

The executors deliberately only acknowledge a CLI after ``Popen`` succeeded,
and a Gateway task after the hook returned its run id.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("clawmate.executor")
BACKENDS = frozenset({"claude", "codex", "openclaw", "auto"})
CLI_BACKENDS = frozenset({"claude", "codex"})


@dataclass(frozen=True)
class LaunchReceipt:
    task_run_id: str
    backend_requested: str
    backend_actual: str = ""
    external_run_id: str = ""
    status: str = "failed"
    started_at: str = ""
    failure_reason: str = ""

    def payload(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskExecutor:
    def __init__(self, cfg):
        self.cfg = cfg

    def _receipt(self, task_run_id, requested, actual="", external="", status="failed", reason=""):
        return LaunchReceipt(task_run_id, requested, actual, str(external or ""), status, _now(), reason)

    def _cli_binary(self, backend: str) -> str | None:
        return shutil.which(backend)

    def _preflight_cli(self, backend: str) -> str:
        binary = self._cli_binary(backend)
        if not binary:
            return "CLI executable unavailable"
        try:
            result = subprocess.run([binary, "--version"], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return "" if result.returncode == 0 else "CLI capability check failed"
        except (OSError, subprocess.SubprocessError):
            return "CLI capability check failed"

    def _preflight_gateway(self, root_id: str) -> str:
        if not self.cfg.openclaw.hook_token or not self.cfg.openclaw.gateway_url:
            return "Gateway configuration unavailable"
        if not self.cfg.root_agent(root_id):
            return "Gateway root agent routing unavailable"
        try:
            # No task is submitted by a preflight.
            response = httpx.get(self.cfg.openclaw.gateway_url.rstrip("/") + "/health", timeout=3.0)
            return "" if response.status_code < 500 else "Gateway unavailable"
        except httpx.HTTPError:
            return "Gateway unavailable"

    def _preflight(self, backend: str, root_id: str) -> str:
        return self._preflight_cli(backend) if backend in CLI_BACKENDS else self._preflight_gateway(root_id)

    def launch(self, *, task_run_id: str, message: str, cwd: str, root_id: str,
               backend: str | None = None, name: str = "clawmate-task") -> LaunchReceipt:
        requested = str(backend or self.cfg.agent.backend).strip().lower()
        if requested not in BACKENDS:
            return self._receipt(task_run_id, requested, reason="Unsupported backend")
        candidates = ("codex", "claude", "openclaw") if requested == "auto" else (requested,)
        failures = []
        for actual in candidates:
            reason = self._preflight(actual, root_id)
            if reason:
                failures.append(f"{actual}: {reason}")
                continue
            if actual == "openclaw":
                return self._launch_gateway(task_run_id, requested, message, root_id, name)
            return self._launch_cli(task_run_id, requested, actual, message, cwd)
        return self._receipt(task_run_id, requested, reason="; ".join(failures) or "No executor available")

    def _launch_cli(self, task_run_id, requested, backend, message, cwd):
        binary = self._cli_binary(backend)
        env = os.environ.copy()
        env.update(self.cfg.agent.env or {})
        if backend == "claude":
            env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
            args = [binary, "--dangerously-skip-permissions", "-p", message]
        else:
            args = [binary, "-p", message]
        try:
            proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env, start_new_session=True)
            return self._receipt(task_run_id, requested, backend, proc.pid, "started")
        except OSError:
            return self._receipt(task_run_id, requested, backend, reason="CLI process could not start")

    def _launch_gateway(self, task_run_id, requested, message, root_id, name):
        try:
            response = httpx.post(self.cfg.openclaw.gateway_url.rstrip("/") + "/hooks/agent", timeout=10.0,
                headers={"Authorization": "Bearer " + self.cfg.openclaw.hook_token},
                json={"message": message, "agentId": self.cfg.root_agent(root_id), "name": name,
                      "wakeMode": "now", "deliver": False})
            data = response.json() if response.status_code == 200 else {}
            run_id = data.get("runId")
            if response.status_code == 200 and run_id:
                return self._receipt(task_run_id, requested, "openclaw", run_id, "started")
            return self._receipt(task_run_id, requested, "openclaw", reason="Gateway did not acknowledge run")
        except (httpx.HTTPError, ValueError):
            return self._receipt(task_run_id, requested, "openclaw", reason="Gateway request failed")


def persist_project_receipt(project_dir: Path, receipt: LaunchReceipt) -> None:
    """Append independent project run history without touching feedback audit."""
    path = project_dir / ".clawmate" / "task-runs.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt.payload(), ensure_ascii=False) + "\n")
