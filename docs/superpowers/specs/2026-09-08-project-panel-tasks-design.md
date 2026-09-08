# ClawMate Project Panel 任务管理改进 —— 设计

日期：2026-09-08
范围：project panel 的任务运行（runs）、推荐任务（recommendations）、CLAWLIST 三条能力的交互与管理。

## 背景与现状

ClawMate 的 project panel（`project-panel.js` / `app.js` 的 `renderProjectPanel`）当前是一个只读概览：

- **runs（正在/最近执行）**：只展示状态；仅失败任务带「重试」。运行由 `dev/task_executor.py` 通过 `codex -p` / `claude -p` 子进程启动，进程句柄存于模块级 `_ACTIVE_PROCESSES: dict[task_run_id, Popen]`；记录追加写入 `.clawmate/task-runs.jsonl`。
- **推荐任务（recommendations）**：来自 `.clawmate/project.json` 的 `recommended_tasks`（source：`project_json` / `discover` / `discover-llm` / `rule`），由 `_recommendations_for()` + `_project_task_catalog()` 产出；**默认任务**（`commit_version`、`maintain_project_docs`、`update_meeting_info`）会被 `_project_task_catalog()` 自动补回。无删除；无 codex 分析生成。
- **CLAWLIST**：`.clawmate/../CLAWLIST.md` 为真相源；仅有「完成」（`/clawlist/complete`）。无删除；无「执行到 Agent panel」。
- **配置**：`config.json` 中 `agent.backend`（通用无人值守）、`agent.ui_backend`（交互面板）。执行路径共用 `agent.backend`。

## 目标

1. **正在执行的任务**：可「取消」「删除」。
2. **推荐任务**：可「删除」（持久）；可由 codex 分析项目生成（手动按钮触发）。
3. **任务执行统一走 codex 优先、带兜底的后端**（配置化，不写死）。
4. **CLAWLIST 任务**：可「删除」「完成」；「执行」转移到 Agent panel 由用户确认后执行。

## 非目标

- 不做 openclaw（gateway）后台任务的进程级取消（仅有 external_run_id，无本地进程）。gateway 运行的 active run 不显示取消按钮，但仍可删除记录。
- 不改动 `ui_backend`（交互面板后端）语义；clawlist→agent 沿用交互后端。
- 不做后台主动刷新 codex 分析（只手动触发）。
- 不迁移项目面板为独立新框架；沿用现有原生 JS 结构。

## 总览

`config.json` 新增 `agent.project_backend`（默认 `"auto"`），供「推荐任务执行」与「codex 推荐生成」使用；`clawlist→agent` 不显式设置后端——它只是打开 Agent panel 并插入提示词，执行后端沿用 Agent panel 自身的 `ui_backend`。三条能力各自新增后端端点 + 前端按钮（index 的 `app.js` 与 preview 的 `project-panel.js` 两个渲染器都要接，避免分叉）。

## 1. Runs：取消 / 删除

### 判定「可取消」
运行处于 `{starting, running, waiting_input}`，且 `backend_actual ∈ {codex, claude}`（即 CLI 后端、在 `_ACTIVE_PROCESSES` 有句柄）。`openclaw`（gateway）无本地进程 → 不显示取消按钮。

### 端点
- `POST /api/clawmate/project/{root}/{project}/runs/{task_run_id}/cancel`
  - 从 `_ACTIVE_PROCESSES` 取出并 kill 进程（`proc.kill()`，失败则 `terminate()`），从 `_ACTIVE_PROCESSES` 移除。
  - `update_project_run(task_run_id, status="cancelled", ended_at=..., ...)` 写墓碑。
  - 若该 run 非 CLI / 无句柄：返回 409（仅 CLI 可取消）。删除记录仍可。
- `POST /api/clawmate/project/{root}/{project}/runs/{task_run_id}/delete`
  - 若在 `_ACTIVE_PROCESSES` 中仍在运行：先 kill + 移除（同 cancel）。
  - 追加一条 `status="deleted"` 的墓碑记录，保持 `.jsonl` 追加式审计。
  - 展示层过滤 `status == "deleted"` 的行。

