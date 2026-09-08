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
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("clawmate.executor")
BACKENDS = frozenset({"claude", "codex", "openclaw", "auto"})
CLI_BACKENDS = frozenset({"claude", "codex"})


_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
_ACTIVE_LOCK = threading.Lock()


@dataclass(frozen=True)
class LaunchReceipt:
    task_run_id: str
    backend_requested: str
    backend_actual: str = ""
    external_run_id: str = ""
    status: str = "failed"
    started_at: str = ""
    failure_reason: str = ""
    latest_feedback: str = ""
    error: str = ""
    result: str = ""

    def payload(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskExecutor:
    def __init__(self, cfg):
        self.cfg = cfg

    def _receipt(self, task_run_id, requested, actual="", external="", status="failed", reason=""):
        return LaunchReceipt(task_run_id, requested, actual, str(external or ""), status, _now(), reason,
                             "", reason if status == "failed" else "", "")

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
            with _ACTIVE_LOCK:
                _ACTIVE_PROCESSES[task_run_id] = proc
            return self._receipt(task_run_id, requested, backend, proc.pid, "running")
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
                return self._receipt(task_run_id, requested, "openclaw", run_id, "running")
            return self._receipt(task_run_id, requested, "openclaw", reason="Gateway did not acknowledge run")
        except (httpx.HTTPError, ValueError):
            return self._receipt(task_run_id, requested, "openclaw", reason="Gateway request failed")

    def run_summary_analysis(self, message: str, cwd: str, timeout_seconds: int = 90) -> dict:
        """Run the project-panel backend in pipe mode and return its captured output.

        Only CLI backends (codex/claude) support buffered analysis; a gateway
        backend (openclaw) has no local process to capture, so it is skipped.
        'auto' resolves codex first, then claude — never a gateway.
        """
        requested = str(self.cfg.agent.project_backend).strip().lower()
        candidates = ("codex", "claude") if requested == "auto" else (requested,)
        failures = []
        for backend in candidates:
            if backend not in CLI_BACKENDS:
                continue
            binary = self._cli_binary(backend)
            if not binary:
                failures.append(f"{backend}: CLI unavailable")
                continue
            env = os.environ.copy()
            env.update(self.cfg.agent.env or {})
            if backend == "claude":
                env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
            args = [binary, "-p", message]
            try:
                proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                      timeout=timeout_seconds, env=env, start_new_session=True)
            except subprocess.TimeoutExpired:
                failures.append(f"{backend}: timeout")
                continue
            except OSError:
                failures.append(f"{backend}: could not start")
                continue
            return {"ok": proc.returncode == 0, "backend": backend,
                    "output": proc.stdout, "error": proc.stderr, "code": proc.returncode}
        return {"ok": False, "backend": "", "output": "",
                "error": "; ".join(failures) or "No CLI backend available", "code": -1}


def _runs_path(project_dir: Path) -> Path:
    return project_dir / ".clawmate" / "task-runs.jsonl"


def persist_project_receipt(project_dir: Path, receipt: LaunchReceipt, *, task: dict | None = None) -> dict:
    """Append safe project-run metadata without prompt/audit data."""
    project_dir.joinpath(".clawmate").mkdir(parents=True, exist_ok=True)
    record = receipt.payload()
    if task:
        record["task"] = {key: task[key] for key in ("id", "label", "frequency", "estimated_minutes") if key in task}
    path = project_dir / ".clawmate" / "task-runs.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _read_project_runs(project_dir: Path) -> list[dict]:
    """Read only bounded, safe fields from project history (newest first)."""
    path = _runs_path(project_dir)
    if not path.exists():
        return []
    safe = {"task_run_id", "backend_requested", "backend_actual", "external_run_id", "status", "started_at", "latest_feedback", "failure_reason", "error", "result", "task", "ended_at", "exit_code"}
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append({key: value[key] for key in safe if key in value})
    except (OSError, ValueError, json.JSONDecodeError):
        logger.warning("Unable to read project task history")
    return list(reversed(rows))


def update_project_run(project_dir: Path, task_run_id: str, **changes) -> dict | None:
    """Append a state snapshot; JSONL preserves an audit trail and is atomic per line."""
    rows = _read_project_runs(project_dir)
    current = next((row for row in rows if row.get("task_run_id") == task_run_id), None)
    if not current:
        return None
    allowed = {"status", "latest_feedback", "failure_reason", "error", "result", "ended_at", "exit_code"}
    current.update({key: value for key, value in changes.items() if key in allowed and value is not None})
    with _runs_path(project_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(current, ensure_ascii=False) + "\n")
    return current


def refresh_project_runs(project_dir: Path) -> list[dict]:
    """Refresh CLI lifecycle for processes owned by this server; Gateway stays running until callback support exists."""
    runs = _read_project_runs(project_dir)
    refreshed: list[dict] = []
    for run in runs:
        if run.get("status") not in {"starting", "running", "waiting_input"} or run.get("backend_actual") not in CLI_BACKENDS:
            refreshed.append(run)
            continue
        with _ACTIVE_LOCK:
            proc = _ACTIVE_PROCESSES.get(run.get("task_run_id"))
        if proc is None:
            refreshed.append(run)
            continue
        code = proc.poll()
        if code is None:
            refreshed.append(run)
            continue
        with _ACTIVE_LOCK:
            _ACTIVE_PROCESSES.pop(run.get("task_run_id"), None)
        if code == 0:
            updated = update_project_run(project_dir, run["task_run_id"], status="succeeded", result="CLI task completed", exit_code=code, ended_at=_now())
        else:
            updated = update_project_run(project_dir, run["task_run_id"], status="failed", error="CLI task exited with an error", failure_reason="CLI task exited with an error", exit_code=code, ended_at=_now())
        refreshed.append(updated or run)
    # collapse snapshots to newest state per id and preserve newest-first order
    seen: set[str] = set()
    return [row for row in refreshed if not (row.get("task_run_id") in seen or seen.add(row.get("task_run_id")))]
