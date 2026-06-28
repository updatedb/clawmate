"""
搜索服务层 — 文件名搜索、内容搜索、文本提取、AI 摘要。

所有搜索逻辑独立于此模块，不依赖 routes 层。
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Dict, List

from service import safe_path, file_info

logger = logging.getLogger("clawmate.search_service")

# ── AI Summary cache (in-memory, TTL-based) ─────────────────────────────
import hashlib
import time as _time
import threading as _threading

_ai_summary_cache: dict[str, dict] = {}
_ai_summary_lock = _threading.Lock()
_AI_SUMMARY_CACHE_TTL = 600  # 10 minutes
_AI_SUMMARY_CACHE_MAX = 128


def search_media(query: str, root_id: str, rel_dir: str = "", recursive: bool = True,
                 limit: int = 200, max_depth: int = 8, timeout: float = 10.0) -> Dict:
    """搜索文件/目录名，支持递归深度限制和硬超时。

    Args:
        max_depth: 递归最大深度（从 start_dir 算起），默认 8 层
        timeout: 搜索超时秒数，默认 10s；超时后返回已有结果并标记 truncated=True
    """
    import time as _time
    _deadline = _time.time() + timeout

    root_path, target, _ = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    query_lower = query.lower().strip()
    results: List[Dict] = []
    truncated = False
    if not query_lower:
        return {"query": query, "results": results, "truncated": False}

    if recursive:
        queue: deque = deque([(target, 0)])  # (dir_path, depth)
        while queue:
            if _time.time() > _deadline:
                truncated = True
                break
            dir_path, depth = queue.popleft()
            if depth > max_depth:
                continue
            try:
                entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if query_lower in entry.name.lower():
                    results.append(file_info(entry, str(entry.relative_to(root_path))))
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
            if depth < max_depth:
                for entry in entries:
                    if entry.is_dir():
                        queue.append((entry, depth + 1))
    else:
        for entry in target.iterdir():
            if _time.time() > _deadline:
                truncated = True
                break
            if query_lower in entry.name.lower():
                results.append(file_info(entry, str(entry.relative_to(root_path))))
                if len(results) >= limit:
                    break

    return {"query": query, "results": results, "truncated": truncated}


# ── Content search ──────────────────────────────────────────────────────────────

# File extensions that can be content-searched as plain text directly
_CONTENT_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".mdx", ".json", ".csv", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".yaml", ".yml",
    ".ini", ".toml", ".xml", ".gpx", ".kml", ".conf", ".env", ".sh", ".bat",
    ".ps1", ".sql", ".r", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".vue",
    ".srt", ".rst", ".tex", ".Makefile", ".dockerfile", ".cfg",
}

# File extensions that need text extraction before search
_CONTENT_EXTRACT_EXTS = {
    ".pdf": "pymupdf",
    ".docx": "python-docx",
    ".xlsx": "openpyxl",
    ".pptx": "python-pptx",
}


_RG_PATH = None

def _check_extractors() -> Dict[str, bool]:
    """Check which document extractors are available.

    Returns a dict mapping extension -> available (bool).
    Python's own import cache makes repeated checks essentially free,
    so no manual cache is needed.
    """
    checks = {
        ".pdf": "fitz",
        ".docx": "docx",
        ".xlsx": "openpyxl",
        ".pptx": "pptx",
    }
    result: Dict[str, bool] = {}
    for ext, mod in checks.items():
        try:
            __import__(mod)
            result[ext] = True
        except ImportError:
            result[ext] = False

    return result


def _rg_available() -> bool:
    """Check if ripgrep is installed."""
    import shutil
    global _RG_PATH
    if _RG_PATH:
        return True
    _RG_PATH = shutil.which("rg")
    if _RG_PATH:
        return True
    # Check common bundled locations (Codex, etc.)
    for candidate in [
        Path.home() / ".npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex-path/rg",
        Path.home() / ".npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-x64/vendor/aarch64-apple-darwin/codex-path/rg",
    ]:
        if candidate.is_file():
            _RG_PATH = str(candidate)
            return True
    return False


def _path_hash(file_path: Path) -> str:
    """Short hash of a file path for cache key."""
    import hashlib
    return hashlib.md5(str(file_path).encode()).hexdigest()[:12]


def _is_junk_path(path: Path) -> bool:
    """Check if a path is macOS/editor metadata junk that should be skipped.

    Returns True for:
    - __MACOSX directories and their contents (macOS ZIP resource forks)
    - ._* AppleDouble files (macOS resource fork metadata)
    - Hidden files/directories starting with '.' (except .clawmate/)
    - .DS_Store files
    """
    # Check if any path component is a junk directory or hidden directory
    for part in path.parts:
        if part == "__MACOSX":
            return True
        if part == ".DS_Store":
            return True
        if part.startswith("._"):
            return True
        # Skip hidden directories (except .clawmate which is our own cache)
        if part.startswith(".") and part != ".clawmate":
            return True
    # Also check the filename directly for AppleDouble prefix
    if path.name.startswith("._"):
        return True
    return False


def _extract_by_type(file_path: Path) -> str | None:
    """Extract plain text from a file based on its extension.

    Returns the extracted text, or None if extraction is not supported.
    """
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        try:
            import fitz  # pymupdf
            text_parts = []
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc):
                    page_text = page.get_text()
                    if page_text.strip():
                        text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
            return "\n\n".join(text_parts) if text_parts else None
        except ImportError:
            logger.warning("pymupdf not installed, cannot search PDF files")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract text from PDF {file_path}: {e}")
            return None

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(file_path))
            text_parts = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(text_parts) if text_parts else None
        except ImportError:
            logger.warning("python-docx not installed, cannot search DOCX files")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract text from DOCX {file_path}: {e}")
            return None

    if ext == ".xlsx":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(file_path, read_only=True, data_only=True)
            text_parts = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                sheet_lines = [f"--- Sheet: {sheet_name} ---"]
                for row in ws.iter_rows(values_only=True):
                    row_text = "\t".join(str(c) if c is not None else "" for c in row)
                    if row_text.strip():
                        sheet_lines.append(row_text)
                if len(sheet_lines) > 1:
                    text_parts.append("\n".join(sheet_lines))
            wb.close()
            return "\n\n".join(text_parts) if text_parts else None
        except ImportError:
            logger.warning("openpyxl not installed, cannot search XLSX files")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract text from XLSX {file_path}: {e}")
            return None

    if ext == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(str(file_path))
            text_parts = []
            for slide_num, slide in enumerate(prs.slides):
                slide_lines = [f"--- Slide {slide_num + 1} ---"]
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            if para.text.strip():
                                slide_lines.append(para.text)
                if len(slide_lines) > 1:
                    text_parts.append("\n".join(slide_lines))
            return "\n\n".join(text_parts) if text_parts else None
        except ImportError:
            logger.warning("python-pptx not installed, cannot search PPTX files")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract text from PPTX {file_path}: {e}")
            return None

    return None


def extract_text(file_path: Path, project_dir: Path) -> Path | None:
    """Lazy text extraction with mtime-based caching.

    Checks {project_dir}/.clawmate/cache/text/{hash}_{mtime}.txt.
    If cache exists and mtime matches, returns cache path directly.
    Otherwise extracts text and writes new cache file.

    Args:
        file_path: Absolute path to the source file (PDF/DOCX/etc.)
        project_dir: Absolute path to the project root (contains .clawmate/)

    Returns:
        Path to the cached text file, or None if extraction is not supported.
    """
    try:
        stat = file_path.stat()
    except (OSError, PermissionError):
        return None

    cache_dir = project_dir / ".clawmate" / "cache" / "text"
    phash = _path_hash(file_path)
    cache_key = f"{phash}_{int(stat.st_mtime)}"
    cache_file = cache_dir / f"{cache_key}.txt"

    if cache_file.exists():
        return cache_file

    # Extract text
    text = _extract_by_type(file_path)
    if text is None:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8", errors="replace")

    # Clean up old caches for the same file (different mtime)
    try:
        for old in cache_dir.glob(f"{phash}_*"):
            if old.name != f"{cache_key}.txt":
                old.unlink()
    except OSError:
        pass

    return cache_file


def _find_projects(root_path: Path, target: Path, max_depth: int,
                   exclude_dir: set, timeout_deadline: float) -> List[Path]:
    """BFS walk from target to discover project directories (those containing .clawmate/).

    Returns a list of project root Paths (immediate children of root_path that have .clawmate/).
    Also returns non-project directories that should get filename-only search.
    """
    import time as _time
    projects = []

    # Check if target itself is a project
    if (target / ".clawmate").is_dir():
        projects.append(target)
        return projects  # target is a project, no need to search subdirectories

    queue: deque = deque([(target, 0)])
    seen_dirs = {target}

    while queue:
        if _time.time() > timeout_deadline:
            break
        dir_path, depth = queue.popleft()
        if depth > max_depth:
            continue

        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (OSError, PermissionError):
            continue

        for entry in entries:
            if _time.time() > timeout_deadline:
                break
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") and entry.name in exclude_dir:
                continue
            if entry.name.lower() in exclude_dir:
                continue

            # Check if this is a project
            if (entry / ".clawmate").is_dir():
                projects.append(entry)
                # Don't recurse into project subdirectories — rg handles that
                continue

            if depth < max_depth and entry not in seen_dirs:
                seen_dirs.add(entry)
                queue.append((entry, depth + 1))

    return projects


def search_content(query: str, root_id: str, rel_dir: str = "",
                   context_lines: int = 3, max_depth: int = 8,
                   max_filesize_mb: int = 5, timeout: float = 30.0,
                   exclude_ext: list = None, exclude_dir: list = None) -> Dict:
    """Search file contents using ripgrep within project directories.

    Walk strategy:
    1. BFS from starting directory, discover .clawmate/ markers → project dirs
    2. For each project directory: run rg to search all text files
       (rg handles its own recursive walk internally, respecting .gitignore)
    3. For PDF/Office files in projects: extract text to cache, then rg searches cache
    4. For non-project areas: filename-only matching only

    Args:
        query: Search query string (literal, not regex by default)
        root_id: Root identifier
        rel_dir: Relative directory to start search from
        context_lines: Lines of context around each match
        max_depth: Maximum directory depth for project discovery
        max_filesize_mb: Skip files larger than this
        timeout: Search timeout in seconds
        exclude_ext: File extensions to exclude from content search
        exclude_dir: Directory names to exclude from traversal

    Returns:
        {query, root, dir, total_matches, total_files, searched_files,
         elapsed_ms, results_by_file: [{file, match_count, preview_url, matches, mtime, size}]}
    """
    import time as _time
    import subprocess
    import json as _json
    from urllib.parse import quote

    if not _rg_available():
        raise RuntimeError(
            "ripgrep (rg) is not installed. "
            "Install it with: sudo apt install ripgrep"
        )

    _start = _time.time()
    _deadline = _start + timeout

    root_path, target, safe_dir = safe_path(root_id, rel_dir)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("Directory not found")

    exclude_ext_set = set(e.lower().lstrip(".") for e in (exclude_ext or []))
    exclude_dir_set = set(d.lower() for d in (exclude_dir or []))

    # Step 1: Discover project directories
    projects = _find_projects(root_path, target, max_depth, exclude_dir_set, _deadline)

    if not projects:
        # No projects found — content search has nothing to do
        return {
            "query": query,
            "root": root_id,
            "dir": safe_dir,
            "total_matches": 0,
            "total_files": 0,
            "searched_files": 0,
            "elapsed_ms": int((_time.time() - _start) * 1000),
            "results_by_file": [],
            "projects_found": 0,
        }

    # Step 2: For each project, extract PDF/Office text to cache
    _processed_count = 0
    for proj in projects:
        if _time.time() > _deadline:
            break
        try:
            for entry in proj.rglob("*"):
                if _time.time() > _deadline:
                    break
                if not entry.is_file():
                    continue
                if _is_junk_path(entry):
                    continue
                ext = entry.suffix.lower()
                if ext in _CONTENT_EXTRACT_EXTS:
                    extract_text(entry, proj)
                    _processed_count += 1
        except (OSError, PermissionError):
            continue

    # Step 3: Build rg command — search across all project dirs and their cache dirs
    search_paths = [str(p) for p in projects]

    # Also include cache directories so rg searches extracted text
    for proj in projects:
        cache_dir = proj / ".clawmate" / "cache" / "text"
        if cache_dir.is_dir():
            search_paths.append(str(cache_dir))

    rg_bin = _RG_PATH or "rg"
    cmd = [
        rg_bin, "--json", "--no-heading",
        "-i",
        "-C", str(context_lines),
        "--max-depth", str(max_depth),
        "--max-filesize", f"{max_filesize_mb}M",
        "--no-ignore-vcs",  # Don't skip .gitignored files (user wants full search)
    ]

    # Exclude common binary/media directories
    for d in exclude_dir_set:
        cmd.extend(["-g", f"!{d}/**"])

    # Exclude binary/media extensions
    for e in exclude_ext_set:
        cmd.extend(["-g", f"!*.{e}"])

    # Also exclude .clawmate/ itself from search
    cmd.extend(["-g", "!.clawmate/**"])

    cmd.append(query)
    cmd.extend(search_paths)

    # Step 4: Run rg
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=max(5, timeout - (_time.time() - _start)),
        )
    except subprocess.TimeoutExpired:
        result = None
    except FileNotFoundError:
        raise RuntimeError("ripgrep (rg) not found. Install with: sudo apt install ripgrep")

    # Step 5: Parse rg JSON output with context tracking
    matches_by_file: Dict[str, Dict] = {}
    total_matches = 0
    searched_files = set()
    # Per-file context buffer: context lines before a match
    _context_buffer: Dict[str, list] = {}  # file_path -> [(line_number, text)]
    _last_was_match: Dict[str, bool] = {}  # file_path -> True if last entry was a match

    if result and result.stdout:
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                entry = _json.loads(line)
            except _json.JSONDecodeError:
                continue

            etype = entry.get("type")
            data = entry.get("data", {})
            path_data = data.get("path", {})
            file_path = path_data.get("text", "")

            if etype == "begin":
                searched_files.add(file_path)
                _context_buffer[file_path] = []
                _last_was_match[file_path] = False

            elif etype == "context":
                lines_data = data.get("lines", {})
                line_number = data.get("line_number", 0)
                ctx_text = lines_data.get("text", "").rstrip("\n")
                buf = _context_buffer.setdefault(file_path, [])
                buf.append((line_number, ctx_text))
                _last_was_match[file_path] = False

            elif etype == "match":
                lines_data = data.get("lines", {})
                line_number = data.get("line_number", 0)
                line_text = lines_data.get("text", "").rstrip("\n")

                # Convert absolute path to relative
                try:
                    abs_path = Path(file_path)
                    rel_path = str(abs_path.relative_to(root_path))
                except (ValueError, TypeError):
                    rel_path = file_path

                # Get stored context buffer
                buf = _context_buffer.get(file_path, [])
                is_after_context = _last_was_match.get(file_path, False)

                if is_after_context and buf and file_path in matches_by_file:
                    prev_matches = matches_by_file[file_path]["matches"]
                    if prev_matches:
                        prev_matches[-1]["context_after"] = [
                            t for _, t in buf
                        ]

                # Context before for this match (same lines serve as both after
                # for previous match and before for this match)
                context_before = [t for _, t in buf]
                _context_buffer[file_path] = []  # clear buffer for next match

                if file_path not in matches_by_file:
                    matches_by_file[file_path] = {
                        "file": rel_path,
                        "match_count": 0,
                        "matches": [],
                    }
                matches_by_file[file_path]["match_count"] += 1
                matches_by_file[file_path]["matches"].append({
                    "line": line_number,
                    "text": line_text,
                    "context_before": context_before,
                    "context_after": [],
                })
                total_matches += 1
                _last_was_match[file_path] = True

            elif etype == "end":
                # Flush any remaining context as after-context for last match
                buf = _context_buffer.pop(file_path, [])
                if buf and file_path in matches_by_file:
                    prev_matches = matches_by_file[file_path]["matches"]
                    if prev_matches:
                        prev_matches[-1]["context_after"] = [
                            t for _, t in buf
                        ]
                _last_was_match.pop(file_path, None)

    # Step 6: Post-process — map cache results back to original files
    # Build a reverse mapping: cache_path -> original_file_path
    cache_to_original: Dict[str, tuple] = {}
    for proj in projects:
        cache_dir = proj / ".clawmate" / "cache" / "text"
        if not cache_dir.is_dir():
            continue
        for cache_file in cache_dir.iterdir():
            if cache_file.suffix == ".txt":
                # Parse hash from filename: {hash}_{mtime}.txt
                cache_to_original[str(cache_file)] = (str(proj), cache_file.name)

    # Replace cache file paths with original file references
    resolved_results = {}
    for abs_path, info in matches_by_file.items():
        if abs_path in cache_to_original:
            proj_path, cache_name = cache_to_original[abs_path]
            # Try to find the original file
            phash = cache_name.split("_")[0]
            for proj in projects:
                for entry in proj.rglob("*"):
                    if _is_junk_path(entry):
                        continue
                    if entry.is_file() and _path_hash(entry) == phash:
                        try:
                            rel_path = str(entry.relative_to(root_path))
                            key = rel_path
                            if key in resolved_results:
                                resolved_results[key]["match_count"] += info["match_count"]
                                resolved_results[key]["matches"].extend(info["matches"])
                            else:
                                resolved_results[key] = {
                                    "file": rel_path,
                                    "match_count": info["match_count"],
                                    "matches": info["matches"],
                                }
                        except ValueError:
                            pass
                        break
        else:
            resolved_results[abs_path] = info

    # Step 7: Build final response
    from service import get_public_base_url as _get_base_url

    results_by_file = []
    # Sort by match count descending
    sorted_results = sorted(
        resolved_results.values(),
        key=lambda r: r["match_count"],
        reverse=True,
    )

    for info in sorted_results:
        rel_path = info["file"]
        preview_url = (
            f"/clawmate/preview.html"
            f"?root={quote(root_id, safe='')}"
            f"&file={quote(rel_path, safe='')}"
        )
        # Gather file mtime for display in collapsed source rows
        file_mtime = 0
        try:
            abs_path = root_path / rel_path
            if abs_path.exists():
                file_mtime = int(abs_path.stat().st_mtime)
        except (OSError, ValueError):
            pass
        results_by_file.append({
            "file": rel_path,
            "match_count": info["match_count"],
            "preview_url": preview_url,
            "matches": info["matches"],
            "mtime": file_mtime,
        })

    # Step 8: Check extractor availability for notice
    extractors = _check_extractors()
    unavailable = []
    _ext_label = {".pdf": "PDF", ".docx": "DOCX", ".xlsx": "XLSX", ".pptx": "PPTX"}
    for ext, ok in extractors.items():
        if not ok:
            unavailable.append({"ext": ext, "label": _ext_label.get(ext, ext)})

    # Step 9: Build final response
    return {
        "query": query,
        "root": root_id,
        "dir": safe_dir,
        "total_matches": total_matches,
        "total_files": len(results_by_file),
        "searched_files": len(searched_files),
        "elapsed_ms": int((_time.time() - _start) * 1000),
        "results_by_file": results_by_file,
        "projects_found": len(projects),
        "summary": None,  # filled by caller (search_routes) when summary=true
        "unavailable_types": unavailable,  # file types skipped due to missing deps
    }


# ── AI Summary ──────────────────────────────────────────────────────────────────

def summarize_search(query: str, results_by_file: List[Dict], root_id: str = "") -> Dict:
    """Generate a concise content-focused summary of search results.

    Produces:
      - overview: 50-100字总结 + 3-5条要点
      - insights: 5-8条核心洞察

    Falls back to AI agent summary for richer analysis.
    """
    if not results_by_file:
        return {"overview": "", "insights": ""}

    total_files = len(results_by_file)
    total_matches = sum(r.get("match_count", 0) for r in results_by_file)

    top_n = min(10, len(results_by_file))
    top_files = sorted(results_by_file, key=lambda r: r.get("match_count", 0), reverse=True)[:top_n]

    def _best_snippet(matches: list, max_len: int = 100) -> str:
        best = ""
        for m in (matches or [])[:3]:
            t = m.get("text", "").strip()
            if len(t) > len(best) and len(t) >= 8:
                best = t
        if len(best) > max_len:
            best = best[:max_len] + "..."
        return best

    def _dirname(fpath: str) -> str:
        return str(Path(fpath).parent)

    # ── Detect primary module/directory ──────────────────────────────
    dir_hits: Dict[str, int] = {}
    for r in results_by_file:
        d = _dirname(r["file"])
        dir_hits[d] = dir_hits.get(d, 0) + r.get("match_count", 0)
    top_dirs = sorted(dir_hits.items(), key=lambda x: x[1], reverse=True)[:3]
    primary_dirs = [d for d, _ in top_dirs]

    # ── Build overview ───────────────────────────────────────────────
    primary_dir_str = "、".join(f"`{d}/`" for d in primary_dirs)
    overview_line = (
        f"关键词「**{query}**」共命中 {total_files} 个文件 {total_matches} 处，"
        f"主要分布在 {primary_dir_str} 等模块。"
    )

    # 3-5 bullet points from top files
    bullets = []
    for f in top_files[:5]:
        fname = Path(f["file"]).name
        s = _best_snippet(f.get("matches", []), max_len=80)
        if s:
            bullets.append(f"- `{fname}` 中匹配到相关代码：`{s}`")
        else:
            bullets.append(f"- `{fname}` 包含 {f.get('match_count', 0)} 处匹配")

    overview = overview_line + "\n\n" + "\n".join(bullets)

    # ── Build insights ───────────────────────────────────────────────
    CODE_EXTS = {"py", "js", "ts", "tsx", "jsx", "go", "rs", "java", "c", "cpp",
                 "h", "hpp", "vue", "rb", "php", "swift", "kt", "sh", "bash"}
    DOC_EXTS = {"md", "markdown", "mdx", "txt", "rst", "tex", "log"}
    CONFIG_EXTS = {"json", "yaml", "yml", "toml", "ini", "cfg", "conf", "env"}

    code_files = [f for f in top_files if Path(f["file"]).suffix.lower().lstrip(".") in CODE_EXTS]
    doc_files = [f for f in top_files if Path(f["file"]).suffix.lower().lstrip(".") in DOC_EXTS]
    config_files = [f for f in top_files if Path(f["file"]).suffix.lower().lstrip(".") in CONFIG_EXTS]

    insight_lines = []

    if code_files:
        names = "、".join(f"`{Path(f['file']).name}`" for f in code_files[:3])
        insight_lines.append(f"- 核心代码集中在 {names} 等文件，建议优先阅读这些文件理解整体逻辑")

    if config_files:
        names = "、".join(f"`{Path(f['file']).name}`" for f in config_files[:2])
        insight_lines.append(f"- 配置相关文件 {names} 包含关键参数定义，修改时需注意影响范围")

    if doc_files:
        insight_lines.append(f"- 文档文件共 {len(doc_files)} 个命中，可作为理解上下文的参考")

    if len(primary_dirs) >= 2:
        insight_lines.append(f"- 匹配分布在 {len(dir_hits)} 个目录，涉及 {primary_dirs[0]}/、{primary_dirs[1] if len(primary_dirs) > 1 else ''}/ 等模块")

    top3_total = sum(f.get("match_count", 0) for f in top_files[:3])
    if total_matches > 0 and top3_total / total_matches > 0.5:
        insight_lines.append(f"- 匹配高度集中在前 3 个文件（占比 {top3_total / total_matches * 100:.0f}%），重点审查这些文件即可覆盖大部分相关逻辑")
    else:
        insight_lines.append(f"- 匹配分布较均匀，建议按模块逐目录审查")

    for f in top_files[:1]:
        s = _best_snippet(f.get("matches", []), max_len=120)
        if s:
            insight_lines.append(f"- `{Path(f['file']).name}` 中典型匹配：`{s}`")

    insights = "\n".join(insight_lines[:8])

    return {"overview": overview, "insights": insights}

def _best_snippet_for_prompt(matches: list, max_len: int = 200) -> str:
    """Pick the most informative match line for the AI prompt (longest non-trivial)."""
    best = ""
    for m in (matches or [])[:5]:
        t = m.get("text", "").strip()
        if len(t) > len(best) and len(t) >= 10:
            best = t
    if len(best) > max_len:
        best = best[:max_len] + "..."
    return best


def _build_ai_summary_prompt(
    query: str,
    results_by_file: list,
    max_files: int = 10,
    max_snippets: int = 3,
) -> str:
    """Build a concise prompt for the AI agent to generate search summary."""
    # Select top N files
    top_files = sorted(
        results_by_file,
        key=lambda r: r.get("match_count", 0),
        reverse=True,
    )[:max_files]

    total_files = len(results_by_file)
    total_matches = sum(r.get("match_count", 0) for r in results_by_file)

    # Build file listing for the prompt
    file_list_lines = []
    for i, f in enumerate(top_files):
        fname = f["file"]
        mcount = f.get("match_count", 0)
        matches = f.get("matches", [])
        snippets = []
        for m in matches[:max_snippets]:
            t = m.get("text", "").strip()
            if len(t) > 200:
                t = t[:200] + "..."
            if t:
                snippets.append(f"  L{m.get('line', '?')}: {t}")
        file_list_lines.append(f"{i + 1}. `{fname}` — {mcount} match(es)")
        file_list_lines.extend(snippets)
        file_list_lines.append("")

    file_list = "\n".join(file_list_lines)

    prompt = f"""<task>
