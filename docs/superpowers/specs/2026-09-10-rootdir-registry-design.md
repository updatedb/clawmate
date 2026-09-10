# Rootdir 注册表与设置面板拆分设计

> 本规格修订并取代 `2026-09-10-multi-user-rootdir-design.md` 中与 root 建模、授权解析、设置界面、持久化相关的章节。账户与首次改密的整体目标不变。

## 目标

把 root 从「用户授权时填写的相对路径字符串」升级为**配置中登记的一等实体**（注册表），使授权引用稳定 id，恢复 label 与 agent 路由能力；同时把设置面板的 root 管理与用户管理拆成两个独立 tab；并修复审计中实测确认的授权绕过与登录锁死缺陷。

## 背景：审计确认的缺陷

本次设计同时修复下列已复现缺陷。每条都已在本地实测确认。

1. **授权绕过**（严重）。`dev/service.py:92-108` 的 `get_roots()` 在 `current_request_user()` 为 `None` 时回退读取旧 `roots` 配置。有两条路径会走到 `user=None`：会话的 `user_id` 解析不到（用户被删除或 `users.json` 重建），以及 `dev/auth.py:373-374` 的本机绕过（`127.0.0.1`/`::1`/`local_hosts`）直接 `call_next` 且从不绑定用户。实测：已删除用户的残留会话访问 `/api/clawmate/list?root=legacy` 返回 200，并列出了 `system_root_dir` 之外目录的内容。真实 `config.json` 至今保留全部 8 条旧 `roots`，该路径当下可达。

2. **登录锁死**（严重）。`dev/user_store.py:82,127` 的 `_read()` 每次读取都重新解析文件系统校验 `root_dirs`。任一授权目录被移动或删除后，`ValueError` 从 `auth_login` 冒泡，**所有账号（含管理员）都无法登录**并返回 500 带堆栈；`--set-password --force` 同样走 `_read()` 而失效，只剩手改 `users.json`。

3. **agent 路由静默退化**。`routes.py:65-72` 把前端 `agent_id` 硬编码为 `"default"`；`cfg.root_agent()`（`config.py:150`）只在授权串恰好等于旧 root id 时命中，`helper/3gpp` 这类授权退回 `default`。

4. **启动迁移校验从未实现**。原设计第 38 行要求旧 `roots` 无法收纳时显式报错，实际无任何代码，反而以静默回退扩大访问范围。

5. **目录枚举性能**。`settings_routes.py:23-28` 对 `system_root_dir` 全量 `rglob("*")`。在 `/home/openclaw` 上实测 **20.4 秒、扫描 130 万条目、产出 107,165 个目录**（其中 88,536 个为隐藏目录），且每次打开设置弹窗都执行一遍。

6. **缺失测试产物**。原计划点名的 `tests/test_auth_users.py` 与 `tests/test_user_root_authorization.py` 从未创建；`tests/test_e2e_browser.py` 无任何 settings 断言。

## 范围

包含：root 注册表的数据模型、持久化、迁移与校验；授权解析的 fail-closed 重构；本机绕过的主体映射；设置面板的两个 tab 与目录选择器；设置相关 API；测试与验收。

不包含：角色层级、**共享目录的只读/读写权限差异**（显式排除，见下）、外部身份提供商、数据库、多租户隔离。

## 数据模型

三个文件职责分离：

| 文件 | 语义 | 写入方 |
|---|---|---|
| `config.json` | 启动配置：`system_root_dir`、port、agent、onlyoffice 等（含 `openclaw_token`、`DEEPSEEK_API_KEY`、`jwt_secret` 等密钥） | **只读**，程序不改写 |
| `roots.json` | 私有运行时 root 注册表 | 设置面板 + 启动迁移 |
| `users.json` | 私有运行时账户与授权 | 设置面板 + 启动迁移 |

`roots.json` 与 `users.json` 均不提交 Git，写入采用同目录临时文件加 `os.replace` 原子替换。

```json
// roots.json
{
  "roots": [
    { "id": "3gpp", "label": "3GPP Meetings", "dir": "helper/3gpp", "agent_id": "helper" }
  ]
}
```