### 读取过滤
- `task_executor.py` 新增 `_visible_project_runs(project_dir)` = `[r for r in _read_project_runs(...) if r.get("status") != "deleted"]`。
- `refresh_project_runs()` 返回改用 `_visible_project_runs`；`/runs` 与 `/overview` 的 runs 推导也基于此。`_read_project_runs` 保留原始（供内部读）。

### 前端
- index（`app.js` `_projectRunCard`）与 preview（`project-panel.js` `runCard`）统一：
  - active 且 CLI → 「取消」(data-project-cancel) + 「删除」。
  - failed/succeeded/… → 「删除」；failed 仍保留「重试」。

## 2. 推荐任务：删除 + codex 生成

### 删除（持久）
- `POST /api/clawmate/project/{root}/{project}/recommendations/{task_id}/delete`
  - 把 `task_id` 加入 `project.json` 新增字段 **`dismissed_recommendations: list[str]`**，并从 `recommended_tasks` 中移除该项。
  - `_project_task_catalog()` 跳过 dismissed 列表中的任何 id（默认任务也遵循 → 删了不复活）。
- 前端：每个推荐项加「删除」。

### codex 生成（手动按钮）
- `POST /api/clawmate/project/{root}/{project}/recommendations/analyze`
  - 后端用 `agent.project_backend` 跑一次无交互 `cli -p "<提示词>"`（`cwd=项目目录`），捕获 stdout，超时约 90s。
  - 解析：剥离 Markdown 围栏，截取首个 `[` 到末个 `]` 后 `json.loads`，校验每项含 `label`。
  - 合并：保留非 `source=="codex"` 的条目，替换旧的 `source=="codex"` 条目，追加新 codex 条目（同样跳过分歧 id）；写回 `recommended_tasks`。
- 提示词模板（示意，仅允许项目内路径，输出 JSON 数组，每项 `{id,label,prompt,kind,frequency}`）：
  > 你是项目分析助手。用 sumi/superpower/productmanager 等技能深入分析当前项目（仅限当前目录），识别最值得交给 Agent 执行的下一步任务。只输出一个 JSON 数组，不要解释文字。每项字段：`id`(短 kebab)、`label`(中文短标题)、`prompt`(给执行 Agent 的完整指令)、`kind`(plan|maintenance|documentation|meeting|research)、`frequency`(0)。只基于项目真实状态与文档，不要编造。
- 前端：推荐区加「分析项目（Codex）」按钮，点击后按钮 loading，成功后 `refresh()`。

## 3. CLAWLIST：删除 / 完成 / 执行到 Agent

- **完成**：复用现有 `POST /clawlist/complete`。
- **删除**：`POST /api/clawmate/project/{root}/{project}/clawlist/delete`
  - 复用 `_mark_clawlist_task_done` 的 exact-match 约束（单个未勾选项匹配，`\n`/超长拒绝），改为从 `CLAWLIST.md` 物理移除该行（临时文件 + `os.replace`，在 `_clawlist_write_lock` 内）。
- **执行（转移到 Agent panel）**：纯前端。
  - 点击「执行」→ `window.Agent.open(root, dir, fileContext)`，再用 `window.Agent.insertText(prompt)` 把任务文本包装成提示词插入输入框（**待用户确认回车**，不自动下发）。
  - 提示词带上项目上下文（如：在项目内完成该 CLAWLIST 任务；遵循 AGENTS.md；不要访问项目外路径）。

## 4. 执行后端配置化

- `config.py`：`AgentConfig` 新增 `project_backend: str = "auto"`（`claude | codex | openclaw | auto`），复用 `_agent_backend` 校验；空则回退到 `backend`。
- `load_cfg()` 解析 `agent.project_backend`（含环境变量 `CLAWMATE_AGENT_PROJECT_BACKEND` 可选覆盖）。
- `/tasks/{id}/run`：`TaskExecutor.launch(..., backend=cfg.agent.project_backend)`（原为 `cfg.agent.backend`）。
- `/recommendations/analyze`：用同一 `project_backend` 跑 `cli -p`。
- `TaskExecutor.launch` 的 `auto` 候选顺序已是 `codex → claude → openclaw`，因此默认 `"auto"` 即「codex 优先、失败兜底」。

