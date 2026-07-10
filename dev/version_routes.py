"""
Version Routes — 文件版本历史与差异对比（基于 git）。

提供三个 API 端点，利用 git 命令查询文件的历史版本和差异。
非 git 仓库或 git 未安装时优雅降级，不报错。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from service import safe_path


logger = logging.getLogger("clawmate.version")
router = APIRouter()


def _find_git_root(file_path: Path) -> Path | None:
    """Walk up from file_path to find the git repository root.

    Returns the git work tree root (``git rev-parse --show-toplevel``)
    or None if the file is not inside a git repository.
    """
    target = file_path.resolve()
    if target.is_dir():
        search_dir = target
    else:
        search_dir = target.parent

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(search_dir),
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    git_root = result.stdout.decode("utf-8", errors="replace").strip()
    if git_root:
        return Path(git_root)
    return None


def _get_file_rel_to_git_root(file_path: Path, git_root: Path) -> str | None:
    """Get file path relative to git root."""
    try:
        resolved_file = file_path.resolve()
        resolved_root = git_root.resolve()
        return str(resolved_file.relative_to(resolved_root))
    except ValueError:
        return None


def _git_log(file_path: Path, max_count: int = 30) -> list[dict] | None:
    """Run git log --follow and return parsed commits.

    Returns None if the file is not in git, otherwise a list of commit dicts.
    """
    git_root = _find_git_root(file_path)
    if git_root is None:
        return None

    rel_path = _get_file_rel_to_git_root(file_path, git_root)
    if rel_path is None:
        return None

    try:
        result = subprocess.run(
            ["git", "log", "--follow",
             f"--max-count={max_count}",
             "--format=%H|%an|%aI|%s",
             "--", rel_path],
            cwd=str(git_root),
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    commits = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            hash_val, author, date_val, msg = parts
            commits.append({
                "hash": hash_val,
                "short_hash": hash_val[:7],
                "author": author,
                "date": date_val,
                "message": msg,
            })
    return commits


def _git_diff(file_path: Path, from_hash: str, to_hash: str | None = None) -> str | None:
    """Run git diff between two commits (or one commit vs working tree).

    Note: ``git diff A..B`` shows changes from A to B.
    When from_hash is the parent and to_hash is the child commit,
    additions display in green and deletions in red (natural direction).

    Returns the unified diff text, or None on failure.
    """
    git_root = _find_git_root(file_path)
    if git_root is None:
        return None

    rel_path = _get_file_rel_to_git_root(file_path, git_root)
    if rel_path is None:
        return None

    try:
        if to_hash:
            spec = f"{from_hash}..{to_hash}"
        else:
            spec = from_hash

        result = subprocess.run(
            ["git", "diff", "--unified=5", spec, "--", rel_path],
            cwd=str(git_root),
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except Exception:
        return None

    if result.returncode != 0:
        return None

    diff_text = result.stdout.decode("utf-8", errors="replace")
    # Check if diff says "binary files differ"
    if not diff_text.strip():
        # Maybe binary — check git diff --numstat
        try:
            ns = subprocess.run(
                ["git", "diff", "--numstat", spec, "--", rel_path],
                cwd=str(git_root), capture_output=True, timeout=5,
            )
            if b"-\t-\t" in ns.stdout:
                return None  # binary — caller will check
        except Exception:
            pass

    return diff_text


# ── Commit endpoint ───────────────────────────────────────────────


@router.post("/api/clawmate/version/commit")
async def clawmate_version_commit(request: Request):
    """Git add + commit a file after save.

    Request body: {root, path, message?}
    Returns: ``{ok: true, hash, short_hash}`` or ``{ok: false, detail: ...}``
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    rel_path = str(body.get("path", "")).strip()
    commit_msg = body.get("message", "")

    if not root_id or not rel_path:
        raise HTTPException(status_code=422, detail="Missing root/path")

    try:
        _, target, _ = safe_path(root_id, rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    git_root = _find_git_root(target)
    if git_root is None:
        return JSONResponse(content={"ok": False, "detail": "文件不在 Git 仓库中"})

    rel_to_git = _get_file_rel_to_git_root(target, git_root)
    if rel_to_git is None:
        return JSONResponse(content={"ok": False, "detail": "无法计算文件相对路径"})

    # Generate commit message if none provided
    if not commit_msg:
        commit_msg = f"Update {target.name}"

    try:
        # git add
        add_result = subprocess.run(
            ["git", "add", "--", rel_to_git],
            cwd=str(git_root), capture_output=True, timeout=10,
        )
        if add_result.returncode != 0:
            return JSONResponse(content={
                "ok": False,
                "detail": f"Git add 失败: {add_result.stderr.decode('utf-8', errors='replace').strip()}",
            })

        # git commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(git_root), capture_output=True, timeout=10,
        )

        if commit_result.returncode != 0:
            stderr_text = commit_result.stderr.decode("utf-8", errors="replace").strip()
            # "nothing to commit" is not an error in this context
            if "nothing to commit" in stderr_text:
                # Nothing changed — get the current HEAD anyway
                head_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(git_root), capture_output=True, timeout=5,
                )
                head_hash = head_result.stdout.decode("utf-8", errors="replace").strip() if head_result.returncode == 0 else ""
                return JSONResponse(content={
                    "ok": True,
                    "hash": head_hash,
                    "short_hash": head_hash[:7] if head_hash else "",
                    "note": "no_changes",
                })

            return JSONResponse(content={
                "ok": False,
                "detail": f"Git commit 失败: {stderr_text}",
            })

        # Parse the commit hash from output: "[<branch> <hash>] message"
        stdout_text = commit_result.stdout.decode("utf-8", errors="replace").strip()
        short_hash = ""
        import re
        m = re.search(r'\[[^\]]+ ([a-f0-9]+)\]', stdout_text)
        if m:
            short_hash = m.group(1)

        # Get full hash
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(git_root), capture_output=True, timeout=5,
        )
        full_hash = head_result.stdout.decode("utf-8", errors="replace").strip() if head_result.returncode == 0 else ""

        return JSONResponse(content={
            "ok": True,
            "hash": full_hash or short_hash,
            "short_hash": short_hash or (full_hash[:7] if full_hash else ""),
        })

    except subprocess.TimeoutExpired:
        return JSONResponse(content={"ok": False, "detail": "Git 操作超时"})
    except Exception as e:
        return JSONResponse(content={"ok": False, "detail": f"Commit 异常: {str(e)}"})


