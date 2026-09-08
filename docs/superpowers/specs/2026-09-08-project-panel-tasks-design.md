# ClawMate Project Panel —— 推荐任务:codex 生成 + 删除 + 后端配置(本轮)

日期：2026-09-08
范围：**仅推荐任务（recommendations）**这一块。runs 取消/删除、CLAWLIST 操作、`/tasks/run` 改读新后端等均推迟到后续（见文末「本轮不做」）。

## 背景与现状

ClawMate project panel 的推荐任务来自 `.clawmate/project.json` 的 `recommended_tasks`（source：`project_json` / `discover` / `discover-llm` / `rule`），由 `_recommendations_for()` + `_project_task_catalog()` 产出。现状：

- 无「删除」；且 `_project_task_catalog()` 会把默认任务（`commit_version`、`maintain_project_docs`、`update_meeting_info`）自动补回，删了会复活。
- 无 codex 分析生成；推荐完全来自项目本地 markdown/规则的解析。
- `config.json` 中 `agent.backend`（通用无人值守）无项目面板专属后端。

## 目标（本轮）

1. 新增 `agent.project_backend`（默认 `"auto"`），作为项目面板（推荐任务）专属执行/分析后端。
2. 推荐任务可「删除」且**持久**（delete 不复活，默认任务也遵循）。
3. 推荐可由 **codex 分析项目内容生成**：手动按钮触发，后端跑 `cli -p` 并解析合并进 `recommended_tasks`。

## 非目标（本轮）

- 不做 runs 取消/删除。
- 不做 CLAWLIST 删除/完成/执行到 Agent。
- `/tasks/{id}/run` 暂不改用 `agent.project_backend`（仍用 `agent.backend`）；是否切换后续再定。
- 不做 openclaw(gateway) 进程级取消。

## 1. 配置:`agent.project_backend`

- `dev/config.py`：`AgentConfig` 新增 `project_backend: str = "auto"`。
  - 取值 `claude | codex | openclaw | auto`，复用 `_agent_backend` 校验；为空则回退到 `backend`。
  - `load_cfg()` 解析 `agent.project_backend`，可选环境变量 `CLAWMATE_AGENT_PROJECT_BACKEND` 覆盖。
- `config.json` 示例：`{ "agent": { "project_backend": "auto" } }`。
- `TaskExecutor.launch` 的 `auto` 候选顺序已是 `codex → claude → openclaw`，故默认 `"auto"` 即「codex 优先、失败兜底」。

## 2. 推荐删除(持久)

- `POST /api/clawmate/project/{root}/{project}/recommendations/{task_id}/delete`
  - 将 `task_id` 加入 `project.json` 新增字段 **`dismissed_recommendations: list[str]`**，并从 `recommended_tasks` 移除该项。
  - `_project_task_catalog()` 跳过 dismissed 中的任何 id（默认任务也遵循 → 删了不复活）。
  - 幂等：删除不存在的 id 也返回 `ok:true`。
- 前端：每个推荐项加「删除」（`data-recommend-delete`）。

## 3. codex 分析生成(手动按钮)

- `POST /api/clawmate/project/{root}/{project}/recommendations/analyze`
  - 后端用 `agent.project_backend` 跑一次无交互 `cli -p "<提示词>"`（`cwd=项目目录`），捕获 stdout，超时约 90s。
  - 解析：剥离 Markdown 围栏，截取首个 `[` 到末个 `]` 后 `json.loads`；校验每项含 `label`，允许 `id` 缺失时回退到 label。
  - 合并：保留非 `source=="codex"` 条目，替换旧的 `source=="codex"` 条目，追加新 codex 条目（同样跳过 dismissed）；写回 `recommended_tasks`。
- 提示词模板（示意，仅允许项目内路径，只输出 JSON 数组）：
  > 你是项目分析助手。用 sumi/superpower/productmanager 等技能深入分析当前项目（仅限当前目录），识别最值得交给 Agent 执行的下一步任务。只输出一个 JSON 数组，不要解释文字。每项字段：`id`(短 kebab)、`label`(中文短标题)、`prompt`(给执行 Agent 的完整指令)、`kind`(plan|maintenance|documentation|meeting|research)、`frequency`(0)。只基于项目真实状态与文档，不要编造。
- 前端：推荐区加「分析项目（Codex）」按钮，点击后按钮 loading，成功后 `refresh()` 并 toast。

## 4. 前端改动

- `dev/static/js/project-panel.js`（preview）：
  - 推荐列表加「删除」按钮；推荐区标题行加「分析项目」按钮。
  - 绑定 `data-recommend-delete` / `data-analyze` handler。
- `dev/static/js/app.js`（index）：
  - 同样在 `renderProjectPanel` 补按钮 + handler，保持两端一致。
- `dev/static/css/style.css`：新按钮样式（沿用 `project-panel-action`）。

> 现状 index(preview) 与 preview 并存两套渲染器；align 两端新增行为即可，不重构合并。

## 5. 数据模型

`project.json`：
```
recommended_tasks: [ ... ]          # 既有
dismissed_recommendations: [id...]  # 新增
```

## 6. 后端接口

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `.../recommendations/{task_id}/delete` | 持久删除推荐（dismissed） |
| POST | `.../recommendations/analyze` | 用 project_backend 跑 codex 分析生成推荐 |

## 7. 错误处理

- codex 分析超时 / 非零退出 / 解析失败 → 返回 `{ok:false, detail}`（HTTP 502 或 200 带 detail），前端 toast 不刷推荐。
- 推荐删除不存在 → 幂等 `ok:true`。

## 8. 测试

- `tests/test_recommendations_manage.py`：
  - `_project_task_catalog` 过滤 dismissed（默认任务也能删）。
  - `/recommendations/{id}/delete`：新增、重复删、幂等。
  - `/recommendations/analyze`：解析/合并/替换 codex 源、失败路径（mock `cli -p` 输出与非零退出）。
- 既有 `test_project_overview.py` / `test_project_panel_shared.py` 字符串断言同步（新增按钮/端点）。
- 回归：`python -m pytest` 全量，基线 312 + 新增无回归。

## 9. 本轮不做（后续）

- runs 取消/删除（`runs/{id}/cancel`、`runs/{id}/delete` + 墓碑过滤）。
- CLAWLIST 删除/完成/执行到 Agent panel（`clawlist/delete`、`insertText` 转移）。
- `/tasks/{id}/run` 读 `agent.project_backend`（执行后端切换）。

## 10. 改动文件清单

- 后端：`dev/config.py`、`dev/project_routes.py`、`dev/task_executor.py`（复用 `TaskExecutor` 的 CLI 启动，可能加一个 `analyze` 辅助函数）。
- 前端：`dev/static/js/project-panel.js`、`dev/static/js/app.js`、`dev/static/css/style.css`。
- 测试：`tests/test_recommendations_manage.py` + 既有用例更新。