```json
// users.json
{
  "users": [
    {
      "id": "u-example",
      "username": "updatedb",
      "password_hash": "bcrypt-encoded-password-hash",
      "is_admin": false,
      "must_change_password": false,
      "root_ids": ["3gpp", "webprojects"]
    }
  ]
}
```

`users.json` 的授权字段由 `root_dirs`（路径）更名为 `root_ids`（注册表引用）。

### root 属性

`id`、`label`、`dir`、`agent_id` 四个字段均为必需，无冗余项：

- `id` — 授权引用的稳定锚点。改 `dir` 不断授权，这是采用注册表的核心收益。
- `label` — 前端显示名，让用户看到「3GPP Meetings」而非 `helper/3gpp`。
- `dir` — 相对 `system_root_dir` 的路径。相对化是越界校验的前提。
- `agent_id` — 决定该目录下任务派发给哪个 agent，修复缺陷 3。

**不引入**：`order`（用数组顺序）、`description`、`icon`、`created_at`（审计价值低）、`enabled`（「删除被引用时拒绝」已覆盖其价值）、`hidden`（隐藏目录只是**枚举时的过滤行为**，不是 root 的属性）。

注意区分两处「隐藏」：`roots.json` 的 root 对象**没有** `hidden` 字段；而 `browse` 响应中每个目录项的 `hidden` 表示该目录名是否以 `.` 开头，仅用于前端渲染，两者语义无关。

**显式排除**：`readonly`（只读授权）是「完整属性」最可能的下一个需求，但本规格明确不含共享目录的读写权限差异，记为 out-of-scope 而非遗漏。

**必须实施的约束**（这才是原模型真正的缺口）：

1. `id` 唯一；**创建后不可修改**（授权引用 id，改 id 等于换实体）。缺省由 `dir` 末段派生，若与既有 id 冲突则依次追加 `-2`、`-3` 直至唯一；派生结果须匹配 `[A-Za-z0-9._-]+`，否则要求显式提供 `id`。
2. `dir` 非空、非绝对路径、不为 `.`、不为系统根自身，且解析后（含符号链接）仍位于 `system_root_dir` 内。
3. `dir` 唯一——两个 root 指向同一目录时拒绝，避免前端出现两个语义含混的入口。
4. `agent_id` 仅做非空与该字符集校验。**服务端没有 agent 注册表**，`agent_id` 是直传 OpenClaw 网关的 `agentId` 字符串，无法对照校验；打错字会静默路由到不存在的 agent。此限制在规格中如实保留，不做虚假承诺。
5. **引用完整性**：删除 root 时若被任一用户的 `root_ids` 引用，返回 422 拒绝，而非静默级联解除授权。

## 启动迁移

首次启动检测到 `config.json` 存在旧 `roots` 段且 `roots.json` 不存在时执行一次性迁移：

1. 逐条把旧 `roots` 的绝对路径转为相对 `system_root_dir` 的 `dir`，保留原 `id`、`label`、`agent_id`。
2. 把 `users.json` 中各用户的授权路径按解析后目录反查，映射为 `root_ids`。
3. 任一条目无法收纳于 `system_root_dir` 内 → 打印明确错误并退出，不启动。
4. 写入前对 `roots.json` 与 `users.json` 各留一份同目录备份 `roots.json.bak` / `users.json.bak`（已存在则覆盖），写入走原子替换。
5. **幂等**：`roots.json` 已存在时跳过迁移。
6. `config.json` 的 `roots` 段迁移后**保留但不再读取**，便于回滚；README 说明可自行删除。

## 会话与授权

### 授权解析 fail-closed

拆成两层，职责分离：

- `RootRegistry.resolve(root_id) -> Path` — 纯注册表查询加越界校验，**不涉及用户**。
- `authorize_root(user, root_id) -> Path` — `root_id == "."` 且用户为管理员时返回 `system_root_dir`；否则 `root_id` 必须存在于注册表，普通用户还须在 `user.root_ids` 中。任何未登记或未授权一律拒绝，**永不回退**。

`get_roots()` 在 `system_root_dir` 存在时只保留注册表分支，删除旧 `roots` 回退分支。

### 本机绕过的主体映射

`dev/auth.py:373-374` 的本机绕过（`127.0.0.1`、`::1`、`auth.local_hosts` 中的主机）不再产生 `user=None`，而是绑定一个显式的 `local-admin` 主体（`is_admin=true`），等价于管理员登录：可访问 `.` 系统根与全部已登记 root。

