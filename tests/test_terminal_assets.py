import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_xterm_6_dependencies_are_pinned():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@xterm/xterm"] == "6.0.0"
    assert package["dependencies"]["@xterm/addon-fit"] == "0.11.0"
    assert package["dependencies"]["@xterm/addon-search"] == "0.16.0"
    assert package["dependencies"]["@xterm/addon-serialize"] == "0.14.0"
    assert package["dependencies"]["@xterm/addon-webgl"] == "0.19.0"


def test_terminal_assets_are_shipped_without_runtime_cdn_dependencies():
    service_worker = (ROOT / "dev/static/sw.js").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/docker.yml").read_text(encoding="utf-8")

    assert "/clawmate/dist/terminal.js" in service_worker
    assert "/clawmate/dist/terminal.css" in service_worker
    assert "FROM node:22-alpine AS frontend" in dockerfile
    assert "npm ci" in dockerfile
    assert "npm run build:terminal" in dockerfile
    assert "npm ci" in install
    assert "npm run build:terminal" in install
    assert "npm ci" in workflow
    assert "npm test" in workflow


def test_replay_exposes_loading_status_until_terminal_output_is_restored():
    source = (ROOT / "dev/frontend/terminal/agent-panel-adapter.ts").read_text(encoding="utf-8")

    assert "this.setStatus('加载中')" in source
    assert "replayComplete" in source
    assert "this.setStatus('已连接')" in source
