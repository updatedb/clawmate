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
import hashlib
import logging
import os
import re
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from service import safe_path, find_project_marker
from config import load as load_cfg, ProjectConfig
from project_llm import extract as _llm_extract

router = APIRouter()
logger = logging.getLogger("clawmate.project")

def _git_identity() -> tuple[str, str]:
    """Resolve the project Git author from config, falling back to defaults."""
    try:
        cfg = load_cfg()
        return cfg.project.git_user_email, cfg.project.git_user_name
    except Exception:
        logger.warning("[project] config unavailable; using default git identity")
        default = ProjectConfig()
        return default.git_user_email, default.git_user_name


_CODEK_ANALYZE_PROMPT = (
    "你是项目分析助手。用 sumi/superpower/productmanager 等技能深入分析当前项目（仅限当前目录），"
    "识别最值得交给 Agent 执行的下一步任务。只输出一个 JSON 数组，不要解释文字。每项字段："
    "id(短 kebab)、label(中文短标题)、prompt(给执行 Agent 的完整指令)、kind(plan|maintenance|documentation|meeting|research)、"
    "frequency(0)。只基于项目真实状态与文档，不要编造。"
)


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
- `.clawmate/`：项目标识与运行态（feedback.json、feedback.audit.jsonl / sessions / cache）。
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
            json.dumps({"items": [], "tasks": []}, ensure_ascii=False, indent=2),
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


# ── Project overview + recommendations (需求 4) ────────────────────────

_clawlist_write_lock = threading.Lock()

_PROJECT_TYPE_LABELS = {"meeting": "会议/协作", "product": "产品/研发", "research": "研究/调研", "generic": "通用"}
_LEARNED_DOCS = ("AGENTS.md", "WORKFLOW.md", "README.md", "PROJECT_NOTE.md")
_TASK_WORDS = ("更新", "进展", "会议", "状态", "下一步", "维护", "提交", "检查", "报告", "TODO", "待办")
_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:py|sh)$")
_TASK_ACTIONS = ("更新", "维护", "处理", "检查", "提交", "整理", "跟进", "同步", "发布", "执行", "update", "maintain", "prepare", "review", "report")
_NON_TASK_PREFIXES = ("维护者", "关联文件", "本文档", "说明", "备注", "引用", "链接", "作者", "版本", "日期")
_LLM_KINDS = {
    "meeting": {"update", "analyze", "collect", "followup"},
    "product": {"feature", "bugfix", "issue", "docs", "review"},
    "research": {"collect", "analyze", "review", "docs"},
    "generic": {"maintain", "update", "review", "commit"},
}
_LLM_TEMPLATES = {
    "meeting": "围绕会议信息更新、文档分析、结论收集和会后跟进生成任务。",
    "product": "围绕功能建议、Bug、遗留问题、文档与评审生成任务。",
    "research": "围绕资料收集、分析、结论评审与研究文档生成任务。",
    "generic": "围绕维护、更新、评审和提交生成任务。",
}


def _read_project_json(target: Path) -> dict:
    """Parse .clawmate/project.json (best-effort)."""
    path = target / ".clawmate" / "project.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_project_json(target: Path, data: dict) -> None:
    """Atomically update optional project metadata without dropping old keys."""
    path = target / ".clawmate" / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="project.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _learned_markdown_sources(target: Path, config: dict | None = None) -> list[Path]:
    """Return only documented, project-local sources used by discovery."""
    discovery = (config or {}).get("task_discovery") or (config or {}).get("discovery") or {}
    configured = discovery.get("sources") if isinstance(discovery, dict) else None
    if isinstance(configured, list):
        result = []
        for name in configured:
            if not isinstance(name, str) or not name.endswith(".md") or "/" in name or "\\" in name:
                continue
            path = target / name
            if path.is_file():
                result.append(path)
        return result
    result = [target / name for name in _LEARNED_DOCS if (target / name).is_file()]
    for path in target.glob("*.md"):
        if path not in result and any(word in path.name for word in ("说明", "流程", "规范")):
            result.append(path)
    return result


def _safe_project_scripts(target: Path) -> list[Path]:
    """Scripts are opt-in: only direct children of this project's scripts/ dir."""
    scripts = target / "scripts"
    return [p for p in scripts.iterdir() if p.is_file() and _SCRIPT_NAME.fullmatch(p.name)] if scripts.is_dir() else []