Analyze the top {min(len(top_files), max_files)} codebase search results below and produce a structured Chinese summary.
Focus on analyzing and synthesizing the CONTENT of matching lines — do NOT produce statistical tables or match counts.
The summary will be displayed in a modal under two sections: "内容概览" and "核心洞察".
</task>

<context>
Search query: "{query}"
You are shown the top {min(len(top_files), max_files)} files (out of {total_files} total, {total_matches} total matches).
</context>

<files>
{file_list}
</files>

<output_format>
Respond with a single JSON object (no markdown fences, no commentary) containing exactly two keys:

- "overview": 内容概览 — A plain Chinese paragraph of 50-100 characters total, followed by 3-5 bullet points (one per line, "- " prefix).
  The paragraph should summarize what the search reveals about the codebase in one sentence.
  Each bullet point should be a concise finding about WHERE and HOW the keyword is used, focusing on patterns, modules, and context revealed by the matching lines. Be specific — cite concrete examples from the snippets.

- "insights": 核心洞察 — 5-8 bullet points (one per line, "- " prefix) based on deep analysis of the matching content.
  Group related points together. Each point should be a meaningful observation, not a statistic.
  Focus on: architectural patterns, code organization, recurring themes, potential issues, relationships between files, usage patterns, and notable implementation details revealed by the actual code/content.
  Reference specific file names in backticks when relevant.

