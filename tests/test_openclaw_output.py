import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))

import agent_routes


def test_openclaw_text_extractor_handles_final_message_content():
    payload = {
        "message": {
            "content": [
                {"type": "text", "text": "收到，测试正常 ✅"},
            ]
        }
    }

    assert agent_routes._extract_openclaw_text(payload) == "收到，测试正常 ✅"


def test_openclaw_session_key_is_scoped_to_root_and_project(tmp_path, monkeypatch):
    root_path = tmp_path / "webprojects"
    (root_path / "clawmate" / ".clawmate").mkdir(parents=True)
    monkeypatch.setattr(agent_routes, "_resolve_root_dir", lambda root: root_path)

    first = agent_routes._openclaw_session_key("work", "webprojects", "clawmate/src")
    second = agent_routes._openclaw_session_key("work", "webprojects", "other")
    assert first != second
    assert first == "agent:work:clawmate:openclaw-webprojects-clawmate"