def _discovery_settings(config: dict) -> tuple[set[str], tuple[str, ...]]:
    """Read optional project-local discovery overrides without widening access."""
    discovery = config.get("task_discovery") or config.get("discovery") or {}
    keywords = discovery.get("keywords") if isinstance(discovery, dict) else None
    if not isinstance(keywords, list):
        return set(_TASK_WORDS), _TASK_ACTIONS
    words = {str(word).strip().lower() for word in keywords if str(word).strip()}
    return words, _TASK_ACTIONS + tuple(words)


def _discovery_config(config: dict) -> dict:
    value = config.get("task_discovery") or config.get("discovery") or {}
    return value if isinstance(value, dict) else {}


def _discovery_docs(target: Path, config: dict) -> dict[str, str]:
    """Read only selected project docs and bound prompt size."""
    options = _discovery_config(config)
    included = options.get("include_docs", ["AGENTS", "WORKFLOW"])
    included = {str(name).upper().removesuffix(".MD") for name in included} if isinstance(included, list) else {"AGENTS", "WORKFLOW"}
    docs: dict[str, str] = {}
    for path in _learned_markdown_sources(target, config):
        if path.stem.upper() not in included:
            continue
        try:
            docs[path.name] = path.read_text(encoding="utf-8")[:24000]
        except OSError:
            pass
    return docs


def _project_type(target: Path, config: dict, docs: dict[str, str]) -> str:
    value = str(config.get("type") or "").lower()
    if value in _LLM_KINDS:
        return value
    text = " ".join(docs.values()).lower() + " " + target.name.lower()
    return "meeting" if any(word in text for word in ("meeting", "会议", "3gpp", "maastricht")) else "generic"


def _validate_llm_tasks(raw: object, project_type: str, scripts: list[Path], target: Path) -> list[dict]:
    """Strictly accept model metadata; commands and paths are never trusted."""
    if isinstance(raw, dict):
        raw = raw.get("tasks")
    if not isinstance(raw, list):
        return []
    allowed = _LLM_KINDS.get(project_type, _LLM_KINDS["generic"])
    names = {p.name: p for p in scripts}
    out: list[dict] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            return []
        # A model may request only a script basename. Any command or path field
        # is an injection attempt, so reject the whole response and fall back.
        if "command" in item or "script_path" in item:
            return []
        label, kind = str(item.get("label", "")).strip(), str(item.get("kind", "")).lower()
        if kind not in allowed or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9，、（）()\- ]{2,40}", label):
            return []
        priority = str(item.get("priority", "normal")).lower()
        if priority not in {"low", "normal", "high"}:
            return []
        # Only an exact local script basename may bind execution.
        script = item.get("script")
        candidate = names.get(script) if isinstance(script, str) and _SCRIPT_NAME.fullmatch(script) else None
        rel = candidate.relative_to(target).as_posix() if candidate else None
        command = (("python " if candidate and candidate.suffix == ".py" else "sh ") + rel + " --json") if candidate else None
        out.append({"id": _semantic_task_id(label), "label": label, "kind": kind, "priority": priority,
                    "reason": str(item.get("reason", ""))[:240], "frequency": 0,
                    "estimated_duration_seconds": 900, "source": "discover-llm",
                    "execution": "script" if command else "needs_agent", "command": command, "script_path": rel})
    return out


