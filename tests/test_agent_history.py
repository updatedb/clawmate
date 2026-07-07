import json
import sys
import time
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


def test_find_codex_transcript_does_not_fallback_across_project_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    session_dir = home / ".codex" / "sessions" / "2026" / "07" / "05"
    session_dir.mkdir(parents=True)
    transcript = session_dir / "rollout-2026-07-05T22-29-10-test.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-05T14:29:29.119Z",
                "type": "session_meta",
                "payload": {"cwd": "/home/openclaw/webprojects/clawmate"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_routes.Path, "home", lambda: home)

    started_at = time.mktime(time.strptime("2026-07-05 20:51:02", "%Y-%m-%d %H:%M:%S"))

    assert agent_routes._find_codex_transcript("/home/openclaw/helper/3gpp/notes", started_at) is None


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
    assert data["sessions"][0]["instruction_count"] == 2
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

    assert listed["instruction_count"] == 2
    assert listed["turn_count"] == 1
    assert detail["instruction_count"] == 2
    assert detail["turn_count"] == 1
    assert detail["meta"]["cwd"] == str(tmp_path)
    assert log_data["total_turns"] == 2
    assert log_data["instruction_count"] == 1
    assert len(log_data["turns"]) == 2
    assert log_data["turns"][0]["content"] == "line one\nline two"
    assert log_data["turns"][0]["turn_index"] == 1
    assert log_data["turns"][1]["turn_index"] == 1


def test_session_cwd_helper_prefers_index_over_path(tmp_path):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {
                "id": "stored-cwd",
                "backend": "codex",
                "cwd": "/home/openclaw/webprojects/clawmate",
                "started_at": 10,
                "status": "ended",
            },
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

    assert agent_routes._session_cwd_from_log_dir(sess_dir, "stored-cwd") == "/home/openclaw/webprojects/clawmate"


def test_collect_transcript_derives_cwd_from_session_dir_when_runtime_cwd_missing(tmp_path, monkeypatch):
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)

    captured = {}

    def fake_parse_transcript(cwd, backend, started_at, ended_at=0):
        captured["cwd"] = cwd
        captured["backend"] = backend
        captured["started_at"] = started_at
        captured["ended_at"] = ended_at
        return []

    monkeypatch.setattr(agent_routes, "_parse_transcript", fake_parse_transcript)

    sess = SimpleNamespace(
        logger=SimpleNamespace(session_id="sid"),
        cwd="",
        key="codex:root:project",
        created_at=123.0,
    )

    agent_routes._collect_transcript(sess, sess_dir)

    assert captured["cwd"] == str(tmp_path)
    assert sess.cwd == str(tmp_path)
    assert captured["backend"] == "codex"


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


def test_session_dates_returns_sorted_dates(tmp_path, monkeypatch):
    """``/sessions/dates`` returns sorted ``{dates: [\"2026-07-06\", ...]}``."""
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {"id": "s1", "backend": "claude", "started_at": 1783077199, "status": "ended"},  # 2026-07-03
            {"id": "s2", "backend": "codex", "started_at": 1783163599, "status": "ended"},  # 2026-07-04
            {"id": "s3", "backend": "claude", "started_at": 1783250000, "status": "ended"},  # 2026-07-05
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(sess_dir, "s1", [{"role": "user", "content": "a", "ts": 1}])
    _write_session(sess_dir, "s2", [{"role": "user", "content": "b", "ts": 2}])
    _write_session(sess_dir, "s3", [{"role": "user", "content": "c", "ts": 3}])

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

    res = client.get("/api/clawmate/agent/sessions/dates?root=root")
    assert res.status_code == 200
    data = res.json()
    assert "dates" in data
    assert data["dates"] == ["2026-07-05", "2026-07-04", "2026-07-03"]


def test_session_dates_excludes_active_sessions(tmp_path, monkeypatch):
    """Active session IDs are excluded from the dates list."""
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    index = {
        "version": 1,
        "sessions": [
            {"id": "active-sess", "backend": "claude", "started_at": 1783077199, "status": "active"},
            {"id": "ended-sess", "backend": "claude", "started_at": 1783163599, "status": "ended"},
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(sess_dir, "active-sess", [{"role": "user", "content": "x", "ts": 1}])
    _write_session(sess_dir, "ended-sess", [{"role": "user", "content": "y", "ts": 2}])

    monkeypatch.setattr(
        agent_routes,
        "load_cfg",
        lambda: SimpleNamespace(roots=[SimpleNamespace(id="root", dir=str(tmp_path))]),
    )
    async def noop_cleanup():
        return None
    monkeypatch.setattr(agent_routes, "_cleanup_dead_sessions", noop_cleanup)
    agent_routes._sessions.clear()
    # Simulate an active session
    fake_active = SimpleNamespace()
    fake_active.logger = SimpleNamespace()
    fake_active.logger.session_id = "active-sess"
    agent_routes._sessions["active"] = fake_active

    app = FastAPI()
    app.include_router(agent_routes.router)
    client = TestClient(app)

    res = client.get("/api/clawmate/agent/sessions/dates?root=root")
    assert res.status_code == 200
    data = res.json()
    assert data["dates"] == ["2026-07-04"]


def test_session_list_filters_by_date(tmp_path, monkeypatch):
    """``/sessions?date=YYYY-MM-DD`` returns only sessions with that date."""
    sess_dir = tmp_path / ".clawmate" / "sessions"
    sess_dir.mkdir(parents=True)
    import time
    today = time.strftime("%Y-%m-%d")
    # Create two sessions with explicit timestamps
    index = {
        "version": 1,
        "sessions": [
            {"id": "s1", "backend": "claude", "started_at": 1783077199, "status": "ended"},  # 2026-07-03
            {"id": "s2", "backend": "codex", "started_at": 1783163599, "status": "ended"},  # 2026-07-04
        ],
    }
    (sess_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    _write_session(sess_dir, "s1", [{"role": "user", "content": "a", "ts": 10}])
    _write_session(sess_dir, "s2", [{"role": "user", "content": "b", "ts": 20}])

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

    # Filter to 2026-07-04 — should only get s2
    res = client.get("/api/clawmate/agent/sessions?root=root&date=2026-07-04")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["sessions"][0]["id"] == "s2"


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


def test_file_context_prompt_prefills_file_only():
    prompt, clean = agent_routes._build_file_context_prompt("/tmp/demo.md")

    assert prompt == "---\n@/tmp/demo.md\n---\n"
    assert clean == "---\n@/tmp/demo.md\n---"
    assert "分析文件" not in prompt
    assert "摘要（≤100字）" not in prompt


def test_agent_routes_has_no_colored_echo_suppression_channel():
    source = Path(agent_routes.__file__).read_text(encoding="utf-8")

    assert "suppress_echo_once" not in source
    assert "_write_pty_with_optional_echo_suppression" not in source
