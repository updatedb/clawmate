import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
if str(DEV) not in sys.path:
    sys.path.insert(0, str(DEV))

import agent_routes


def _write_session(log_dir: Path, session_id: str, chat_lines: list[dict] | None):
    if chat_lines is not None:
        with (log_dir / f"{session_id}.chat.jsonl").open("w", encoding="utf-8") as f:
            for line in chat_lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")


def test_session_list_filters_empty_chat_logs_and_returns_instruction_count(tmp_path, monkeypatch):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {"id": "empty-file", "backend": "claude", "started_at": 30, "status": "ended"},
            {"id": "empty-content", "backend": "claude", "started_at": 20, "status": "ended"},
            {"id": "with-turns", "backend": "codex", "started_at": 10, "status": "ended"},
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(sess_dir, "empty-file", [])
    _write_session(sess_dir, "empty-content", [{"role": "user", "content": "", "ts": 20}])
    _write_session(
        sess_dir,
        "with-turns",
        [
            {"role": "user", "content": "hello", "ts": 10},
            {"role": "assistant", "content": "hi", "ts": 11},
        ],
    )

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )
    async def noop_cleanup():
        return None

    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    res = client.get("/api/clawmate/agent/sessions?root=root")

    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert [s["id"] for s in data["sessions"]] == ["with-turns"]
    assert data["sessions"][0]["instruction_count"] == 1
    assert data["sessions"][0]["turn_count"] == 1


def test_session_instruction_count_matches_detail_turns(tmp_path, monkeypatch):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {"id": "merged-input", "backend": "codex", "started_at": 10, "status": "ended"},
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    (sess_dir / "merged-input.meta.json").write_text(
        json.dumps({"session_id": "merged-input", "backend": "codex", "started_at": 10}),
        encoding="utf-8",
    )
    _write_session(
        sess_dir,
        "merged-input",
        [
            {"role": "user", "content": "line one", "ts": 10.0},
            {"role": "user", "content": "line two", "ts": 10.5},
            {"role": "assistant", "content": "reply", "ts": 11.0},
            {"role": "assistant", "content": "", "ts": 12.0},
        ],
    )

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )

    async def noop_cleanup():
        return None

    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    list_res = client.get("/api/clawmate/agent/sessions?root=root")
    detail_res = client.get("/api/clawmate/agent/sessions/merged-input?root=root")
    log_res = client.get("/api/clawmate/agent/sessions/merged-input/log?root=root")

    assert list_res.status_code == 200
    assert detail_res.status_code == 200
    assert log_res.status_code == 200

    listed = list_res.json()["sessions"][0]
    detail = detail_res.json()
    log_data = log_res.json()

    assert listed["instruction_count"] == 1
    assert listed["turn_count"] == 1
    assert detail["instruction_count"] == 1
    assert detail["turn_count"] == 1
    assert log_data["total_turns"] == 2
    assert log_data["instruction_count"] == 1
    assert len(log_data["turns"]) == 2
    assert log_data["turns"][0]["content"] == "line one\nline two"
    assert log_data["turns"][0]["turn_index"] == 1
    assert log_data["turns"][1]["turn_index"] == 1


def test_session_log_assigns_turn_index_per_user_instruction(tmp_path, monkeypatch):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {"id": "two-rounds", "backend": "codex", "started_at": 10, "status": "ended"},
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(
        sess_dir,
        "two-rounds",
        [
            {"role": "user", "content": "first", "ts": 10.0},
            {"role": "assistant", "content": "first reply", "ts": 11.0},
            {"role": "user", "content": "second", "ts": 12.0},
            {"role": "assistant", "content": "second reply", "ts": 13.0},
        ],
    )

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )

    async def noop_cleanup():
        return None

    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    res = client.get("/api/clawmate/agent/sessions/two-rounds/log?root=root")

    assert res.status_code == 200
    turns = res.json()["turns"]
    assert [t["turn_index"] for t in turns] == [1, 1, 2, 2]


def test_session_list_returns_stored_session_key_when_present(tmp_path, monkeypatch):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {
                "id": "stored-key",
                "backend": "codex",
                "key": "codex:root:project-a",
                "started_at": 10,
                "status": "ended",
            },
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(
        sess_dir,
        "stored-key",
        [
            {"role": "user", "content": "hello", "ts": 10.0},
            {"role": "assistant", "content": "hi", "ts": 11.0},
        ],
    )

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )

    async def noop_cleanup():
        return None

    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    res = client.get("/api/clawmate/agent/sessions?root=root")

    assert res.status_code == 200
    session = res.json()["sessions"][0]
    assert session["sessionKey"] == "codex:root:project-a"


def test_session_list_falls_back_to_derived_session_key(tmp_path, monkeypatch):
    root_sess_dir = tmp_path / ".clawmate" / "sessions"
    project_sess_dir = tmp_path / "project-a" / ".clawmate" / "sessions"
    root_sess_dir.mkdir(parents=True)
    project_sess_dir.mkdir(parents=True)
    root_index = {
        "version": 1,
        "sessions": [
            {"id": "root-session", "backend": "codex", "started_at": 20, "status": "ended"},
        ],
    }
    project_index = {
        "version": 1,
        "sessions": [
            {"id": "project-session", "backend": "claude", "started_at": 10, "status": "ended"},
        ],
    }
    (root_sess_dir / "index.json").write_text(json.dumps(root_index), encoding="utf-8")
    (project_sess_dir / "index.json").write_text(json.dumps(project_index), encoding="utf-8")
    _write_session(
        root_sess_dir,
        "root-session",
        [
            {"role": "user", "content": "root turn", "ts": 20.0},
            {"role": "assistant", "content": "root reply", "ts": 21.0},
        ],
    )
    _write_session(
        project_sess_dir,
        "project-session",
        [
            {"role": "user", "content": "project turn", "ts": 10.0},
            {"role": "assistant", "content": "project reply", "ts": 11.0},
        ],
    )

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )

    async def noop_cleanup():
        return None

    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    res = client.get("/api/clawmate/agent/sessions?root=root")

    assert res.status_code == 200
    sessions = {s["id"]: s for s in res.json()["sessions"]}
    assert sessions["root-session"]["sessionKey"] == "codex:root"
    assert sessions["project-session"]["sessionKey"] == "claude:root:project-a"
