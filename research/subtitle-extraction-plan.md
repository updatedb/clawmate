# 字幕提取功能方案

> 状态：✅ 已审批 — 执行方案 A（本地 faster-whisper）  
> 背景：在 ClawMate 中预览音视频文件时，用户可一键提取人声并生成 SRT 字幕文件。  
> 审批时间：2026-06-03

---

## 方案概览

从音频（mp3/wav）或视频（mp4/webm/mov）中提取人声 → 语音识别生成 SRT 字幕 → 自动关联到原媒体文件。

```
用户点击「提取字幕」
  → ffmpeg 提取音频流 (wav 16kHz mono)
  → faster-whisper 语音识别
  → 生成 .srt 文件（保存在同目录，同名不同后缀）
  → CLI 进度通过后端 event stream 返回前端
  → 字幕面板自动加载新生成的 .srt
```

---

## 1. 技术选型

### 语音识别引擎

| 引擎 | 速度 (CPU) | 精度 | 内存 | 模型大小 | 推荐 |
|------|:--:|:--:|:--:|:--:|:--:|
| **faster-whisper tiny** | 实时 10x | 中等 | ~1GB | 75MB | ✅ 快速原型 |
| **faster-whisper small** | 实时 4x | 良好 | ~2GB | 480MB | ✅ 推荐 |
| faster-whisper medium | 实时 1x | 高 | ~4GB | 1.5GB | ⚠️ 内存紧张 |
| openai-whisper | 实时 0.3x | 高 | ~5GB | 1.5GB | ❌ 太慢 |
| insanely-fast-whisper | - | 高 | - | - | ❌ 需要 GPU |

**推荐 `faster-whisper` + `small` 模型**：
- CPU 可用（无需 GPU），本机 7.2GB RAM 足够
- `small` 模型精度良好，中文识别准确
- pip 安装：`pip install faster-whisper`
- 依赖 CTranslate2（已编译好的二进制，无系统依赖）

### 备选：轻量方案

如内存不足，可选 `tiny` 模型（仅 75MB），精度略降但速度更快。

---

## 2. 依赖

```bash
pip install faster-whisper
# 首次运行时自动下载模型文件到 ~/.cache/huggingface/
```

已有依赖（无需额外安装）：
- ffmpeg（已安装 v7.0.2）
- ffprobe（已安装）

---

## 3. 后端 API 设计

### 新增端点

```
POST /api/clawmate/subtitle/extract
```

**请求体**：
```json
{
  "root": "webprojects",
  "path": "media/会议录音.mp3",
  "model": "small",
  "language": "zh"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| root | string | ✅ | root ID |
| path | string | ✅ | 音频/视频文件相对路径 |
| model | string | ❌ | tiny/small/medium，默认 small |
| language | string | ❌ | zh/en/auto，默认 auto（自动检测） |

**响应**（事件流 / SSE）：
```
data: {"phase":"extracting","progress":0}
data: {"phase":"extracting","progress":50}
data: {"phase":"transcribing","progress":0,"detail":"正在识别语音..."}
data: {"phase":"transcribing","progress":30,"detail":"已识别 30 秒"}
data: {"phase":"transcribing","progress":80,"detail":"已识别 80 秒"}
data: {"phase":"done","srt_path":"media/会议录音.srt"}
```

**错误响应**：
```json
{
  "ok": false,
  "error": "no_speech_detected",
  "detail": "未检测到人声"
}
```

### 扩展：查询字幕

```
GET /api/clawmate/subtitle/status?root=webprojects&path=media/会议录音.mp3
```
返回：
```json
{
  "has_subtitle": true,
  "srt_path": "media/会议录音.srt",
  "srt_size": 12345
}
```

---

## 4. 核心实现

### routes.py 新增

```python
# dev/subtitle.py — 独立模块

import subprocess
import tempfile
import os
from pathlib import Path
from faster_whisper import WhisperModel

MODEL_SIZE = "small"  # tiny | small | medium
MODEL = None  # 延迟加载

def _get_model(size: str = "small"):
    global MODEL
    if MODEL is None:
        MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    return MODEL

def extract_audio(input_path: Path) -> Path:
    """用 ffmpeg 提取 16kHz mono wav"""
    output = input_path.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-vn",                # 去掉视频流
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", "16000",       # 16kHz 采样率
        "-ac", "1",           # 单声道
        "-y",                 # 覆盖
        str(output)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output

def generate_srt(segments, output_path: Path):
    """将 faster-whisper segment 转为 SRT 格式"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = _format_time(seg.start)
            end = _format_time(seg.end)
            text = seg.text.strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")

def _format_time(seconds: float) -> str:
    """秒数 → SRT 时间戳 HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

async def extract_subtitle(
    file_path: Path,
    srt_path: Path,
    model_size: str = "small",
    language: str = None,
    progress_callback=None
):
    """核心提取流程"""
    # Step 1: 提取音频
    if progress_callback:
        await progress_callback("extracting", 0, "正在提取音频...")
    
    if file_path.suffix.lower() in ('.mp4', '.webm', '.mov', '.avi', '.mkv'):
        audio_path = extract_audio(file_path)
        cleanup_audio = True
    else:
        audio_path = file_path  # 本身就是音频
        cleanup_audio = False
    
    if progress_callback:
        await progress_callback("extracting", 100, "音频提取完成")
    
    # Step 2: 语音识别
    if progress_callback:
        await progress_callback("transcribing", 0, "正在加载模型...")
    
    model = _get_model(model_size)
    
    if progress_callback:
        await progress_callback("transcribing", 10, "正在识别语音...")
    
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,  # 过滤静音
    )
    
    # Step 3: 生成 SRT（逐段回调进度）
    seg_list = []
    total_duration = info.duration
    for seg in segments:
        seg_list.append(seg)
        if progress_callback and total_duration > 0:
            pct = min(90, 10 + int(seg.end / total_duration * 80))
            await progress_callback("transcribing", pct, f"已识别 {int(seg.end)}/{int(total_duration)} 秒")
    
    generate_srt(seg_list, srt_path)
    
    if cleanup_audio and audio_path.exists():
        audio_path.unlink()
    
    if progress_callback:
        await progress_callback("done", 100, f"字幕生成完成: {srt_path.name}")
    
    return {
        "srt_path": str(srt_path),
        "language": info.language,
        "duration": total_duration,
        "segments": len(seg_list),
    }