这是相对现状的**范围扩大**——现状本机绕过只拿到 8 个旧 root，新模型下可及 `system_root_dir` 全域（含 `.openclaw` 等 dot 目录）。该扩大是有意为之：绕过语义本就是「本机进程完全信任、免登录」，且本机持有含全部密钥的 `config.json`。

`local-admin` 是**合成主体，不写入 `users.json`**，不参与账户 CRUD、不可被删除或改密，也无法通过设置接口修改其授权；它只在本机绕过分支被构造并绑定到请求上下文。设置面板的用户列表不得展示它。

### 会话绑定账户生命周期

会话有效但 `user_id` 在 `users.json` 中解析不到时，返回 401 并清除 cookie 要求重新登录，不再以 `user=None` 继续处理。这是缺陷 1 的根治点之一。

### 管理员可见范围

- 管理员：`.`（系统根目录）+ 全部已登记 root，各自的 `label` 与 `agent_id` 如实呈现。
- 普通用户：仅获授的 root。

管理员的可见范围由 `is_admin` 决定，**不依赖 `root_ids`**；因此 `root_ids` 对管理员账户无意义，设置接口不得接受或写入管理员的 `root_ids`（保持为空）。普通用户必须至少有一个 `root_ids`。

前端的 root 选择列表仅用于展示，服务端校验是唯一安全边界。

## 持久化与校验分层

修复缺陷 2 的关键是把校验时机拆开：

- **写入时严格校验**：存在性、越界、`dir` 重复、`id` 唯一、引用完整性。
- **读取时只做结构与类型校验**，不再重复解析文件系统。授权 id 在注册表中查不到时，在**使用时**拒绝该次请求并记录日志。

结果：单个失效或已删除的目录只影响那一个 root，不会锁死所有账号登录。

`get_user_store()` 与新的 `get_root_registry()` 统一从 `config.load()` 已解析出的配置目录取路径，不再单独读取 `CLAWMATE_CONFIG` 环境变量（当前两套来源并存是隐患）。

配置或持久化失败时返回明确的非敏感错误；密码、哈希、会话 ID 与系统绝对路径不写入浏览器日志或错误详情。

## API 契约

### Root 管理（要求管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/clawmate/settings/roots` | `{roots: [{id, label, dir, agent_id}]}` |
| POST | `/api/clawmate/settings/roots` | 创建；`{id?, label, dir, agent_id}`；`id` 缺省由 `dir` 末段派生并唯一化 |
| PATCH | `/api/clawmate/settings/roots/{root_id}` | 改 `label`/`dir`/`agent_id`；`id` 不可改 |
| DELETE | `/api/clawmate/settings/roots/{root_id}` | 被任一用户引用 → 422 |

改 `dir` 时已引用该 root 的用户授权不受影响（引用的是 id）。

### 目录浏览（要求管理员，懒加载）

```
GET /api/clawmate/settings/browse?path=helper&show_hidden=false
→ { "path": "helper", "parent": "",
    "dirs": [{"name": "3gpp", "path": "helper/3gpp", "hidden": false}],
    "truncated": false }
```

只列**子目录**、单层。`path` 解析后必须位于 `system_root_dir` 内，复用同一越界校验。`show_hidden=false` 时过滤 dot 目录。单层超过 500 项时截断并置 `truncated=true`。

`path` 缺省或为 `""` 时表示系统根，此时 `parent` 为 `null`（无上一级可去）；其余情况下 `parent` 是当前路径的父路径相对值，`path` 为 `""` 时前端禁用「上一级」。不存在的目录返回 404。

### 用户管理（要求管理员）

- `GET /api/clawmate/settings/users` → `{users: [...], roots: [{id, label}]}`。目录选项来自注册表摘要，取代原先的全量目录枚举。
- `POST` / `PATCH` / `DELETE` 保持现有语义，授权字段改为 `root_ids`。
- 创建普通用户须至少一个 `root_ids`；引用不存在的 root id → 422。

### 身份与配置

