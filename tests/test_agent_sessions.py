from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))

import agent_routes


def test_root_only_session_key_uses_root_sessions_dir(tmp_path, monkeypatch):
    root_dir = tmp_path / "webprojects"
    root_sessions = root_dir / ".clawmate" / "sessions"
    root_sessions.mkdir(parents=True)

    monkeypatch.setattr(agent_routes, "_resolve_root_dir", lambda root_id: root_dir)

    assert (
        agent_routes._session_log_dir("codex:webprojects", str(root_dir))
        == root_sessions
    )


def test_session_query_includes_root_and_project_session_dirs(tmp_path):
    root_dir = tmp_path / "webprojects"
    (root_dir / ".clawmate" / "sessions").mkdir(parents=True)
    (root_dir / "clawmate" / ".clawmate" / "sessions").mkdir(parents=True)
    (root_dir / "plain").mkdir()

    assert agent_routes._projects_for_session_query(root_dir, "", "") == [
        ("", root_dir),
        ("clawmate", root_dir / "clawmate"),
    ]


def test_session_query_still_limits_to_explicit_project(tmp_path):
    root_dir = tmp_path / "webprojects"
    (root_dir / ".clawmate" / "sessions").mkdir(parents=True)
    (root_dir / "clawmate" / ".clawmate" / "sessions").mkdir(parents=True)

    assert agent_routes._projects_for_session_query(root_dir, "clawmate", "") == [
        ("clawmate", root_dir / "clawmate"),
    ]
