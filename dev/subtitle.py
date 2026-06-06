"""
字幕提取模块 — faster-whisper 本地语音识别 + LLM 纠错
从音频/视频文件中提取人声，生成 SRT 字幕文件。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

# faster-whisper 延迟导入，首次调用时下载模型
_WHISPER_MODEL: Optional[object] = None


def _format_time(seconds: float) -> str:
    """秒数 → SRT 时间戳 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _check_subtitle_enabled():
    """检查字幕提取是否启用：config.json > 环境变量 > 默认关闭。"""
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
        # CPU int8 量化，small 模型约 480MB
        _WHISPER_MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def has_audio_stream(input_path: Path) -> bool:
    """用 ffprobe 检查文件是否包含音频流."""
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
    if not has_audio_stream(input_path):
        raise RuntimeError("文件中没有音频轨道，无法提取字幕")

    output = input_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",                     # 去掉视频流
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16kHz 采样率
        "-ac", "1",               # 单声道
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 音频提取失败: {result.stderr.strip()}")
    return output


def generate_srt(segments, output_path: Path) -> None:
    """将 faster-whisper segment 列表写入 SRT 文件。"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_time(seg.start)
            end = _format_time(seg.end)
            text = seg.text.strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


async def extract_subtitle(
    file_path: Path,
    srt_path: Path,
    model_size: str = "small",
    language: Optional[str] = None,
    progress_callback=None,
) -> dict:
    """
    核心提取流程。

    Args:
        file_path:     媒体文件路径（mp3/wav/mp4/webm/mov 等）
        srt_path:      输出的 .srt 文件路径
        model_size:    faster-whisper 模型大小 tiny/small/medium
        language:      语言代码或 None（自动检测）
        progress_callback: async fn(phase, pct, detail) — 进度回调

    Returns:
        dict，含 srt_path / language / duration / segments
    """
    # Step 1: 音频提取
    if progress_callback:
        await progress_callback("extracting", 0, "正在提取音频...")

    is_video = file_path.suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv")
    if is_video or file_path.suffix.lower() in (".mp3", ".wma", ".ogg", ".flac", ".aac", ".m4a"):
        audio_path = extract_audio(file_path)
        cleanup_audio = True
    else:
        audio_path = file_path
        cleanup_audio = False

    if progress_callback:
        await progress_callback("extracting", 100, "音频提取完成")

    # Step 2: 加载模型
    if progress_callback:
        await progress_callback("transcribing", 0, "正在加载模型（首次约需 2-5 分钟）...")

    model = _get_whisper_model(model_size)

    if progress_callback:
        await progress_callback("transcribing", 5, "模型加载完成，开始识别...")

    # Step 3: 语音识别
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,   # 过滤静音
    )

    # Step 4: 生成 SRT（逐段回调进度）
    seg_list = []
    total_duration = info.duration or 0.0

    for seg in segments_gen:
        seg_list.append(seg)
        if progress_callback and total_duration > 0:
            pct = min(90, 5 + int(seg.end / total_duration * 85))
            await progress_callback(
                "transcribing", pct,
                f"已识别 {int(seg.end)}/{int(total_duration)} 秒"
            )
        elif progress_callback:
            await progress_callback("transcribing", 50, "识别中...")

    generate_srt(seg_list, srt_path)

    # 清理临时音频
    if cleanup_audio and audio_path.exists():
        try:
            audio_path.unlink()
        except OSError:
            pass

    if progress_callback:
        await progress_callback("done", 100, f"字幕已生成: {srt_path.name}")

    return {
        "srt_path": str(srt_path),
        "language": info.language,
        "duration": total_duration,
        "segments": len(seg_list),
    }


# ── LLM 字幕纠错 (已删除 — 改为通过 agent 处理) ────────────────
