"""
Subtitle Routes — 字幕提取 API。

字幕提取功能（faster-whisper 语音识别 → SRT 生成）。
纠错任务已交由 agent 处理（task/run + subtitle_correct 模板）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import load as load_config
from service import safe_path


logger = logging.getLogger("clawmate.subtitle")
router = APIRouter()

# ═══════════════════════════════════════════════════════════════════
#  字幕提取核心模块（原 subtitle.py）
# ═══════════════════════════════════════════════════════════════════

_FFMPEG_CHECKED: Optional[bool] = None
_FFPROBE_CHECKED: Optional[bool] = None
_WHISPER_MODEL: Optional[object] = None


def _check_ffmpeg() -> str:
    """检查 ffmpeg 是否可用，返回消息。空字符串表示可用。"""
    global _FFMPEG_CHECKED
    if _FFMPEG_CHECKED is None:
        import shutil
        _FFMPEG_CHECKED = shutil.which("ffmpeg")
    if _FFMPEG_CHECKED:
        return ""
    return "ffmpeg 未安装，请执行: sudo apt install ffmpeg"


def _check_ffprobe() -> str:
    """检查 ffprobe 是否可用，返回消息。空字符串表示可用。"""
    global _FFPROBE_CHECKED
    if _FFPROBE_CHECKED is None:
        import shutil
        _FFPROBE_CHECKED = shutil.which("ffprobe")
    if _FFPROBE_CHECKED:
        return ""
    return "ffprobe 未安装，请执行: sudo apt install ffmpeg"


def _format_time(seconds: float) -> str:
    """秒数 → SRT 时间戳 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _check_subtitle_enabled():
    """检查字幕提取是否启用。"""
    try:
        from config import load as _cfg
        if _cfg().feedback.enable_subtitle:
            return True
    except Exception:
        pass
    return os.getenv("CLAWMATE_ENABLE_SUBTITLE", "0") == "1"


def _get_whisper_model(size: str = "small"):
    """延迟加载 faster-whisper 模型（全局单例）。"""
    if not _check_subtitle_enabled():
        raise RuntimeError("Subtitle extraction disabled. 配置 feedback.enable_subtitle=true 或设置 CLAWMATE_ENABLE_SUBTITLE=1 启用")
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper 未安装，pip install faster-whisper 后重试")
        _WHISPER_MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def has_audio_stream(input_path: Path) -> bool:
    """用 ffprobe 检查文件是否包含音频流。"""
    msg = _check_ffprobe()
    if msg:
        raise RuntimeError(msg)
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return "audio" in result.stdout


def extract_audio(input_path: Path) -> Path:
    """用 ffmpeg 提取 16kHz mono wav 到临时文件，返回 wav 路径。"""
    msg = _check_ffmpeg()
    if msg:
        raise RuntimeError(msg)
    if not has_audio_stream(input_path):
        raise RuntimeError("文件中没有音频轨道，无法提取字幕")

    output = input_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output


def generate_srt(segments, srt_path: Path):
    """将 faster-whisper segments 写入 SRT 文件。"""
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_time(seg.start)
            end = _format_time(seg.end)
            text = seg.text.strip()
            if not text:
                continue
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


async def _pst_progress(
    phase: str, pct: int, detail: str,
    queue: asyncio.Queue,
):
    """SSE progress 回调。"""
    payload = json.dumps({"phase": phase, "progress": pct, "detail": detail}, ensure_ascii=False)
    await queue.put(f"data: {payload}\n\n")


async def _extract_subtitle_core(
    file_path: Path,
    srt_path: Path,
    model_size: str = "small",
    language: Optional[str] = None,
    queue: asyncio.Queue = None,
) -> dict:
    """核心提取流程。"""
    # Step 1: 音频提取
    if queue:
        await _pst_progress("extracting", 0, "正在提取音频...", queue)

    is_video = file_path.suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv")
    if is_video or file_path.suffix.lower() in (".mp3", ".wma", ".ogg", ".flac", ".aac", ".m4a"):
        audio_path = extract_audio(file_path)
        cleanup_audio = True
    else:
        audio_path = file_path
        cleanup_audio = False

    if queue:
        await _pst_progress("extracting", 100, "音频提取完成", queue)

    if queue:
        await _pst_progress("transcribing", 0, "正在加载模型（首次约需 2-5 分钟）...", queue)

    model = _get_whisper_model(model_size)

    if queue:
        await _pst_progress("transcribing", 5, "模型加载完成，开始识别...", queue)

    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,
    )

    seg_list = []
    total_duration = info.duration or 0.0

    for seg in segments_gen:
        seg_list.append(seg)
        if queue and total_duration > 0:
            pct = min(90, 5 + int(seg.end / total_duration * 85))
            await _pst_progress("transcribing", pct, f"已识别 {int(seg.end)}/{int(total_duration)} 秒", queue)
        elif queue:
            await _pst_progress("transcribing", 50, "识别中...", queue)

    generate_srt(seg_list, srt_path)

    if cleanup_audio and audio_path.exists():
        try:
            audio_path.unlink()
        except OSError:
            pass

    if queue:
        await _pst_progress("done", 100, f"字幕已生成: {srt_path.name}", queue)

    return {
        "srt_path": str(srt_path),
        "language": info.language,
        "duration": total_duration,
        "segments": len(seg_list),
    }


# ═══════════════════════════════════════════════════════════════════
#  路由
# ═══════════════════════════════════════════════════════════════════


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
    language = body.get("language")

    if not root_id or not file_rel_path:
        raise HTTPException(status_code=422, detail="Missing root or path")

    if model_size not in ("tiny", "small", "medium"):
        model_size = "small"

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

    audio_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma"}
    video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v"}
    allowed = audio_exts | video_exts
    if target.suffix.lower() not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {target.suffix}. Supported: {', '.join(sorted(allowed))}",
        )

    srt_path = target.with_suffix(".srt")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()

        async def _run():
            try:
                result = await _extract_subtitle_core(
                    target, srt_path,
                    model_size=model_size,
                    language=language,
                    queue=queue,
                )
                await queue.put(f"data: {json.dumps({'phase': 'done', **result}, ensure_ascii=False)}\n\n")
            except Exception as e:
                await queue.put(f"data: {json.dumps({'phase': 'error', 'detail': str(e)}, ensure_ascii=False)}\n\n")
            await queue.put(None)

        asyncio.create_task(_run())

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
