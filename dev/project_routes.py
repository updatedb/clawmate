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


def _project_task_catalog(target: Path) -> list[dict]:
    """Return compatible recommended tasks, preferring persisted task records."""
    cfg = _read_project_json(target)
    raw = cfg.get("recommended_tasks") or cfg.get("recommendations") or []
    tasks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            continue
        task = dict(item)
        task["id"] = str(task.get("id") or task["label"])
        task["label"] = str(task["label"]).strip()
        task["frequency"] = int(task.get("frequency") or 0)
        tasks.append(task)
    known = {task["id"] for task in tasks}
    defaults = [
        {"id": "commit_version", "label": "提交版本", "kind": "commit", "prompt": "检查项目当前改动；仅提交与本次项目工作直接相关、且已完成自检的文件。", "frequency": 0},
        {"id": "maintain_project_docs", "label": "维护项目文档", "kind": "documentation", "prompt": "阅读 PROJECT_NOTE.md 和 CLAWLIST.md，依据当前项目实际进展更新必要文档，不要编造事实。", "frequency": 0},
    ]
    if str(cfg.get("type", "")).lower() == "meeting":
        defaults.append({"id": "update_meeting_info", "label": "更新会议信息", "kind": "meeting", "prompt": "更新项目中的会议纪要、日程或行动项；只写入已知会议事实。", "frequency": 0})
    tasks.extend(task for task in defaults if task["id"] not in known)
    return tasks


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
    name = target.name
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
        persist_project_receipt(target, receipt)
        if receipt.status != "started":
            raise HTTPException(status_code=503, detail="Agent backend unavailable")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[project.task] spawn failed: %s", exc)
        raise HTTPException(status_code=503, detail="Unable to start Agent task")
    return JSONResponse(content={"ok": True, "task": {"id": task["id"], "label": task["label"]}, "status": "started", "receipt": receipt.payload()})


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
    recs = _recommendations_for(target)
    pj = _read_project_json(target)
    project_tasks = _clawlist_tasks(target)
    actions = _project_panel_actions(target, review, pj)

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
    })
