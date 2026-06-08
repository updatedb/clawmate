# 方案：Task Template 统一体系

> 将 feedback 标签、AI 自定义任务（字幕纠错、图片修改等）、Agent 处理 prompt、前端按钮渲染全部统一到 task_template 体系管理。

---

## 现状：配置散落四处

| 层面 | 当前管理方式 | 位置 |
|------|------------|------|
| feedback 标签 action/scope | `config.json feedback.tags[]` | 后端 config |
| Agent 处理指令 | `_wake_agent_for_root` 硬编码 | `feedback_api.py` |
| 前端 AI 按钮 | preview.html 写死 | HTML + JS |
| subtitle/correct 自定义 prompt | routes.py 字符串拼接 | `routes.py` |
| 按钮按文件类型匹配 | 前端按扩展名硬判断 | preview.html |

---

## 统一方案：Task Template

### 数据结构

```json
{
  "task_templates": [
    {
      "id": "review_delete",
      "label": "🗑 删除",
      "action": "delete",
      "scope": "document",
      "source": "selection",              // 选中文本后浮窗触发
      "match": {"ext": ["md", "txt", "py", "js", "json", "html", "css", "go", "rs", "ts", "yaml", "xml"]},
      "agent_prompt": "清除选中内容",
      "frontend": {"tooltip": true, "panel": true}
    },
    {
      "id": "review_modify",
      "label": "🔧 修改",
      "action": "modify",
      "scope": "document",
      "source": "selection",
      "match": {"ext": ["md", "txt", "py", "js", "json", "html"]},
      "agent_prompt": "修改选中内容，思路如下：",
      "frontend": {"tooltip": true, "panel": true}
    },
    {
      "id": "review_explain",
      "label": "📈 扩展",
      "action": "explain",
      "scope": "document",
      "source": "selection",
      "match": {"ext": ["md", "txt"]},
      "agent_prompt": "详细解释选中内容",
      "frontend": {"tooltip": true, "panel": true}
    },
    {
      "id": "review_simplify",
      "label": "📉 简化",
      "action": "simplify",
      "scope": "document",
      "source": "selection",
      "match": {"ext": ["md", "txt"]},
      "agent_prompt": "抽象选中内容，简单描述",
      "frontend": {"tooltip": true, "panel": true}
    },
    {
      "id": "project_execute",
      "label": "⚡ 执行方案",
      "action": "execute",
      "scope": "project",
      "source": "selection",
      "match": {"ext": ["md", "txt"]},
      "agent_prompt": "文档审批通过，执行方案。\n读取 {file} 中的方案，在 project 范围内实施。",
      "frontend": {"tooltip": true, "panel": true}
    },
    {
      "id": "subtitle_correct",
      "label": "🤖 AI 字幕纠错",
      "action": "modify",
      "scope": "document",
      "source": "media_bar",
      "match": {"ext": ["mp3", "wav", "m4a", "mp4", "webm", "ogg"]},
      "agent_prompt": "【AI 字幕纠错任务】\n请修正以下 SRT 字幕文件的文字内容。\nSRT 文件路径：{srt_path}\n修正规则：\n1. 修正文字转录错误、添加标点符号（不含句号）、不合理的重复\n2. 合并过短的字幕，拆分过长的字幕段，合并时间戳范围\n3. 输出必须是合法 SRT 格式\n4. 用修正后的完整 SRT 内容替换写回源文件",
      "frontend": {"media_bar": true}
    },
    {
      "id": "image_edit",
      "label": "🎨 AI 图片编辑",
      "action": "modify",
      "scope": "document",
      "source": "image_bar",
      "match": {"ext": ["png", "jpg", "jpeg", "webp", "gif", "svg"]},
      "agent_prompt": "【AI 图片编辑任务】\n图片路径：{file}\n用户需求：{user_prompt}\n请根据需求编辑图片并保存。",
      "frontend": {"image_bar": true}
    }
  ]
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识，写入 feedback card 的 `task_id` 字段 |
| `label` | 按钮显示文字 |
| `action` | add / delete / modify / explain / simplify / translate / execute |
| `scope` | document（操作文件）/ project（操作项目） |
| `source` | 触发方式：selection（选中文本浮窗）/ media_bar / image_bar / panel |
| `match.ext` | 文件扩展名匹配规则，决定哪些文件显示该按钮 |
| `agent_prompt` | Agent 处理指令，支持 `{file}`、`{position}`、`{content}`、`{note}` 等标准变量插值 |
| `frontend` | 按钮显示位置的开关 |

### position 格式规范

position 字段因文件类型不同，采用以下标准格式：

| 文件类型 | position 格式 | 示例 |
|---------|-------------|------|
| Word / PPT / PDF | Page {start}-{end} | `Page 1-2` |
| 纯文本 / 脚本 | Line {start}-{end} | `Line 9-12` |
| Markdown | Section {id} / Section {heading} | `Section 1.1.2` / `Section ##xxx` |
| 音频 / 视频 / SRT | Time {HH:MM:SS} | `Time 00:00:00` |
| Excel | Range {col}{row}-{col}{row} | `Range A1-B4` |
| 图片 | Area [x,y]xR | `Area [100,200]x50` |

Agent 根据 position 格式识别文件类型和定位方式。


### 通用字段 vs 模板特定字段

所有 task 共享以下基础字段，由调用方在 `POST /api/task/run` 时传入：