# ── API Endpoints ──────────────────────────────────────────────────


@router.get("/api/clawmate/version/info")
async def clawmate_version_info(
    root: str = Query(""),
    path: str = Query(""),
):
    """查询文件的 git 版本信息：是否在仓库中、最新 commit、dirty 状态。

    Args:
        root: root ID
        path: 相对于 root 的文件路径

    Returns:
        in_git: false 时表示不在 git 仓库中
        in_git: true 时附带 hash/author/date/message/is_dirty
    """
    if not root or not path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    git_root = _find_git_root(target)
    if git_root is None:
        return JSONResponse(content={"in_git": False})

    rel_path = _get_file_rel_to_git_root(target, git_root)
    if rel_path is None:
        return JSONResponse(content={"in_git": False})

    # Check if file is tracked by git
    try:
        ls_result = subprocess.run(
            ["git", "ls-files", "--", rel_path],
            cwd=str(git_root), capture_output=True, timeout=5,
        )
        is_tracked = bool(ls_result.stdout.strip())
    except Exception:
        is_tracked = False

    if not is_tracked:
        # File exists in a git repo but is not tracked (new/untracked file)
        return JSONResponse(content={
            "in_git": True,
            "tracked": False,
            "message": "文件尚未提交",
        })

    # Latest commit for tracked file
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%an|%aI|%s", "--", rel_path],
            cwd=str(git_root), capture_output=True, timeout=5,
        )
    except Exception:
        return JSONResponse(content={"in_git": False})

    if result.returncode != 0 or not result.stdout.strip():
        return JSONResponse(content={"in_git": False})

    parts = result.stdout.decode("utf-8", errors="replace").strip().split("|", 3)

    # Check dirty status (for tracked files: staged or unstaged modifications)
    is_dirty = False
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--", rel_path],
            cwd=str(git_root), capture_output=True, timeout=5,
        )
        is_dirty = bool(status_result.stdout.strip())
    except Exception:
        pass

    if len(parts) == 4:
        hash_val, author, date_val, msg = parts
        return JSONResponse(content={
            "in_git": True,
            "tracked": True,
            "hash": hash_val,
            "short_hash": hash_val[:7],
            "author": author,
            "date": date_val,
            "message": msg,
            "is_dirty": is_dirty,
        })

    return JSONResponse(content={"in_git": False})


@router.get("/api/clawmate/version/log")
async def clawmate_version_log(
    root: str = Query(""),
    path: str = Query(""),
    max_count: int = Query(30, ge=1, le=200),
):
    """获取文件的 git commit 历史列表。

    Args:
        root: root ID
        path: 相对于 root 的文件路径
        max_count: 最大返回 commit 数（默认 30，上限 200）

    Returns:
        in_git: false 时表示不在 git 仓库中
        in_git: true 时附带 commits 列表
    """
    if not root or not path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    commits = _git_log(target, max_count=max_count)
    if commits is None:
        return JSONResponse(content={"in_git": False})

    return JSONResponse(content={
        "in_git": True,
        "commits": commits,
    })


@router.get("/api/clawmate/version/diff")
async def clawmate_version_diff(
    root: str = Query(""),
    path: str = Query(""),
    from_hash: str = Query("", alias="from"),
    to_hash: str | None = Query(None, alias="to"),
):
    """获取两个版本间的文件差异（unified diff）。

    Args:
        root: root ID
        path: 相对于 root 的文件路径
        from_hash: 起始 commit hash
        to_hash: 目标 commit hash（省略时对比工作区）

    Returns:
        in_git: false 时表示不在 git 仓库中
        binary: true 时表示二进制文件无法显示 diff
        diff: unified diff 文本
    """
    if not root or not path or not from_hash:
        raise HTTPException(status_code=422, detail="Missing required parameters")

    try:
        _, target, _ = safe_path(root, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    diff_text = _git_diff(target, from_hash, to_hash)
    if diff_text is None:
        # Check if file exists in git at all
        git_root = _find_git_root(target)
        if git_root is None:
            return JSONResponse(content={"in_git": False})
        # Binary or error
        return JSONResponse(content={
            "in_git": True,
            "binary": True,
            "message": "二进制文件或无法显示差异",
        })

    return JSONResponse(content={
        "in_git": True,
        "from": from_hash,
        "to": to_hash or "(working tree)",
        "diff": diff_text,
    })
