"""Project management routes — convert a directory into a ClawMate project.

Backs ``POST /api/clawmate/project/convert``.  Turning a plain directory into
a project mirrors ``clawmate init``'s Phase I conventions: it creates the
``.clawmate/`` marker plus the core project docs, sets up a per-project
``README.md``-style entry (``PROJECT_NOTE.md`` lives here as the single
human+agent source of truth for what the project is and its decisions), and
initialises Git with the project's author identity.

Idempotent: if the directory already has a ``.clawmate/`` marker it is
already a project and is left untouched.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from service import safe_path, find_project_marker
from config import load as load_cfg

router = APIRouter()
logger = logging.getLogger("clawmate.project")

# Default Git author used when a directory is converted into a project.
# Preferred values come from config.json (project.git_user_email / .git_user_name).
_DEFAULT_EMAIL = "updatedb@qq.com"
_DEFAULT_NAME = "OpenClaw"


def _git_identity() -> tuple[str, str]:
    """Resolve the project Git author from config, falling back to defaults."""
    try:
        cfg = load_cfg()
        return cfg.project.git_user_email, cfg.project.git_user_name
    except Exception:
        logger.warning("[project] config unavailable; using default git identity")
        return _DEFAULT_EMAIL, _DEFAULT_NAME


_PROJECT_NOTE_TEMPLATE = """# {name} 产品笔记

## 当前焦点（≤ 20 行，每次会话首先阅读）
- **当前阶段**: Phase I
- **本周目标**: {name} 项目初始化完成
- **阻塞项**: 无
- **关键决策**: 见下表

## 项目简介
{name} 项目简介（待补充项目是什么、要解决什么问题）。

## 项目方向（只写一次，变更时更新）
- **要解决的核心问题**: （待补充）
- **目标用户/受众**: （待补充）
- **预期成果**: （待补充）
- **项目类型**: 观点收集 / 产品方案 / 研发需求

## 关键决策（所有决策必须记录）
| 日期 | 决策 | 理由 | 影响 |
|------|------|------|------|
| {date} | 项目初始化 | 将 {name} 标记为 ClawMate 项目 | 建立 .clawmate 边界 |

## 开发规范（研发需求项目）
- 代码风格：{{规范}}
- 测试要求：{{覆盖率}}
- 文档要求：必须更新哪些文档
"""


_CLAWLIST_TEMPLATE = """# CLAWLIST — {name}（项目级 — 总览）

> 本项目级 CLAWLIST 管理所有非研发、测试的项目进展，并汇总各分组的简要状态。
> 明细任务分别在 dev/、test/、research/ 的 CLAWLIST 中管理。

## Phase I 项目初始化
- [x] 确认项目类型
- [x] 创建目录结构
- [x] 初始化 Git

## Phase II 需求澄清
- [ ] 目的确认
- [ ] 服务对象（三类）
- [ ] 输出物清单
- [ ] 评价标准
- [ ] 工作范围

## Phase III 信息收集
- [ ] 识别信息需求
- [ ] 生成研究计划
- [ ] 执行研究
- [ ] 用户确认

## Phase IV MRD 编写（产品方案/研发需求）
- [ ] 市场概述
- [ ] 目标市场
- [ ] 竞品分析
- [ ] 用户需求
- [ ] 商业价值
- [ ] 风险与假设
- [ ] 用户评审通过

## Phase V PRD 编写（产品方案/研发需求）
- [ ] 总 PRD
- [ ] 子场景 PRD
- [ ] 用户评审通过
"""


_AGENTS_TEMPLATE = """# AGENTS.md — {name} 项目操作规范

本文件定义各 agent 在 {name} 项目中工作时遵循的规范、流程与上下文。

## 角色定位
- 本文件描述{name}项目的工作约定，帮助 openclaw / codex / claude 在项目内正确工作。

## 目录约定
- `.clawmate/`：项目标识与运行态（feedback.json / sessions / cache）。
- `dev/`：源码目录（如研发需求项目）。
- `test/`：测试目录，与源码严格分离。
- `archive/`：统一归档（严禁在子目录内建 archive/）。
- `research/ collect/ prd/`：按项目类型建立的资料/方案目录。