Example:
{{
  "overview": "搜索「auth」揭示了认证逻辑主要集中在 api/ 和 middleware/ 模块，涉及 JWT 令牌验证、OAuth 流程和会话管理。\\n\\n- JWT 验证逻辑集中在 `auth/jwt.py`，覆盖令牌生成、验证和刷新三个环节\\n- OAuth 回调处理分散在 `api/oauth.py` 和 `middleware/auth.py`，存在逻辑重复\\n- 会话管理通过 Redis 实现，`session.py` 包含完整的 CRUD 操作",
  "insights": "- 认证中间件 `middleware/auth.py` 被 12 个路由文件引用，是系统最核心的安全组件\\n- `auth/jwt.py` 中的令牌过期逻辑使用了硬编码的 3600 秒，建议提取为配置项\\n- OAuth 流程在 `api/oauth.py` 和 `middleware/auth.py` 中重复实现，可抽取公共模块\\n- 测试文件 `test_auth.py` 覆盖了主要认证路径，但缺少令牌刷新失败的边界测试\\n- `config.py` 中 OAuth 密钥通过环境变量注入，符合安全最佳实践\\n- 日志记录在认证失败时仅输出通用错误，缺少用于调试的详细上下文"
}}
</output_format>

<constraints>
- overview: Start with one 50-100 character summary sentence, then 3-5 bullet points. Each bullet: one concrete finding with file/module context.
- insights: 5-8 analytical bullet points. NO statistics, NO match counts, NO tables. Focus on MEANING: architecture, patterns, issues, relationships, quality observations.
- ALL content must be in Chinese.
- Reference specific file names in backticks.
- Output valid JSON only. No markdown code fences, no commentary, no ```json``` wrapper.
</constraints>"""

    return prompt


def _parse_ai_summary_output(output: str) -> dict | None:
    """Parse the AI agent's stdout into {overview, findings} dict."""
    import json as _json

    # Strip markdown code fences if present
    text = output.strip()
    if text.startswith("```"):
        idx = text.find("\n")
        if idx != -1:
            text = text[idx + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Try to find JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        parsed = _json.loads(text)
        overview = str(parsed.get("overview", "")).strip()
        insights = str(parsed.get("insights", "")).strip()
        findings = str(parsed.get("findings", "")).strip()
        if overview or insights:
            return {"overview": overview, "insights": insights}
        if overview or findings:
            return {"overview": overview, "insights": findings}
    except (_json.JSONDecodeError, ValueError):
        pass

    # Fallback: use raw output as overview if it looks like text
    if len(output) > 50 and not output.startswith("{"):
        return {"overview": output[:2000], "insights": ""}

    logger.warning("[ai-summary] could not parse agent output: %s", output[:200])
    return None


# ── AI Summary cache ───────────────────────────────────────────────────

def _summary_cache_key(root_id: str, query: str) -> str:
    """Deterministic cache key from root+query."""
    raw = f"{root_id}\x00{query.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cached_ai_summary(root_id: str, query: str) -> dict | None:
    """Return cached summary dict or None if expired/missing."""
    key = _summary_cache_key(root_id, query)
    with _ai_summary_lock:
        entry = _ai_summary_cache.get(key)
        if entry and (_time.time() - entry["ts"]) < _AI_SUMMARY_CACHE_TTL and entry.get("summary"):
            return entry["summary"]
    return None


def set_cached_ai_summary(root_id: str, query: str, summary: dict) -> None:
    """Store summary in cache, evicting oldest if over limit."""
    key = _summary_cache_key(root_id, query)
    with _ai_summary_lock:
        if len(_ai_summary_cache) >= _AI_SUMMARY_CACHE_MAX:
            oldest = min(_ai_summary_cache, key=lambda k: _ai_summary_cache[k]["ts"])
            del _ai_summary_cache[oldest]
        _ai_summary_cache[key] = {"summary": summary, "ts": _time.time()}


def generate_ai_summary(
    query: str,
    results_by_file: list,
    binary_path: str,
    backend: str = "claude",
    cwd: str = "",
    timeout: int = 45,
    max_files: int = 10,
    max_snippets: int = 3,
    extra_env: dict | None = None,
) -> dict | None:
    """Generate search summary using the AI agent backend.

    Runs synchronously via ``<binary> -p``; intended to be called from a
    background daemon thread so it does not block the HTTP response.

    Only supports ``backend="claude"`` and ``backend="codex"`` (direct
    subprocess).  The ``openclaw`` backend is handled separately via
    webhook in search_routes (same pattern as feedback processing).

    Args:
        query: The original search query
        results_by_file: List of per-file match results from search_content()
        binary_path: Absolute path to the CLI binary
        backend: "claude" or "codex" (default "claude")
        cwd: Working directory for the subprocess (project root)
        timeout: Max seconds to wait for the subprocess
        max_files: Top N files to include in the prompt
        max_snippets: Snippets per file in the prompt
        extra_env: Extra environment variables for the subprocess

    Returns:
        {"overview": str, "findings": str} or None on failure
    """
    import subprocess
    import os as _os

    if not results_by_file:
        return None

    if backend not in ("claude", "codex"):
        logger.warning("[ai-summary] unsupported backend '%s', only claude/codex supported", backend)
        return None

    # Build the AI prompt
    prompt = _build_ai_summary_prompt(
        query=query,
        results_by_file=results_by_file,
        max_files=max_files,
        max_snippets=max_snippets,
    )

    # Prepare environment
    env = _os.environ.copy()
    if backend == "claude":
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    if extra_env:
        env.update(extra_env)

    actual_cwd = cwd or _os.path.expanduser("~")

    # Build args: claude needs --dangerously-skip-permissions, codex does not
    args = [binary_path, "-p"]
    if backend == "claude":
        args.append("--dangerously-skip-permissions")

    try:
        result = subprocess.run(
            args,
            cwd=actual_cwd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output = result.stdout.strip()
        if not output:
            logger.warning("[ai-summary] empty output from agent (backend=%s)", backend)
            return None

        parsed = _parse_ai_summary_output(output)
        return parsed
    except subprocess.TimeoutExpired:
        logger.warning("[ai-summary] agent timed out after %ds (backend=%s)", timeout, backend)
        return None
    except Exception as e:
        logger.warning("[ai-summary] agent failed (backend=%s): %s", backend, e)
        return None
