# 方案：FeedBack 批处理合并

> 目的：解决同一文件的多个 feedback pending 项被 agent 逐条处理时，先处理的修改导致后处理的内容找不的问题。

---

## 现状与问题

### 当前处理流程

```
用户提交反馈（一次可能选中多个位置）
  ↓
CREATE 多条 item（shared file）
  ↓
_wake_agent_for_root(root_id) → POST /hooks/agent
  ↓
Agent 收到通知
  → GET /feedback/list?status=pending&root=R&project=P&file=F → N 条 pending
  → 逐条循环：
      1. 取 item i 的 content（选中文本）
      2. 在文件 F 中 search(content)
      3. 找到后执行改动（删除/替换）
      4. write file
      5. 更新 item[i].status = done
  → 下一轮可能因为文件已变，content 找不到
```

### 已出现的故障

- FD-CM-0053 和 FD-CM-0054 同时提交（同文件），agent 处理了 0053，跳过了 0054，0054 永久 stuck 在 pending
- FD-CM-0054 的 content "方法一：复制到 OpenClaw 技能目录（推荐）" 实际上仍在文件中，但因处理顺序和上下文不清被跳过
- agent 在同一个长会话中处理多个 task，feedback 通知被淹没

### 根源

| 问题 | 严重性 |
|------|:------:|
| 逐条修改文件，后处理项内容可能已不存在 | ❌ 数据出错 |
| agent 跨 item 处理时上下文不连续 | ⚠️ 效率低 |
| 同一文件多次 read/write | ⚠️ 性能浪费 |
| wake 发送到 work agent，与其它任务混在一起 | ⚠️ 容易被跳 |

---

## 方案设计

### 核心思路：批处理合并

```
Agent 收到唤醒通知
  → GET /feedback/list?status=pending&root=R&project=P&file=F → [{id, note, content, ...}, ...]
  → 如果同一文件有 ≥2 条 pending：
      → 调用 POST /api/clawmate/feedback/batch-process
      → 后端按 file 合并，返回合并后的「操作列表」
      → Agent 对 operations 去重、检查逻辑冲突
      → 冲突/异常项写入原 feedback card 的 result 字段（标记 status=failed）
      → Agent 一次性执行剩余操作 → 写一次文件
      → 批量更新所有 item 状态（含冲突标记）
  → 如果只有 1 条 pending：
      → 走现有单条处理逻辑
```

### 后端新增 `/batch-process`

```python
POST /api/clawmate/feedback/batch-process
Body: {
  "root": "webprojects",
  "project": "clawmate",
  "file": "clawmate/README.md"
}
Response: {
  "ok": true,
  "file": "clawmate/README.md",
  "current_content": "<文件当前完整内容>",
  "operations": [
    {"id": "FD-CM-0054", "note": "清除选中内容", "content": "方法一：...", "action": "delete"},
    {"id": "FD-CM-0053", "note": "清除选中内容", "content": "方法二：...", "action": "delete"},
    {"id": "FD-CM-0051", "note": "详细解释选中内容：...", "content": "...", "action": "explain"}
  ],
  "conflicts": [
    {"ids": ["FD-CM-0053", "FD-CM-0054"], "type": "duplicate_delete", "detail": "两个 delete 均匹配同一段文本，自动合并为一条删除"}
  ],
  "dedup_count": 1,
  "conflict_count": 1,
  "total": 3
}
```

### 后端处理逻辑

```
1. 按 file 收集所有 status=pending 的 item
2. content 去重（相同选中文本只保留一条，记录 dedup_count）
3. 逻辑冲突检测：
   - 两个 delete 匹配同一段文本 → 合并为一个
   - delete 与 replace 匹配同一段文本 → 标记 conflict
   - replace 与 explain 匹配同一处 → 标记 conflict
   - 冲突项加入 conflicts[]，附带冲突类型和涉及 ID
4. note 标准化：
   - "清除选中内容" → action=delete
   - "将选中内容替换为：xxx" → action=replace
   - "详细解释选中内容：xxx" → action=explain
   - 其他 → action=other
5. 读取文件当前内容
6. 返回 current_content + operations + conflicts 列表
```

### Action 作用域说明

`operations[]` 中的 action 字段有两类作用域，**Agent 处理时必须区分**：

| action 类型 | 作用域 | 说明 |
|:---|:---|:---|
| `delete` / `replace` / `explain` / `add` / `expand` / `simplify` / `translate` / `modify` | **当前文档** | 操作直接针对 `/batch-process` 指定的 `file`（即该 research 文档内容本身） |
| `execute` | **当前 project** | **不是**修改当前文档，而是执行该 research 文档提出的建议方案（如改代码、改配置），作用于 project 下的实际代码/配置文件 |

#### Tag → Action 映射

`config.json` 中 `feedback.tags[]` 的标签通过其 `prompt` 模板与 batch-process 的 action 类型关联。**Agent 收到 batch-process 的结果后，根据 `note` 内容自动识别 action 类型**：

