---
name: clawmate
description: ClawMate 文件管理 + 预览 + 反馈闭环。预览链接生成、feedback 查询与处理。
license: MIT
---

# ClawMate Skill

> {base_url} 由 ClawMate 服务端 config.json 的 public_base_url 决定。
> 内部 API 调用（cron job / agent 处理）使用 http://localhost:5533 绕过 nginx basic auth。

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

搜索文件并生成 Markdown 可点击预览链接。

**步骤**：
1. `GET http://localhost:5533/api/clawmate/search?q={filename}&root={root}`
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
1. `GET http://localhost:5533/api/clawmate/feedback/list?root={root}&project={project}&status={status}&file={filename}&since={date}`
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
1. `GET /api/clawmate/feedback/list?root={root}&project={project}&status=pending`
2. 逐条处理：
   a. `POST /feedback/update` → status=in_progress
   b. 读取 `item.content`（选区原文）+ `item.note`（用户备注）→ AI 理解 → 定位文件 → 修改
   c. `POST /feedback/update` → status=done，带 result 摘要
3. 异常 → status=failed
4. 输出统计：成功 N 条，失败 M 条

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

---

## 5. API 参考

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/clawmate/config` | GET | 获取 roots、默认 root 等配置 |
| `/api/clawmate/list?root=&dir=` | GET | 列出目录内容 |
| `/api/clawmate/search?q=&root=&dir=` | GET | 递归搜索文件 |
| `/api/clawmate/feedback/list` | GET | 查询 feedback 列表 |
| `/api/clawmate/feedback/update` | POST | 更新 feedback 状态 |
| `/api/clawmate/preview` | GET | 获取文件内容（二进制/JSON） |
| `/api/clawmate/rename` | POST | 重命名文件 |
| `/api/clawmate/delete` | POST | 删除文件 |

---

## 6. 常见错误

| 错误 | 原因 | 修复 |
|------|------|------|
| 401 Unauthorized | 未登录/ session 过期 | 先登录 clawmate |
| 404 File not found | 路径错误或 root 不存在 | 确认文件在正确 root 下 |
| 409 Conflict | 重命名目标已存在 | 换一个文件名 |
| 500 Internal Error | 服务端异常 | 检查 clawmate 日志 |
