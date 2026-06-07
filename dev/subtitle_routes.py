"""
Subtitle Routes — 字幕提取 + 纠错 API。

从 routes.py 迁出，转为调用 task_runner 处理纠错任务。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import load as load_config
from service import safe_path


logger = logging.getLogger("clawmate.subtitle")
router = APIRouter()

@router.post("/api/clawmate/subtitle/extract")
async def clawmate_subtitle_extract(request: Request):
    """
    从音频/视频文件提取语音并生成 SRT 字幕。
    返回 SSE 事件流，逐段推送进度。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    file_rel_path = str(body.get("path", "")).strip()
    model_size = str(body.get("model", "small")).strip()
    language = body.get("language")  # None = auto

    if not root_id or not file_rel_path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    if model_size not in ("tiny", "small", "medium"):
        model_size = "small"

    # 安全路径解析
    try:
        _, target, _ = safe_path(root_id, file_rel_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    # 只处理音视频格式
    audio_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"}
    video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v"}
    allowed = audio_exts | video_exts
    if target.suffix.lower() not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {target.suffix}. Supported: {', '.join(sorted(allowed))}",
        )

    # SRT 输出到同目录同名 .srt
    srt_path = target.with_suffix(".srt")

    # SSE 事件流
    async def event_generator():
        import asyncio
        queue: asyncio.Queue = asyncio.Queue()

        async def progress(phase: str, pct: int, detail: str = ""):
            payload = json.dumps({"phase": phase, "progress": pct, "detail": detail}, ensure_ascii=False)
            await queue.put(f"data: {payload}\n\n")

        try:
            from subtitle import extract_subtitle
            result = await extract_subtitle(
                target, srt_path,
                model_size=model_size,
                language=language,
                progress_callback=progress,
            )
            await queue.put(f"data: {json.dumps({'phase': 'done', **result}, ensure_ascii=False)}\n\n")
        except Exception as e:
            await queue.put(f"data: {json.dumps({'phase': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n")

        await queue.put(None)  # sentinel: extraction complete
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/api/clawmate/subtitle/status")
async def clawmate_subtitle_status(root: str = "", path: str = ""):
    """查询指定媒体文件是否已有同目录同名 .srt 字幕。"""
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

    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    srt_path = target.with_suffix(".srt")
    exists = srt_path.exists()
    return JSONResponse(content={
        "has_subtitle": exists,
        "srt_path": str(srt_path) if exists else None,
        "srt_size": srt_path.stat().st_size if exists else None,
    })


@router.post("/api/clawmate/subtitle/correct")
async def clawmate_subtitle_correct(request: Request):
    """通过 task_runner 纠错 SRT 字幕。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    root_id = str(body.get("root", "")).strip()
    media_path = str(body.get("media_path", "")).strip()
    srt_path = str(body.get("srt_path", "")).strip()
    if not root_id or not srt_path or not media_path:
        raise HTTPException(status_code=422, detail="Missing root/media_path/srt_path")

    try:
        root_path, target, safe_rel = safe_path(root_id, srt_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Root not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists():
        raise HTTPException(status_code=404, detail="SRT file not found")
    srt_content = target.read_text(encoding="utf-8").strip()
    if not srt_content:
        raise HTTPException(status_code=400, detail="SRT file is empty")

    project = media_path.split("/")[0] if "/" in media_path else ""
    import httpx
    cfg = load_config()
    base_url = cfg.public_base_url or "http://localhost:5533"
    try:
        r = httpx.post(
            f"{base_url}/api/clawmate/task/run",
            json={
                "root": root_id,
                "project": project,
                "task_id": "subtitle_correct",
                "file": media_path,
                "content": srt_content,
                "srt_path": safe_rel,
            },
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return JSONResponse(content={"ok": True, "id": data["id"], "message": "纠错任务已创建"})
        detail = r.json().get("detail", "创建失败")
        raise HTTPException(status_code=r.status_code, detail=detail)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Task runner unavailable: {e}")