| 字段 | 来源 | 说明 |
|------|------|------|
| `root` | 调用方 | 根目录标识 |
| `project` | 调用方 | 项目名 |
| `file` | 调用方 | 文件路径（相对 root） |
| `content` | 选中文本 / 模板渲染 | 提交的内容 |
| `note` | 渲染后的 `agent_prompt` | Agent 的处理指令 |
| `position` | 选中文本位置 / 时间戳 / 图片区域 | 定位信息 |

**不需要独立的 `params` 字段**。不同 task 只是填充 `content`/`note`/`position` 的方式不同：

| 场景 | content 来源 | note 来源 | position 来源 |
|------|-------------|-----------|-------------|
| 选中文本 → 删除 | 用户选中文本 | `agent_prompt` | 行号范围 |
| 选中文本 → 翻译 | 用户选中文本 | `agent_prompt` | 行号范围 |
| 选中文本 → 执行 | 用户选中文本 | `agent_prompt` + `{file}` | 行号范围 |
| 字幕纠错 | SRT 文件内容 | 渲染后的 `agent_prompt`（含 `{srt_path}`） | 无 |
| 图片编辑 | 图片路径 | 渲染后的 `agent_prompt`（含 `{file}` + `{user_prompt}`） | 图片区域 |

---

## 三端统一

### 后端：单一路由 `POST /task/run`

```python
POST /api/clawmate/task/run
Body: {
  "root": "webprojects",
  "project": "content-studio",
  "task_id": "subtitle_correct",
  "file": "content-studio/output/xxx.mp3"
}
```

`task_runner.py` 处理逻辑：

```
1. 从 task_templates 查找 task_id
2. 校验 match.ext 与 file 扩展名是否一致
3. content = 选中文本（由前端传入，subtitle_correct 等系统 task 由前端或调用方传入）
4. 渲染 agent_prompt（变量插值: {file}, {content}, {srt_path} 等）
   - agent 根据 note 中的文件路径自行读取文件内容，避免 feedback.json 膨胀
5. 创建 feedback card：
   - task_id = task.id
   - action = task.action
   - scope = task.scope
   - content = 步骤 3 确定的 content
   - note = 渲染后的 agent_prompt
6. 调用 _wake_agent_for_root
```

### 前端：动态渲染按钮

```
用户打开文件
  → GET /api/config → 拿到 task_templates[] + 当前文件扩展名
  → 前端过滤 match.ext 命中当前文件的模板
  → 按 source 分组渲染按钮：
     - source=selection → 选中文本后浮窗显示标签
     - source=media_bar → 媒体播放器下方按钮区
     - source=image_bar → 图片导航下方按钮区
  → 用户点击 → POST /api/task/run
```

目前前端 `pst-tags` 硬编码的标签 HTML 改为从 `/api/config` 动态生成。

### Agent：wake message 内置完整 prompt，零额外 API 调用

`_wake_agent_for_root` 在推送时不发「去查列表」的指令，而是直接把数据拼进 message：

```
ClawMate 反馈通知，有以下待处理 feedback 需要你执行：

1. [FD-CM-0070] task_id=subtitle_correct action=modify scope=document
   file: content-studio/output/xxx.mp3
   操作：读取 SRT 文件 → 按以下规则纠错 → 写回文件
   规则：修正转录错误、合并过短字幕、拆分过长段、保持 SRT 格式
   SRT 路径：content-studio/output/xxx.srt

2. [FD-CM-0069] task_id=review_delete action=delete scope=document
   file: clawmate/README.md
   操作：在文件中找到以下 content 匹配的文本段 → 删除
   content: "方法一：复制到 OpenClaw 技能目录（推荐）"

3. [FD-CM-0071] task_id=project_execute action=execute scope=project
   file: research/feedback-batch-processing.md
   操作：读取 file 全文 → 理解方案 → 在 project 范围内实施

执行完成后，批量 POST /api/clawmate/feedback/batch-update 更新状态。
```

**关键原则：Agent 收到消息后不需要调用任何 Clawmate API**（清单、batch-process 等），所有数据已在 message 中。只最后做完需要调一次 batch-update 标记状态。

### feedback card 与 task_id

feedback card 新增可选 `task_id` 字段（供日志和追踪参考，不在 agent 主流程中）：

```python
{
  "id": "FD-CM-0070",
  "task_id": "subtitle_correct",    # 可选，用于追踪
  "action": "modify",
  "scope": "document",
  "file": "...",
  "content": "...",
  "note": "..."
}
```

---

## 变化文件清单

| 文件 | 变更 |
|------|------|
| `config.json` | 移除 `feedback.tags[]`，新增 `task_templates[]` |
| `config.py` | 新增 `TaskTemplate` dataclass，移除 `FeedbackTag` |
| `task_runner.py` (新) | `POST /api/task/run` + 模板渲染 + feedback 创建 |
| `feedback_api.py` | `_wake_agent_for_root` message 简化，引用 task_id |
| `routes.py` | subtitle/correct 改为 task_runner 调用 |
| `subtitle.py` | 只保留提取逻辑，路由移至 task_runner |
| `store.py` | create_items 增加 `task_id` 字段（可选） |
| `main.py` | 注册 task_runner 路由 |
| `preview.html` | 前端按钮改为从 `/api/config` 动态渲染 |

---

## 讨论点

- ~~task_template 是放在 config.json 还是独立 yaml 文件~~ ✅ 独立 JSON 文件：`task_templates.json`（与现有 config.json 一致，零新依赖）
- ~~agent_prompt 中的变量插值格式~~ ✅ 保持 `{file}`、`{content}`、`{srt_path}` 格式不变
- 前端动态按钮的渲染性能（每次打开文件都要重新匹配）
- 现有 feedback.tags 迁移到 task_templates 的兼容方案（老数据没有 task_id）