- `GET /api/clawmate/auth/me` 增加 `roots: [{id, label, agent_id}]` 可见摘要。
- `GET /api/clawmate/config` 的 roots 返回**真实** `label` 与 `agent_id`，不再硬编码 `"default"`。
- `GET /api/clawmate/auth/status` 保持现状——前端身份探针依赖它，且它位于中间件白名单（`auth.py:267`），强制改密期间仍可用。

### 错误契约

422 校验失败或引用冲突；403 未授权；404 不存在；401 未认证。设置路由要求管理员身份，且在首次改密完成前不可使用。

## 设置界面

设置弹窗内拆为两个 tab，顺序按工作流：**先登记 Rootdir，再给用户授权**。复用既有 `.modal-overlay` / `.modal-box` token 与「更多」菜单入口，不引入侧边推挤面板。

### Tab 1 · Rootdir 管理

列表显示 `label`、`dir`、`agent_id` 与「编辑」「删除」；底部「添加 Rootdir」。添加/编辑表单字段为 `id`（编辑时只读）、显示名、目录（带「浏览…」）、Agent。

**目录选择器**（懒加载逐层下钻）：显示当前路径面包屑、「上一级」、当前层的子目录列表、「显示隐藏目录」开关，以及「选为 Rootdir 目录」。关键交互点是**选择动作作用于当前路径**，不必先钻进目标目录；隐藏目录开关只作用于当前层过滤。

### Tab 2 · 用户管理

用户列表显示用户名与获授 root 的 `label`（非路径），带「编辑」「删除」。创建表单为用户名、初始密码，以及**注册表复选框列表**作为授权控件——取代原先含 1.8 万个路径项的 `<select multiple>`。

### 行为保持

强制改密弹窗仍不可关闭（禁用 Escape 与遮罩关闭）；普通用户不接收也不渲染 `btnSettings`；接口响应不返回任何密码哈希。`settingsError` 区域承担 422/403 文案，包括「该 Rootdir 正被用户引用，无法删除」与「目录已被其它 Rootdir 占用」。

编辑 root 修改 `dir` 保存前，明确提示「已引用该 Rootdir 的 N 位用户授权不受影响」——该行为与直觉相反。

## 测试与验收

**回归测试优先**。新增 `tests/test_root_authorization_regression.py`，先复现缺陷再修：

1. 用户被删除后其残留会话访问 `/api/clawmate/config` 与 `list?root=<旧root>` 必须 401，且不得返回任何 `system_root_dir` 之外的目录。
2. 授权目录被移除后，管理员与普通用户仍能登录（当前 500 锁死）。

**补齐原计划点名却从未创建的文件**：

- `tests/test_auth_users.py` — 默认管理员强制改密限制与改密解锁。
- `tests/test_user_root_authorization.py` — 伪造 root 403、失效会话 401、`local-admin` 主体可见范围。

**新增单元测试**：

- `tests/test_root_registry.py` — CRUD 与原子写；`id` 唯一化与不可变；`dir` 越界（绝对路径 / `..` / 符号链接逃逸 / 根自身 / `.`）拒绝；`dir` 重复拒绝；删除被引用拒绝；失效 `dir` 时 `resolve` 拒绝但 store 读取不抛。
- `tests/test_root_migration.py` — 绝对路径转相对注册表（保留 id/label/agent）；授权路径反查为 `root_ids`；不可收纳则报错退出；`.bak` 生成；幂等。

**路由与前端契约**：

- 扩展 `tests/test_settings_routes.py` — root CRUD、`browse` 越界 403、引用冲突 422、单层截断。
- 扩展 `tests/test_settings_frontend_contract.py` — 两个 tab、注册表复选框（不再有路径枚举的 `<select multiple>`）、`browse` 调用、隐藏目录开关。
- 补齐 `tests/test_e2e_browser.py` — 切换隐藏目录开关、选目录建 root、建用户勾授权、普通用户只看到获授 root、首次管理员改密流程。使用含 `projects`/`private`/`.hidden-dir` 的临时 system root，不依赖真实 home 目录。

**性能门槛**：`browse` 断言响应目录项数不超过单层上限，且请求不触及更深层级，防止退化为全量 `rglob`。

**基线**：当前 `379 passed`（`PYTHONPATH=. dev/.venv/bin/python -m pytest tests/ -q`），全部须保持通过。