| feedback tag label | feedback tag prompt | 对应 action 类型 | 作用域 |
|:---|:---|:---|:---|
| 🗑 删除 | 清除选中内容 | `delete` | 当前文档 |
| 🔧 修改 | 修改选中内容，思路如下： | `modify` / `replace` | 当前文档 |
| 📈 扩展 | 详细解释选中内容 | `explain` / `expand` | 当前文档 |
| 📉 简化 | 抽象选中内容，简单描述 | `simplify` | 当前文档 |
| ⚡ 执行 | 文档审批通过，执行方案 | `execute` | 当前 project |

> **识别方式**：batch-process 后端根据 `note` 文本前缀与 tag prompt 匹配，自动设置 `operation.action`。Agent **不应自行猜测** action 类型，应始终使用 batch-process 返回的 `action` 字段。

#### 各 action 的执行方式

| action | 执行方式 | 示例 |
|:---|:---|:---|
| `delete` | 在 `current_content` 中定位 `content` 匹配的文本段，整段移除 | 删除过期段落 |
| `replace` / `modify` | 在 `current_content` 中定位 `content` 匹配的文本段，替换为 `note` 中的思路/替换值 | 用优化参数替换原有逻辑 |
| `explain` / `expand` | 在 `content` 匹配段下方插入补充说明（另起段落，不覆盖原文） | 在关键词后加注释说明 |
| `simplify` | 将 `content` 匹配的文本段抽象为简洁描述（保留关键信息，去除冗余） | 将三段文字缩为一段总结 |
| `add` | 在文件末尾或指定位置追加新内容（`content` 可为空，追加内容来自 `note`） | 追加新章节 |
| `execute` | **不修改当前文档**，根据 `note` 指引到 project 的代码/配置文件中执行改动 | 修改 config.json 中的 server 地址 |

**Agent 按 action 类型决定执行方式**：
- 文档操作（delete/replace/explain/add 等）：在 `current_content` 中找到对应位置直接修改
- 项目操作（execute）：根据 operation 中的 note/content 指引，到 project 的代码文件中去执行改动

> 同一 batch 中可能同时包含文档操作和执行操作。Agent 应**先执行所有文档操作**（一次读完文件、一次写完），**再依次执行项目操作**（每个 execute 单独到对应代码文件执行）。

### Agent 处理逻辑（修改后的 prompt）

```
1. GET /feedback/list?root=R&project=P&file=F&status=pending
2. 如果同一文件有 ≥2 条 pending：
   → POST /batch-process（携带 root/project/file）
3. 读取返回的 current_content + operations + conflicts
4. 处理逻辑冲突（conflicts 列表）
   - 合并型冲突（delete+delete 同段）→ 允许合并，标记 success
   - 互斥型冲突（delete vs replace 同处）→ agent 按 note 优先级决策
   - 无法决策 → 设 operation.status = skip
5. 对 operations 去重（去重后冗余项标 skip）
6. skip/conflict 异常项不创建新 card，直接写入对应 feedback card 的 result 字段
   status=failed + result 注明具体冲突/跳过原因
7. 一次性执行剩余操作（只读一次文件，只在最后写一次）
   - delete: 去掉 content 匹配的文本行/块
   - replace: 替换 content 为 note 中的替换值
   - explain: 在 content 下方补充说明
8. 一次性写入新文件内容
9. 批量 POST /feedback/batch-update（逐项标记状态）
   - 执行成功的 item → status=done
   - 冲突/异常的 item → status=failed + result 注明原因
   - （异常项已通过 result 字段记录，无需创建新 card）
```

### 批量更新后端 `/batch-update`

```python
POST /api/clawmate/feedback/batch-update
Body: {
  "items": [
    {"id": "FD-CM-0054", "status": "done", "result": "删除成功"},
    {"id": "FD-CM-0053", "status": "done", "result": "与FD-CM-0054合并删除"}
  ]
}

支持逐项标记不同状态（done/failed/conflict），减少 HTTP 调用。
```

---

## 变更文件清单

| 文件 | 变更内容 | 估算行数 |
|------|---------|:--------:|
| `feedback_api.py` | 新增 `POST /batch-process` 路由 + 去重+冲突检测逻辑 | ~100 |
| `feedback_api.py` | 新增 `POST /batch-update` 路由（逐项批量更新） | ~40 |
| `feedback_api.py` | `_wake_agent_for_root` 中的 prompt 更新（指向批处理） | ~5 |
| `store.py` | 新增 `batch_update_items()` + `batch_add_item()` 函数 | ~30 |
| 合计 | | ~175 |

---

## 风险和注意事项

| 风险 | 应对 |
|------|------|
| 多个文件的 pending 同时存在 | 按 file 分组，每文件一次批处理 |
| agent 写文件时文件被外部修改 | 乐观锁：写前读 mtime，不一致则重做 |
| 某一操作失败是否全部回滚 | **不回滚**— 前端可单条重试失败项 |
| API 兼容性 | 新 endpoint 不影响现有单条处理逻辑 |

---