## 5. 数据模型

`project.json`：
```
recommended_tasks: [ ... ]          # 既有
dismissed_recommendations: [id...]  # 新增
```
`CLAWLIST.md`、`.clawmate/task-runs.jsonl` 结构不变（后者新增 `status: "cancelled" | "deleted"` 墓碑值）。

## 6. 后端接口一览

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `.../runs/{task_run_id}/cancel` | 取消 CLI 后端运行（kill + 标 cancelled） |
| POST | `.../runs/{task_run_id}/delete` | 删除运行（kill 如活跃 + 墓碑 deleted） |
| POST | `.../recommendations/{task_id}/delete` | 持久删除推荐（dismissed） |
| POST | `.../recommendations/analyze` | 用 project_backend 跑 codex 分析生成推荐 |
| POST | `.../clawlist/delete` | 删除一条 CLAWLIST |
| POST | `.../clawlist/complete` | 既有：勾选完成 |
| POST | `.../tasks/{task_id}/run` | 既有：执行推荐（改读 project_backend） |

## 7. 前端改动

- `dev/static/js/project-panel.js`（preview）：`runCard` 加取消/删除；推荐项加删除；推荐区加「分析项目」；clawlist 行加删除/执行。对应 action 绑定（`data-project-cancel` / `data-project-delete` / `data-recommend-delete` / `data-analyze` / `data-clawlist-delete` / `data-clawlist-run`）。
- `dev/static/js/app.js`（index）：`_projectRunCard` + `renderProjectPanel` + 各 action handler 对应补齐。
- `dev/static/css/style.css`：新按钮样式（沿用 `project-panel-action`；可加 icon 变体）。

> 前端逻辑在 index / preview 两处有重复（现状即如此，两个渲染器并存）。设计沿用现状，新增行为保持两端一致；共享端点 + 薄 handler 减少重复风险。

## 8. 配置

`config.json`：
```json
{ "agent": { "project_backend": "auto" } }
```
默认值 / 校验集中在 `config.py`。

## 9. 错误处理

- 取消非 CLI / 无句柄 → 409。
- 删除/取消后端不可用 → 503 并带原因字符串（复用 receipt.failure_reason）。
- codex 分析超时 / 非零退出 / 解析失败 → 返回 200 `{ok:false, detail}` 或 502；前端 toast 提示不刷推荐。
- clawlist delete：精确匹配失败 → 409；非法任务 / 超长 → 422。
- 推荐删除已不存在 → 幂等（`ok:true`）。

## 10. 测试

- `tests/test_project_runs_cancel_delete.py`：cancel（CLI 有/无句柄、gateway 409）、delete（墓碑、读取过滤 `status==deleted`）。
- `tests/test_recommendations_manage.py`：dismissed 过滤 `_project_task_catalog`（默认任务也删）、删除端点、codex analyze 的解析/合并（mock `cli -p` 输出与失败路径）。
- `tests/test_clawlist_manage.py`：delete exact-match、complete 不变、边界（多匹配/非法）。
- 既有 `test_project_overview.py` / `test_project_panel_shared.py` 的字符串断言需同步（新增按钮/端点字符串）。
- 回归：`python -m pytest` 全量，目标基线 312 + 新增无回归。

## 11. 不做的事 / 边界

- 不对 openclaw gateway run 做进程取消（仅删除记录）。
- 不自动后台跑 codex 分析。
- 不重构现有 index/preview 双渲染器为单一实现（超范围）；只对齐新增行为。
- 不为新端点加登录之外的额外限流（与会话鉴权一致即可）。

## 12. 改动文件清单

- 后端：`dev/config.py`、`dev/project_routes.py`、`dev/task_executor.py`
- 前端：`dev/static/js/project-panel.js`、`dev/static/js/app.js`、`dev/static/css/style.css`
- 测试：`tests/`(上述新增 + 既有用例更新)
