"""No-side-effect routing tests for the unattended executor registry."""
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

from task_executor import LaunchReceipt, TaskExecutor, persist_project_receipt


def _cfg(backend="claude"):
    return SimpleNamespace(agent=SimpleNamespace(backend=backend, env={}),
        openclaw=SimpleNamespace(hook_token="x", gateway_url="http://gateway"),
        root_agent=lambda root: "root-agent")


def test_explicit_backends_route_to_their_executor(monkeypatch):
    executor = TaskExecutor(_cfg())
    calls = []
    monkeypatch.setattr(executor, "_preflight", lambda backend, root: "")
    monkeypatch.setattr(executor, "_launch_cli", lambda *args: calls.append(args[2]) or LaunchReceipt(args[0], args[1], args[2], "9", "started"))
    monkeypatch.setattr(executor, "_launch_gateway", lambda *args: calls.append("openclaw") or LaunchReceipt(args[0], args[1], "openclaw", "run", "started"))
    for backend in ("claude", "codex", "openclaw"):
        assert executor.launch(task_run_id=backend, message="x", cwd=".", root_id="r", backend=backend).status == "started"
    assert calls == ["claude", "codex", "openclaw"]


def test_auto_uses_order_and_reports_all_preflight_failures(monkeypatch):
    executor = TaskExecutor(_cfg("auto"))
    reasons = {"codex": "missing", "claude": "missing", "openclaw": "offline"}
    monkeypatch.setattr(executor, "_preflight", lambda backend, root: reasons[backend])
    receipt = executor.launch(task_run_id="x", message="x", cwd=".", root_id="r")
    assert receipt.status == "failed"
    assert receipt.failure_reason == "codex: missing; claude: missing; openclaw: offline"


def test_auto_selects_first_preflighted_backend(monkeypatch):
    executor = TaskExecutor(_cfg("auto"))
    monkeypatch.setattr(executor, "_preflight", lambda backend, root: "missing" if backend == "codex" else "")
    monkeypatch.setattr(executor, "_launch_cli", lambda *args: LaunchReceipt(args[0], args[1], args[2], "123", "started"))
    receipt = executor.launch(task_run_id="x", message="x", cwd=".", root_id="r")
    assert receipt.backend_actual == "claude"


def test_project_receipt_is_jsonl_persisted(tmp_path):
    marker = tmp_path / ".clawmate"
    marker.mkdir()
    receipt = LaunchReceipt("task", "codex", "codex", "42", "started", "now")
    persist_project_receipt(tmp_path, receipt)
    assert '"external_run_id": "42"' in (marker / "task-runs.jsonl").read_text()