def _clean_task_text(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[#>\s*\-–—\d.)]+", "", text).strip(" ：:。.;；")
    return re.sub(r"\s+", " ", text).strip()


def _semantic_task_label(text: str) -> str | None:
    """Turn an actionable Markdown node into a short, human-readable Chinese task."""
    text = _clean_task_text(text)
    lower = text.lower()
    if not text or text.startswith(_NON_TASK_PREFIXES) or text.startswith(("http://", "https://")):
        return None
    meeting = any(word in lower for word in ("会议", "meeting", "3gpp", "maastricht"))
    if meeting and any(word in lower for word in ("更新", "进展", "状态", "下一步", "update", "trigger", "workflow")):
        return "更新会议信息" if "进展" not in text else "更新会议进展"
    if "maastricht" in lower:
        return "处理 Maastricht 会后事项" if "post" in lower else "处理 Maastricht 会前准备"
    if any(word in lower for word in ("文档", "readme", "clawlist")) and any(word in lower for word in ("维护", "更新", "maintain")):
        return "维护项目文档"
    if re.match(r"^[A-Za-z]+\d+\s*(增量|任务|事项)", text):
        return f"处理 {re.split(r'[：:；;。]', text, maxsplit=1)[0].strip()[:30]}"
    if any(word in lower for word in _TASK_ACTIONS):
        text = re.split(r"[：:；;。]", text, maxsplit=1)[0].strip()
        return text[:40] if text else None
    return None


def _semantic_task_id(label: str) -> str:
    lower = label.lower()
    if "会议" in label:
        return "meet-update-progress" if "进展" in label else "meet-update-info"
    if "maastricht" in lower:
        return "maastricht-post" if "会后" in label else "maastricht-prep"
    if "文档" in label:
        return "maintain-docs"
    english = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return english[:32] or "project-task"


def _meeting_script(scripts: list[Path]) -> Path | None:
    return next((p for p in scripts if p.name.lower() == "meeting_pipeline.py"), None)


def discover_project_tasks(target: Path) -> dict:
    """Semantically extract executable tasks from local Markdown task structures."""
    cfg = _read_project_json(target)
    scripts, found = _safe_project_scripts(target), []
    options = _discovery_config(cfg)
    engine = str(options.get("engine", "llm")).lower()
    # LLM discovery is optional at runtime.  No adapter, timeout, malformed
    # output, or an empty task list all deliberately use the established rules.
    if engine == "llm":
        docs = _discovery_docs(target, cfg)
        project_type = _project_type(target, cfg, docs)
        templates = options.get("prompts") if isinstance(options.get("prompts"), dict) else {}
        template = str(templates.get(project_type) or _LLM_TEMPLATES[project_type])
        try:
            backend = load_cfg().agent.backend
        except Exception:
            backend = "auto"
        try:
            raw_llm_tasks = _llm_extract(backend, project_type, docs, template, float(options.get("timeout_seconds", 8)))
        except Exception:
            logger.warning("[project] LLM task discovery unavailable; falling back to rules")
            raw_llm_tasks = None
        llm_tasks = _validate_llm_tasks(raw_llm_tasks, project_type, scripts, target)
        if llm_tasks:
            existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
            preserved = [item for item in existing if not isinstance(item, dict) or item.get("source") not in {"discover", "discover-llm"}]
            cfg["recommended_tasks"] = preserved + llm_tasks
            cfg["learned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cfg["markdown_sources"] = list(docs)
            cfg["task_discovery_state"] = _discovery_fingerprint(target, cfg)
            _write_project_json(target, cfg)
            return {"learned_at": cfg["learned_at"], "markdown_sources": cfg["markdown_sources"], "recommended_tasks": cfg["recommended_tasks"]}
    keywords, actions = _discovery_settings(cfg)
    for doc in _learned_markdown_sources(target, cfg):
        try:
            lines = doc.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            todo = bool(re.match(r"^\s*[-*]\s*\[ \]", line))
            heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
            bullet = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$", line)
            plain_sentence = not heading and not bullet and doc.name in {"AGENTS.md", "WORKFLOW.md"}
            raw = (heading.group(1) if heading else bullet.group(1) if bullet else line if plain_sentence else "")
            text = _clean_task_text(re.sub(r"^\[[ xX]\]\s*", "", raw))
            workflow_heading = bool(heading and doc.name in {"AGENTS.md", "WORKFLOW.md"} and any(word in text.lower() for word in ("触发", "workflow", "流程", "trigger")))
            actionable_bullet = bool(bullet and (todo or any(word in text.lower() for word in actions) or any(word in text.lower() for word in keywords)))
            task_sentence = bool(plain_sentence and any(text.lower().startswith(word) for word in actions))
            if not (todo or workflow_heading or actionable_bullet or task_sentence):
                continue
            label = _semantic_task_label(text)
            if not label:
                continue
            candidate = _meeting_script(scripts) if any(word in (label + text).lower() for word in ("会议", "meeting", "3gpp", "maastricht")) else None
            rel = candidate.relative_to(target).as_posix() if candidate else None
            command = (("python " if candidate.suffix == ".py" else "sh ") + rel + " --json") if candidate else None
            found.append({"id": _semantic_task_id(label), "label": label, "origin_file": doc.name, "origin_line": number, "kind": "todo" if todo else ("workflow" if workflow_heading else "action"), "priority": "high" if todo else "normal", "frequency": 0, "estimated_duration_seconds": 900, "source": "discover", "execution": "script" if command else "needs_agent", "command": command, "script_path": rel})
    unique, labels = [], set()
    for task in found:
        if task["label"] not in labels:
            labels.add(task["label"]); unique.append(task)
    existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
    # Discovery is a snapshot of the current project documentation, not an
    # append-only history.  Replacing its own records removes legacy
    # ``learned-*`` noise on the first subsequent discovery while preserving
    # user-authored and other integration-provided recommendations intact.
    preserved = [item for item in existing if not isinstance(item, dict) or item.get("source") not in {"discover", "discover-llm"}]
    cfg["recommended_tasks"] = preserved + unique
    cfg["learned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg["markdown_sources"] = [p.name for p in _learned_markdown_sources(target, cfg)]
    cfg["task_discovery_state"] = _discovery_fingerprint(target, cfg)
    _write_project_json(target, cfg)
    return {"learned_at": cfg["learned_at"], "markdown_sources": cfg["markdown_sources"], "recommended_tasks": cfg["recommended_tasks"]}


def _discovery_fingerprint(target: Path, config: dict) -> dict:
    """A bounded, deterministic content state used to avoid repeated refreshes."""
    rows = []
    for path in _learned_markdown_sources(target, config):
        try:
            content = path.read_bytes()
            rows.append((path.name, len(content), int(path.stat().st_mtime_ns), hashlib.sha256(content).hexdigest()))
        except OSError:
            continue
    return {"docs": rows, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _should_auto_discover(target: Path, config: dict) -> bool:
    """Detect substantial doc changes without polling; small edits wait for TTL."""
    options = _discovery_config(config)
    state = config.get("task_discovery_state") if isinstance(config.get("task_discovery_state"), dict) else {}
    old = {row[0]: row for row in state.get("docs", []) if isinstance(row, (list, tuple)) and len(row) >= 4}
    current = _discovery_fingerprint(target, config)["docs"]
    if not old:
        return bool(current)
    threshold = max(1, int(options.get("change_threshold", 800)))
    changed = sum(abs(row[1] - old.get(row[0], ("", 0, 0, 0))[1]) for row in current)
    changed += sum(1 for row in current if row[0] not in old) * threshold
    # Same-size meaningful rewrites are considered a change once mtime differs.
    changed += sum(threshold for row in current if row[0] in old and row[2] != old[row[0]][2] and row[3] != old[row[0]][3])
    return changed >= threshold


_auto_discovery_lock = threading.Lock()
_auto_discovery_active: set[str] = set()


def _schedule_auto_discover(target: Path) -> None:
    """One background refresh per project when overview observes a large change."""
    cfg = _read_project_json(target)
    if not _should_auto_discover(target, cfg):
        return
    key = str(target.resolve())
    with _auto_discovery_lock:
        if key in _auto_discovery_active:
            return
        _auto_discovery_active.add(key)
    def run() -> None:
        try:
            discover_project_tasks(target)
        except Exception:
            logger.exception("[project] automatic task discovery failed: %s", target)
        finally:
            with _auto_discovery_lock:
                _auto_discovery_active.discard(key)
    threading.Thread(target=run, name="project-task-discovery", daemon=True).start()


def _project_task_catalog(target: Path) -> list[dict]:
    """Return compatible recommended tasks, preferring persisted task records.

    Records whose id is in ``dismissed_recommendations`` are skipped — including
    the built-in defaults, so a dismissed default never resurrects."""
    cfg = _read_project_json(target)
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    raw = cfg.get("recommended_tasks") or cfg.get("recommendations") or []
    known: set[str] = set()
    tasks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            continue
        task = dict(item)
        task["id"] = str(task.get("id") or task["label"])
        task["label"] = str(task["label"]).strip()
        task["frequency"] = int(task.get("frequency") or 0)
        if task.get("estimated_minutes") is not None:
            task["estimated_minutes"] = max(0, int(task["estimated_minutes"]))
        known.add(task["id"])
        if task["id"] in dismissed:
            continue
        tasks.append(task)
    defaults = [
        {"id": "commit_version", "label": "提交版本", "kind": "commit", "prompt": "检查项目当前改动；仅提交与本次项目工作直接相关、且已完成自检的文件。", "frequency": 0},
        {"id": "maintain_project_docs", "label": "维护项目文档", "kind": "documentation", "prompt": "阅读 PROJECT_NOTE.md 和 CLAWLIST.md，依据当前项目实际进展更新必要文档，不要编造事实。", "frequency": 0},
    ]
    if str(cfg.get("type", "")).lower() == "meeting":
        defaults.append({"id": "update_meeting_info", "label": "更新会议信息", "kind": "meeting", "prompt": "更新项目中的会议纪要、日程或行动项；只写入已知会议事实。", "frequency": 0})
    tasks.extend(task for task in defaults if task["id"] not in known and task["id"] not in dismissed)
    return tasks


def _merge_codex_recommendations(target: Path, new_tasks: list[dict]) -> list[dict]:
    """Replace prior codex-sourced records with fresh ones, respecting dismissal."""
    cfg = _read_project_json(target)
    existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    preserved = [t for t in existing if t.get("source") != "codex" and (str(t.get("id") or t.get("label") or "")) not in dismissed]
    kept = {(str(t.get("id") or t.get("label") or "")) for t in preserved}
    seen = set(kept)
    appended: list[dict] = []
    for t in new_tasks:
        tid = str(t.get("id") or t.get("label") or "")
        if tid in dismissed or tid in seen:
            continue
        seen.add(tid)
        appended.append(t)
    merged = preserved + appended
    cfg["recommended_tasks"] = merged
    cfg["dismissed_recommendations"] = sorted(dismissed)
    _write_project_json(target, cfg)
    return merged


def update_project_after_commit(target: Path, commit_subject: str, changed_file: str) -> dict:
    """Persist deterministic status and bounded frequency-ranked task metadata."""
    cfg = _read_project_json(target)
    pending, _ = _count_clawlist_todo(target)
    summary = f"本次已提交《{changed_file}》更新：{commit_subject}；当前仍有 {pending} 项 CLAWLIST 待办，请继续推进并维护项目文档。"[:50]
    if len(summary) < 30:
        summary = (summary + "项目状态已同步，后续请持续跟进待办与文档记录。")[:30]
    existing = {task["id"]: task for task in _project_task_catalog(target)}
    defaults = [
        {"id": "commit_version", "label": "提交版本", "kind": "commit", "prompt": "检查项目当前改动；仅提交与本次项目工作直接相关、且已完成自检的文件。", "frequency": 0},
        {"id": "maintain_project_docs", "label": "维护项目文档", "kind": "documentation", "prompt": "阅读 PROJECT_NOTE.md 和 CLAWLIST.md，依据当前项目实际进展更新必要文档，不要编造事实。", "frequency": 0},
    ]
    if str(cfg.get("type", "")).lower() == "meeting":
        defaults.append({"id": "update_meeting_info", "label": "更新会议信息", "kind": "meeting", "prompt": "更新项目中的会议纪要、日程或行动项；只写入已知会议事实。", "frequency": 0})
    for task in defaults:
        current = existing.get(task["id"], {})
        task.update({key: value for key, value in current.items() if key != "frequency"})
        task["frequency"] = int(current.get("frequency") or 0) + 1
        existing[task["id"]] = task
    tasks = sorted(existing.values(), key=lambda item: (-int(item.get("frequency") or 0), item["label"]))[:5]
    cfg["status_summary"] = summary
    cfg["recommended_tasks"] = tasks
    _write_project_json(target, cfg)
    return {"status_summary": summary, "recommended_tasks": tasks}


def _count_clawlist_todo(target: Path) -> tuple[int, list[str]]:
    """Count unchecked tasks in CLAWLIST.md (lines matching '- [ ]')."""
    path = target / "CLAWLIST.md"
    if not path.exists():
        return 0, []
    items: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*-\s*\[ \]\s*(.*)$", line)
            if m and m.group(1).strip():
                items.append(m.group(1).strip())
    except Exception:
        return 0, []
    return len(items), items



def _clawlist_tasks(target: Path) -> list[dict]:
    """Return checklist entries in file order; CLAWLIST remains the source of truth."""
    path = target / "CLAWLIST.md"
    if not path.exists():
        return []
    tasks: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*-\s*\[([ xX])\]\s*(.*)$", line)
            if match and match.group(2).strip():
                tasks.append({"task": match.group(2).strip(), "completed": match.group(1).lower() == "x"})
    except Exception:
        return []
    return tasks


def _changed_project_file_count(target: Path) -> int:
    """Count dirty files without staging or otherwise modifying the repository."""
    result = _run_git(target, ["status", "--porcelain", "--untracked-files=all"])
    if not result or result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def _parse_project_datetime(value: object) -> datetime | None:
    """Parse an optional project.json timestamp as an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _project_panel_actions(target: Path, review: dict, cfg: dict, *, now: datetime | None = None) -> list[dict]:
    """Create source-labelled actionable rows from local project state."""
    now = now or datetime.now(timezone.utc)
    actions: list[dict] = []
    pending_review = int(review.get("pending_review") or 0)
    if pending_review:
        actions.append({"id": "review_feedback", "label": f"待评审条目（{pending_review}条）", "action": "评审反馈", "kind": "review", "source": ".clawmate/feedback.json"})
    ready_execution = int(review.get("approved") or 0)
    if ready_execution:
        actions.append({"id": "implement_feedback", "label": f"待执行条件（{ready_execution}条）", "action": "实施反馈", "kind": "implementation", "source": ".clawmate/feedback.json（approved）"})
    changed_files = _changed_project_file_count(target)
    if changed_files:
        actions.append({"id": "commit_version", "label": f"{changed_files}个项目文件发生变化", "action": "提交版本", "kind": "commit", "source": "git status --porcelain"})
    panel = cfg.get("project_panel") if isinstance(cfg.get("project_panel"), dict) else {}
    if panel.get("maintenance_required") is True:
        actions.append({"id": "maintain_project_docs", "label": "Agents | Clawlist | Project_note信息已过期", "action": "维护项目", "kind": "maintenance", "source": ".clawmate/project.json → project_panel.maintenance_required"})
    meetings = panel.get("meetings", [])
    if isinstance(meetings, dict):
        meetings = [meetings]
    if not isinstance(meetings, list):
        meetings = []
    upcoming = any(now <= start <= now + timedelta(days=14) for item in meetings if isinstance(item, dict) for start in [_parse_project_datetime(item.get("starts_at"))] if start)
    recently_ended = any(now - timedelta(days=7) <= end <= now for item in meetings if isinstance(item, dict) for end in [_parse_project_datetime(item.get("ends_at"))] if end)
    if upcoming:
        actions.append({"id": "update_meeting_agenda", "label": "新会议在2周内举行", "action": "更新会议议题", "kind": "meeting", "source": ".clawmate/project.json → project_panel.meetings[].starts_at"})
    if recently_ended:
        actions.append({"id": "update_meeting_conclusion", "label": "会议结束1周内", "action": "更新会议结论", "kind": "meeting", "source": ".clawmate/project.json → project_panel.meetings[].ends_at"})
    return actions

def _count_review(target: Path) -> dict:
    """Count review items by status from .clawmate/feedback.json."""
    path = target / ".clawmate" / "feedback.json"
    counts = {"pending_review": 0, "approved": 0, "rejected": 0, "in_progress": 0, "executed": 0}
    if not path.exists():
        return counts
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            st = item.get("status")
            if st in ("pending_review", "pending"):
                counts["pending_review"] += 1
            elif st in ("approved",):
                counts["approved"] += 1
            elif st in ("rejected",):
                counts["rejected"] += 1
            elif st in ("in_progress", "planned", "execution_pending"):
                counts["in_progress"] += 1
            elif st in ("executed", "done"):
                counts["executed"] += 1
    except Exception:
        pass
    return counts


def _recommendations_for(target: Path) -> list[dict]:
    """Recommend project actions from built-in archetypes + project.json.

    Lightweight rules: match on project type and the presence of marker files
    (e.g. meeting dirs / CHANGELOG) to surface the most likely next action.
    Custom rules come from .clawmate/project.json 'recommendations'.
    """
    cfg = _read_project_json(target)
    ptype = str(cfg.get("type") or "generic").lower()
    recs: list[dict] = []

    for r in _project_task_catalog(target):
        recs.append({"source": "project_json", **r})

    names = {p.name.lower() for p in target.iterdir() if p.is_file()}
    dirs = {p.name.lower() for p in target.iterdir() if p.is_dir()}

    def _add(label: str, kind: str, detail: str = "") -> None:
        recs.append({"source": "rule", "label": label, "kind": kind, "detail": detail})

    if ptype == "meeting" or any("meeting" in d for d in dirs) or any("meeting" in n for n in names):
        _add("更新会议信息", "meeting", "刷新进度/纪要/日程")
        _add("生成/更新会议纪要", "meeting", "沉淀本次会议结论")
    if ptype == "product" or any("changelog" in n for n in names) or any("prd" in d for d in dirs):
        _add("更新 CHANGELOG", "release", "记录本次变更")
        _add("评审未关闭项", "review", "推进待评审/已评审项")
    if ptype == "research" or "research" in dirs:
        _add("整理调研结论", "research", "归档到 archive/research")
    _add("完善项目说明", "doc", "更新 PROJECT_NOTE.md")
    _add("规划待办", "plan", "推进 CLAWLIST 未完成项")
    unique: list[dict] = []
    labels: set[str] = set()
    for rec in recs:
        if rec["label"] not in labels:
            labels.add(rec["label"])
            unique.append(rec)
    return unique[:5]


def _extract_codex_tasks(output: str) -> list[dict]:
    """Pull a JSON array of recommended tasks out of a free-form CLI response."""
    text = str(output or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("No JSON array in codex response")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, list):
        raise ValueError("Expected a JSON array from codex")
    tasks: list[dict] = []
    for item in payload:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            continue
        label = str(item["label"]).strip()
        tasks.append({
            "id": str(item.get("id") or label).strip() or label,
            "label": label,
            "prompt": str(item.get("prompt") or f"在项目内完成推荐任务：{label}。"),
            "kind": str(item.get("kind") or "plan"),
            "frequency": int(item.get("frequency") or 0),
            "source": "codex",
        })
    return tasks



def _mark_clawlist_task_done(target: Path, task: str) -> bool:
    """Check exactly one unchecked CLAWLIST item, never fuzzy-match user input."""
    if not task or "\n" in task or "\r" in task or len(task) > 500:
        raise ValueError("Invalid task")
    path = target / "CLAWLIST.md"
    if not path.exists():
        raise FileNotFoundError("CLAWLIST.md not found")
    with _clawlist_write_lock:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines) if re.match(r"^(\s*-\s*)\[ \](\s*" + re.escape(task) + r")\s*$", line.rstrip("\r\n"))]
        if len(matches) != 1:
            raise LookupError("Task must match exactly one unchecked CLAWLIST item")
        lines[matches[0]] = re.sub(r"^(\s*-\s*)\[ \]", r"\1[x]", lines[matches[0]], count=1)
        fd, tmp_name = tempfile.mkstemp(prefix="clawlist.", suffix=".md", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.writelines(lines)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
    return True


def _project_target(root: str, project: str) -> Path:
    _, target, _ = safe_path(root, project)
    if not target.is_dir() or not (target / ".clawmate").is_dir():
        raise FileNotFoundError("Not a ClawMate project")
    return target


@router.post("/api/clawmate/project/{root}/{project}/discover")
async def project_discover(root: str, project: str):
    """Refresh learned recommendations from project-local docs and scripts."""
    try:
        _, target, _ = safe_path(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")
    return JSONResponse(content={"ok": True, **discover_project_tasks(target)})


@router.post("/api/clawmate/project/{root}/{project}/tasks/{task_id}/run")
async def project_task_run(root: str, project: str, task_id: str):
    """Run a stored recommendation through the configured Agent backend only."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    task = next((item for item in _project_task_catalog(target) if item["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Recommended task not found")
    prompt = str(task.get("prompt") or f"在项目内完成推荐任务：{task['label']}。")
    try:
        cfg = load_cfg()
        from task_executor import TaskExecutor, persist_project_receipt
        message = ("ClawMate 项目推荐任务（仅限当前项目目录）：\n" + prompt
                   + "\n遵循项目 AGENTS.md；不要访问项目外路径；完成后如有事实变更，更新相关项目文档。")
        receipt = TaskExecutor(cfg).launch(task_run_id=f"PR-{uuid.uuid4().hex[:12]}", message=message,
            cwd=str(target), root_id=root, name=f"clawmate-project-{task['id']}")
        record = persist_project_receipt(target, receipt, task=task)
        if receipt.status not in {"starting", "running", "waiting_input"}:
            return JSONResponse(status_code=503, content={"ok": False, "task": {"id": task["id"], "label": task["label"]}, "status": receipt.status, "receipt": record})
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[project.task] spawn failed: %s", exc)
        raise HTTPException(status_code=503, detail="Unable to start Agent task")
    return JSONResponse(content={"ok": True, "task": {"id": task["id"], "label": task["label"]}, "status": receipt.status, "receipt": record})


@router.get("/api/clawmate/project/{root}/{project}/runs")
async def project_task_runs(root: str, project: str):
    """Return current-project run lifecycle only; prompts and credentials never leave disk."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    from task_executor import refresh_project_runs
    safe_fields = {"task_run_id", "backend_requested", "backend_actual", "external_run_id", "status", "started_at", "latest_feedback", "failure_reason", "error", "result", "ended_at", "exit_code", "task"}
    runs = [{key: value for key, value in run.items() if key in safe_fields} for run in refresh_project_runs(target)]
    active = [run for run in runs if run.get("status") in {"starting", "running", "waiting_input"}]
    return JSONResponse(content={"ok": True, "active": active, "recent": runs[:10]})


@router.post("/api/clawmate/project/{root}/{project}/runs/{task_run_id}/retry")
async def project_task_retry(root: str, project: str, task_run_id: str):
    """Retry only a failed recommendation by resolving its persisted task id anew."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    from task_executor import refresh_project_runs
    failed = next((run for run in refresh_project_runs(target) if run.get("task_run_id") == task_run_id), None)
    task_id = (failed or {}).get("task", {}).get("id")
    if not failed or failed.get("status") != "failed" or not task_id:
        raise HTTPException(status_code=409, detail="Only failed recommended tasks can be retried")
    return await project_task_run(root, project, str(task_id))


@router.post("/api/clawmate/project/{root}/{project}/recommendations/{task_id}/delete")
async def project_recommendation_delete(root: str, project: str, task_id: str):
    """Persistently dismiss a recommendation; it will not resurrect."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    cfg = _read_project_json(target)
    dismissed = set(cfg.get("dismissed_recommendations") or [])
    dismissed.add(task_id)
    existing = cfg.get("recommended_tasks") if isinstance(cfg.get("recommended_tasks"), list) else []
    cfg["recommended_tasks"] = [t for t in existing if isinstance(t, dict) and (str(t.get("id") or t.get("label") or "")) != task_id]
    cfg["dismissed_recommendations"] = sorted(dismissed)
    _write_project_json(target, cfg)
    return JSONResponse(content={"ok": True, "task_id": task_id})


@router.post("/api/clawmate/project/{root}/{project}/recommendations/analyze")
def project_recommendations_analyze(root: str, project: str):
    """Generate recommendations by analyzing the project with the project-panel backend."""
    try:
        target = _project_target(root, project)
    except (ValueError, PermissionError):
        raise HTTPException(status_code=403, detail="Forbidden")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    from task_executor import TaskExecutor
    cfg = load_cfg()
    result = TaskExecutor(cfg).run_summary_analysis(_CODEK_ANALYZE_PROMPT, cwd=str(target), timeout_seconds=90)
    if not result.get("ok"):
        return JSONResponse(status_code=502, content={"ok": False, "detail": result.get("error") or "codex 分析失败"})
    try:
        new_tasks = _extract_codex_tasks(result.get("output") or "")
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "detail": f"无法解析 codex 输出：{exc}"})
    if not new_tasks:
        return JSONResponse(content={"ok": True, "recommended_tasks": _project_task_catalog(target), "detail": "codex 未返回可执行任务"})
    merged = _merge_codex_recommendations(target, new_tasks)
    return JSONResponse(content={"ok": True, "recommended_tasks": merged})


@router.post("/api/clawmate/project/{root}/{project}/clawlist/complete")
async def project_clawlist_complete(root: str, project: str, request: Request):
    try:
        body = await request.json()
        task = str(body.get("task", "")).strip()
        target = _project_target(root, project)
        _mark_clawlist_task_done(target, task)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project or CLAWLIST not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    return JSONResponse(content={"ok": True, "task": task, "status": "completed"})

@router.get("/api/clawmate/project/{root}/{project}/overview")
async def project_overview(root: str, project: str):
    """Aggregate project overview: CLAWLIST todo + review counts + recommendations."""
    if not root:
        raise HTTPException(status_code=422, detail="Missing root")
    if not project:
        raise HTTPException(status_code=422, detail="Missing project")
    try:
        root_path, target, safe_rel = safe_path(root, project)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid path")

    if not (target / ".clawmate").is_dir():
        raise HTTPException(status_code=404, detail="Not a ClawMate project")

    review = _count_review(target)
    # Deliberately fire-and-forget: overview remains read-only from its caller's
    # perspective and never waits for an LLM or document scan.
    _schedule_auto_discover(target)
    recs = _recommendations_for(target)
    pj = _read_project_json(target)
    project_tasks = _clawlist_tasks(target)
    actions = _project_panel_actions(target, review, pj)
    from task_executor import refresh_project_runs
    runs = refresh_project_runs(target)
    active_runs = [run for run in runs if run.get("status") in {"starting", "running", "waiting_input"}]
    failed_runs = [run for run in runs if run.get("status") == "failed"]

    return JSONResponse(content={
        "ok": True,
        "root": root,
        "project": project,
        "name": target.name,
        "type": pj.get("type", "generic"),
        "type_label": _PROJECT_TYPE_LABELS.get(str(pj.get("type", "generic")).lower(), "通用"),
        "status_summary": pj.get("status_summary", ""),
        "todo": {"total": sum(not item["completed"] for item in project_tasks), "items": [item["task"] for item in project_tasks if not item["completed"]][:30]},
        "project_tasks": project_tasks[:30],
        "review": review,
        "recommendations": recs,
        "actions": actions,
        "runs": {"active": active_runs, "recent": runs[:10]},
        "status": {"refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "running": len(active_runs), "pending": int(review.get("pending_review") or 0) + int(review.get("approved") or 0), "failed": len(failed_runs)},
    })
