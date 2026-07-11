# Docker Agent CLI Startup Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every ClawMate container start with working `claude` and `codex` CLIs by default, while preserving the existing FastAPI entrypoint.

**Architecture:** Keep the Python runtime image as the base, copy the Node 22 runtime and npm from a dedicated Debian-based Node stage, and run an idempotent shell entrypoint before `python -u main.py`. The entrypoint installs only missing CLIs and can be disabled with `CLAWMATE_INSTALL_AGENT_CLIS=0`.

**Tech Stack:** Docker multi-stage build, Node.js 22/npm, POSIX shell, Python pytest.

---

### Task 1: Add failing Docker contract tests

**Files:**
- Modify: `tests/test_terminal_assets.py`

- [ ] **Step 1: Write the failing tests**

Add tests that read `Dockerfile` and `docker-entrypoint.sh` and assert:

```python
def test_docker_runtime_declares_agent_cli_installation():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint_path = ROOT / "docker-entrypoint.sh"
    assert entrypoint_path.exists()
    entrypoint = entrypoint_path.read_text(encoding="utf-8")

    assert "FROM node:22-bookworm-slim AS node-runtime" in dockerfile
    assert "COPY --from=node-runtime /usr/local/bin/node" in dockerfile
    assert "@anthropic-ai/claude-code" in entrypoint
    assert "@openai/codex" in entrypoint
    assert 'CLAWMATE_INSTALL_AGENT_CLIS="${CLAWMATE_INSTALL_AGENT_CLIS:-1}"' in entrypoint
    assert 'exec "$@"' in entrypoint


def test_docker_entrypoint_skips_install_when_disabled():
    entrypoint_path = ROOT / "docker-entrypoint.sh"
    assert entrypoint_path.exists()
    entrypoint = entrypoint_path.read_text(encoding="utf-8")
    assert 'CLAWMATE_INSTALL_AGENT_CLIS" = "0"' in entrypoint
    assert "exec \"$@\"" in entrypoint
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `dev/.venv/bin/python -m pytest tests/test_terminal_assets.py -q`

Expected: FAIL with assertions because `docker-entrypoint.sh` does not yet exist and the Dockerfile has no Node runtime stage.

### Task 2: Add the idempotent startup installer

**Files:**
- Create: `docker-entrypoint.sh`

- [ ] **Step 1: Implement the minimal entrypoint**

Create an executable POSIX shell script with this behavior:

```sh
#!/bin/sh
set -eu

CLAWMATE_INSTALL_AGENT_CLIS="${CLAWMATE_INSTALL_AGENT_CLIS:-1}"

if [ "$CLAWMATE_INSTALL_AGENT_CLIS" = "0" ]; then
    exec "$@"
fi

install_cli() {
    command_name="$1"
    package_name="$2"
    if command -v "$command_name" >/dev/null 2>&1; then
        echo "[clawmate] $command_name already installed: $(command -v "$command_name")"
        return 0
    fi
    echo "[clawmate] installing $package_name"
    npm install --global "$package_name"
}

install_cli claude @anthropic-ai/claude-code
install_cli codex @openai/codex

exec "$@"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x docker-entrypoint.sh`

- [ ] **Step 3: Run the focused tests**

Run: `dev/.venv/bin/python -m pytest tests/test_terminal_assets.py -q`

Expected: the entrypoint contract assertions pass; Dockerfile assertions remain failing until Task 3.

### Task 3: Provide Node/npm in the Python runtime image

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Add a Debian Node runtime stage**

Add before the Python builder stage:

```dockerfile
FROM node:22-bookworm-slim AS node-runtime
```

- [ ] **Step 2: Copy the Node runtime and npm into the existing Python runtime**

After `FROM python:3.11-slim AS runtime`, copy the Node executable and npm installation from the Debian-compatible stage:

```dockerfile
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
```

Keep `python:3.11-slim` as the base so the existing copied Python packages and `uvicorn` shebang remain valid.

- [ ] **Step 3: Copy and invoke the entrypoint**

Before the healthcheck and `CMD`, add:

```dockerfile
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-u", "main.py"]
```

- [ ] **Step 4: Run the focused tests**

Run: `dev/.venv/bin/python -m pytest tests/test_terminal_assets.py -q`

Expected: PASS.

### Task 4: Document the default and opt-out setting

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Add the compose environment variable**

Add the documented variable and default environment entry:

```yaml
#   CLAWMATE_INSTALL_AGENT_CLIS  选填，启动时安装 Claude/Codex CLI，默认 1；设为 0 跳过
      - CLAWMATE_INSTALL_AGENT_CLIS=${CLAWMATE_INSTALL_AGENT_CLIS:-1}
```

- [ ] **Step 2: Document startup requirements**

In the Docker deployment section, state that the first startup requires npm registry access, installs missing `claude` and `codex`, and can skip installation with `CLAWMATE_INSTALL_AGENT_CLIS=0`.

- [ ] **Step 3: Run whitespace and focused tests**

Run: `git diff --check && dev/.venv/bin/python -m pytest tests/test_terminal_assets.py -q`

Expected: no diff errors and all focused tests pass.

### Task 5: Build and runtime verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Build the image**

Run: `docker build -t clawmate-agent-cli-test .`

Expected: build completes successfully and the runtime stage contains `/usr/local/bin/node` and `/usr/local/bin/npm`.

- [ ] **Step 2: Verify the disabled startup path without network installation**

Run: `docker run --rm -e CLAWMATE_INSTALL_AGENT_CLIS=0 clawmate-agent-cli-test sh -c 'command -v node && command -v npm && python --version'`

Expected: prints paths for Node/npm and the Python version, then exits 0 without attempting npm package installation.

- [ ] **Step 3: Run the repository verification**

Run: `dev/.venv/bin/python -m pytest -q`

Expected: the full Python suite passes.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check && git status --short`

Expected: only the intended Docker, entrypoint, compose, README, and test changes are present in the task diff; pre-existing user changes remain untouched.