```

### routes.py 端点

```python
@router.post("/api/clawmate/subtitle/extract")
async def clawmate_subtitle_extract(request: Request):
    body = await request.json()
    root_id = body.get("root")
    file_path = body.get("path")
    model_size = body.get("model", "small")
    language = body.get("language")
    
    # 安全校验
    _, target, _ = safe_path(root_id, file_path)
    if not target.exists():
        raise HTTPException(404, "File not found")
    
    srt_path = target.with_suffix('.srt')
    
    # SSE 流式响应
    async def event_generator():
        async def progress(phase, pct, detail=""):
            yield f"data: {json.dumps({'phase': phase, 'progress': pct, 'detail': detail})}\n\n"
        
        try:
            # 发送进度
            async for msg in progress("extracting", 0, ""):
                yield msg
            
            result = await extract_subtitle(
                target, srt_path, model_size, language,
                progress_callback=progress
            )
            yield f"data: {json.dumps({'phase': 'done', **result})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'phase': 'error', 'detail': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

---

## 5. 前端集成

### 触发入口

在 `preview.html` 媒体播放器工具栏添加按钮：
```
[▶️ 播放] [🔊 音量] [📝 字幕面板] [🎙️ 提取字幕]
```

### 进度展示

点击「提取字幕」后：
```
┌─────────────────────────────┐
│  🎙️ 正在提取字幕...         │
│  ████████████░░░░░░  65%    │
│  已识别 120/180 秒          │
│                             │
│  [取消]                     │
└─────────────────────────────┘
```

### 完成后

```
✅ 字幕提取完成
   → 会议录音.srt (180 秒, 45 条字幕)
   → 字幕面板已自动加载
```

### 前端实现要点

```javascript
async function extractSubtitle() {
  showProgressModal('🎙️ 正在提取字幕...');
  
  const response = await fetch('/api/clawmate/subtitle/extract', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      root: rootId,
      path: filePath,
      model: 'small',
      language: 'zh'
    })
  });
  
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    
    const text = decoder.decode(value);
    for (const line of text.split('\n')) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        if (data.phase === 'done') {
          hideProgressModal();
          showToast('✅ 字幕提取完成');
          loadSubtitle(data.srt_path);  // 加载到字幕面板
        } else if (data.phase === 'error') {
          hideProgressModal();
          showToast('❌ ' + data.detail, 5000);
        } else {
          updateProgress(data.progress, data.detail);
        }
      }
    }
  }
}
```

---

## 6. 限制与边界

| 项目 | 说明 |
|------|------|
| **首模型下载** | 首次使用需下载 small 模型（~480MB），耗时约 2-5 分钟 |
| **处理速度** | CPU small 模型：约 4x 实时（1 分钟音频 ≈ 15 秒处理） |
| **最大时长** | 建议限制 2 小时以内（内存/超时约束） |
| **语言** | 支持 99 种语言，中文识别良好 |
| **噪声环境** | VAD 过滤静音，嘈杂环境精度下降 |
| **并发** | 单任务执行（内存限制），后续请求返回 429 |

---

## 7. 前端最小集改动

| 文件 | 改动 |
|------|------|
| `preview.html` | 媒体播放器工具栏加「🎙️ 提取字幕」按钮 + 进度弹窗 |
| `style.css` | 进度弹窗样式 `.subtitle-progress-*` |
| `app.js` | 无改动（字幕提取仅在 preview 触发） |

> 字幕面板 `.subtitle-*` 样式已在 style.css 中（之前 CSS 统一收口时移入）。

---

## 8. 实施计划

| 阶段 | 内容 | 预估工时 |
|------|------|:--:|
| Phase 1 | 后端 subtitle.py 核心模块 + API 端点 | 2h |
| Phase 2 | SSE 进度事件流 + 错误处理 | 1h |
| Phase 3 | 前端「提取字幕」按钮 + 进度 UI | 1h |
| Phase 4 | 模型下载提示 + 边界测试 | 0.5h |
| Phase 5 | `pip install faster-whisper` + requirements.txt 更新 | 0.2h |

**总计：约 5 小时**

---

## 9. 备选方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A: faster-whisper 本地** | 隐私、免费、离线 | 首次下载模型、CPU 速度受限 |
| B: OpenAI Whisper API | 精度最高、零部署 | 付费、需外网、数据出境 |
| C: 阿里云语音识别 | 中文精度高 | 付费、需 API Key、数据出境 |

**推荐方案 A（本地 faster-whisper）**：ClawMate 定位为本地工具，隐私优先。

---

## 10. 验收标准

- [ ] 上传 mp3/wav 音频 → 点击提取字幕 → 生成 .srt 同目录同名文件
- [ ] 上传 mp4 视频 → 提取字幕 → 自动提取音频流 → 识别 → 生成 .srt
- [ ] 进度条实时更新（百分比 + 文字描述）
- [ ] 字幕面板自动加载新生成的 .srt
- [ ] 无语音文件 → 返回 "未检测到人声" 提示
- [ ] 超大文件（>2 小时）→ 友好提示超限
- [ ] 首次使用 → 提示正在下载模型