## 规范
- 文档决策记录在 `PROJECT_NOTE.md`（产品决策唯一来源）。
- 任务清单记录在 `CLAWLIST.md`。
- 每次保存文件到磁盘后，生成 ClawMate 可点击预览链接。
"""


_GITIGNORE_TEMPLATE = """node_modules/ .npm/ .pnpm-store/ __pycache__/ *.py[cod]
.venv/ venv/ .env* *.log logs/
.DS_Store Thumbs.db .vscode/ .idea/ dist/ build/
"""


def _project_name(target: Path) -> str:
    return target.name or target.parent.name


def _git_author_env() -> dict:
    """Return a clean env for convert-time git commands.

    The agent harness exports GIT_CONFIG_COUNT / GIT_CONFIG_* and
    GIT_AUTHOR_* / GIT_COMMITTER_* that pin the commit author to a GitHub
    noreply identity.  A project's own git history should instead use the
    project author (see _GIT_EMAIL / _GIT_NAME), so strip those overrides and
    set the author/committer explicitly.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_CONFIG_") or key in (
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        ):
            env.pop(key, None)
    email, name = _git_identity()
    env["GIT_AUTHOR_NAME"] = name
    env["GIT_AUTHOR_EMAIL"] = email
    env["GIT_COMMITTER_NAME"] = name
    env["GIT_COMMITTER_EMAIL"] = email
    return env


def _run_git(target: Path, args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(target),
            env=_git_author_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        logger.warning("[project.git] git %s failed in %s: %s", args, target, exc)
        return None


def _ensure_git_repo(target: Path) -> None:
    """git init (idempotent) + set author identity + initial commit."""
    email, name = _git_identity()
    if not (target / ".git").exists():
        _run_git(target, ["init"])
    # Always (re-)assert the project author identity (from config).
    _run_git(target, ["config", "user.email", email])
    _run_git(target, ["config", "user.name", name])
    # Commit only if there is something new and no prior commit.
    if not _run_git(target, ["rev-parse", "--is-inside-work-tree"]):
        return
    if (target / ".git").exists():
        try:
            st = subprocess.run(["git", "status", "--porcelain"], cwd=str(target),
                                capture_output=True, text=True, timeout=30)
            pending = bool(st.stdout.strip())
        except Exception:
            pending = True
        if pending:
            _run_git(target, ["add", "-A"])
            _run_git(target, ["commit", "-m", f"Initial commit: {target.name}"])


@router.post("/api/clawmate/project/convert")
async def project_convert(request: Request):
    """Convert a plain directory under a root into a ClawMate project.

    Body: { "root": <root_id>, "path": <rel dir>, "type": <optional> }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root = str(body.get("root", "")).strip()
    path = str(body.get("path", "")).strip()
    ptype = str(body.get("type", "")).strip()

    if not root:
        raise HTTPException(status_code=422, detail="Missing root")
    if not path:
        raise HTTPException(status_code=422, detail="Missing path")

    try:
        root_path, target, safe_rel = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid path")

    if not target.is_dir():
        raise HTTPException(status_code=422, detail="Not a directory")

    if (target / ".clawmate").is_dir():
        raise HTTPException(status_code=409, detail="Directory is already a project")

    name = _project_name(target)
    date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # ── Core project docs first (idempotent — never overwrite) ──────
    # Write docs BEFORE the .clawmate marker so a partial failure never leaves
    # a half-initialised directory that is then mistakenly reported as a project.
    if not (target / "PROJECT_NOTE.md").exists():
        (target / "PROJECT_NOTE.md").write_text(
            _PROJECT_NOTE_TEMPLATE.format(name=name, date=date), encoding="utf-8")
    if not (target / "CLAWLIST.md").exists():
        (target / "CLAWLIST.md").write_text(
            _CLAWLIST_TEMPLATE.format(name=name), encoding="utf-8")
    if not (target / "AGENTS.md").exists():
        (target / "AGENTS.md").write_text(
            _AGENTS_TEMPLATE.format(name=name), encoding="utf-8")
    if not (target / ".gitignore").exists():
        (target / ".gitignore").write_text(_GITIGNORE_TEMPLATE, encoding="utf-8")

    # ── Scaffold .clawmate/ marker (defines the project boundary) ────
    clawmate_dir = target / ".clawmate"
    clawmate_dir.mkdir(parents=True, exist_ok=True)
    if not (clawmate_dir / "feedback.json").exists():
        (clawmate_dir / "feedback.json").write_text(
            json.dumps({"items": [], "audit": [], "tasks": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Git init + author + initial commit ──────────────────────────
    _ensure_git_repo(target)

    project = find_project_marker(root_path, safe_rel) or name
    logger.info("[project.convert] root=%s path=%s project=%s", root, safe_rel, project)

    return JSONResponse(content={
        "ok": True,
        "root": root,
        "path": safe_rel,
        "project": project,
        "name": name,
        "created": {
            "clawmate": True,
            "PROJECT_NOTE.md": (target / "PROJECT_NOTE.md").exists(),
            "CLAWLIST.md": (target / "CLAWLIST.md").exists(),
            "AGENTS.md": (target / "AGENTS.md").exists(),
            ".gitignore": (target / ".gitignore").exists(),
        },
    })
