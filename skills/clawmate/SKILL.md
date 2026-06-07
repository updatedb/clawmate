---
name: clawmate
description: ClawMate 文件管理 + 预览 + 反馈闭环。预览链接生成、feedback 查询与处理。
license: MIT
---

# ClawMate Skill

> ⚠️ {base_url} 需要由你根据 ClawMate 服务端的实际访问地址指定，由服务端 config.json 的 public_base_url 配置决定。
> 内部 API 调用（cron job / agent 处理）使用 http://localhost:5533 绕过 nginx basic auth（此地址不受 {base_url} 影响）。

---

## 功能概览

| 命令 | 功能 | 状态 |
|------|------|:----:|
| `clawmate link <filename>` | 搜索文件生成可点击预览链接 | ✅ |
| `clawmate feed [status] [filename] [date]` | 查询 feedback 列表 | ✅ |
| `clawmate do [feedback_id]` | 处理待处理 feedback | ✅ |
| `clawmate project` | 项目级别文件管理 | 🔄 规划中 |

---

## 1. clawmate link

OpenClaw 编写文件并保存后，使用 `/clawmate link {filename}` 搜索文件并生成 Markdown 可点击预览链接。

**步骤**：
1. `GET {base_url}/api/clawmate/search?q={filename}&root={root}`
2. 匹配到文件后，构造 `{base_url}/clawmate/preview.html?root={root}&file={encoded_path}`
3. 输出 Markdown 可点击链接 `[filename](url)`

**正确输出**：
```markdown
[CLAWLIST.md](https://example.com/clawmate/preview.html?root=webprojects&file=clawmate%2FCLAWLIST.md)
```

**错误输出**（禁止）：
```
https://example.com/clawmate/preview.html?root=webprojects&file=clawmate/CLAWLIST.md   ← 裸 URL
~/webprojects/clawmate/CLAWLIST.md                                                       ← 裸路径
```

**多结果处理**：模糊匹配到多个文件时，列出所有匹配项，每项生成独立预览链接。

---

## 2. clawmate feed

查询 feedback 列表，支持过滤。

**参数**：
- `status`: `pending` / `in_progress` / `done` / `failed`（默认全部）
- `filename`: 文件名模糊匹配（可选）
- `date`: `today` 或 `YYYY-MM-DD`（默认 `today`）

**步骤**：
1. `GET {base_url}/api/clawmate/feedback/list?root={root}&project={project}&status={status}&file={filename}&since={date}`
2. 格式化输出：

```
| ID | 状态 | 文件 | 用户备注 | 更新时间 |
| FD-CM-042 | ⏳ pending | clawmate/README.md | 补充 Docker 截图 | 2026-06-06 20:00 |
```

**状态符号**：⏳ pending / 🔄 in_progress / ✅ done / ❌ failed

---

## 3. clawmate do

处理待处理 feedback（全部或指定 ID）。

### 全部处理
```
clawmate do
```

### 指定 ID
```
clawmate do FD-CM-042
```

**处理步骤**：
使用 `/api/clawmate/feedback/cron-tick` 接口来执行所有未处理的 feedback 操作。
该接口内部依次处理：查询 → 标记 in_progress → 执行变更 → 标记 done/failed。

**硬约束**：
- ⚠️ 禁止直接 read feedback.json，必须通过 API 获取结构化数据
- ⚠️ API 返回的 `item.content` 是选区原文（已解析），`item.note` 是用户备注

---

## 4. 文件推送规范

每次生成本地文件后，必须推送摘要 + 可点击预览链接给用户。

**模板**：
```markdown
✅ <做了什么>

[文件名]({base_url}/clawmate/preview.html?root=<root>&file=<encoded_path>)

<简短摘要，2-3 句话>
```

**链接生成规则**：
1. 确定文件所在 root
2. 计算文件相对于 root 目录的路径
3. URL 编码路径中的中文和特殊字符
4. 输出 `[文件名]({base_url}/clawmate/preview.html?root=<root>&file=<encoded_path>)`

**正确示例**：
```markdown
✅ 测试报告已生成

[测试报告-v1.3.md](https://example.com/clawmate/preview.html?root=webprojects&file=clawmate%2Ftest%2Ftest-report-v1.3.md)

- 通过率：49/52 (94%)
- 3 个问题均为预期行为
```

