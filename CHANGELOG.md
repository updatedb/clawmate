# Changelog

## v1.57 (2026-09-14)
### `project/convert` 初始化治理骨架 `project-harness/`（新增）
- **背景**：项目治理标准要求每个项目带一份公开、版本化的 `project-harness/` 契约，但 `project/convert` 此前只铺 `.clawmate/` marker 与核心文档，从不创建治理骨架；「新建项目」与「引入治理契约」是脱节的两步，模板 `project-template/` 靠人工手动 `cp`。
- **新增配置键 `project.harness_template_dir`**：指向治理仓库的 `project-template/`（即 `project-harness/` 的父目录）。与既有 `project` 段同构解析：缺段/缺键逐键回退 `ProjectConfig` 默认值，未配置时为空串。
- **新增 `_scaffold_governance()`**：convert 时（1）幂等补齐 `.clawmate/` 运行子目录（仅 state/tasks/evidence/audit，见下节目录收敛）；（2）从模板按「**绝不覆盖**」语义复制 `project-harness/` 及 `docs/reports/`。模板缺失、为空或已存在骨架都**不是错误**——转换照常成功，由响应 `governance.skipped_reason` 说明原因，交由引导流程补齐。
- **响应新增 `governance` 字段**：报告 `template` / `project_harness` / `seeded` / `runtime_dirs` / `skipped_reason`，使调用方（skill）能判断骨架是否就位，而不是靠猜。
- **`skills/clawmate/SKILL.md` 的 Phase I 重写并整合**：convert 现在是项目初始化的**唯一入口**（步骤 2），
  `.clawmate/`、基础文档、`git init`、`project-harness/` 骨架一次完成。原「步骤 1」不再预建 `.clawmate/`
  ——否则 convert 判定「已是项目」返回 409，照旧文档走会把自身卡死；原「步骤 3：初始化 Git」降级为
  「步骤 5：通常无需手工执行」，只用于对已存在项目补做。步骤重编号为 0–5。
- **缺内容必须澄清**：skill 与网页端「转换为项目」都读响应 `governance` 字段；骨架未铺时
  弹窗/输出明确告知原因（未配置模板 / 模板缺失 / 已存在 / HTTP 409），不再静默略过。
- **角色定义不随项目复制**：明确项目只**引用**角色（`roles.yaml`），不复制不修改；建项目是
  项目创建者（人类）的专属行为。
- **`skills/clawmate/_meta.json`**：版本 2.7.2 → 2.8.0，`clawmate init` 描述补充治理骨架。
- **`config.example.json`** 补充 `project.harness_template_dir` 示例值。

### 目录收敛：只保留有消费者的目录
- **`.clawmate/` 运行子目录 9 → 4**：原先铺 state/tasks/runs/logs/evidence/audit/decisions/schemas/reports，逐个追消费方后确认只有 4 个需要预建——state/tasks/evidence/audit 是 `project-harness/roles.yaml` 路径契约（Gateway sandbox bind）的锚点。其余全部由各自消费方**懒创建**：`sessions/`（`SessionLogger.__init__` 的 `mkdir(parents=True, exist_ok=True)`）、`cache/text/`（search_service）、`generated-tasks/`（generated_assets）；`runs`/`logs`/`decisions`/`schemas` 在 ClawMate 代码与治理可执行物中**零消费者**。
- **不再播种 `.clawmate/reports/`**：这是治理侧明确拒绝的 legacy 路径（`scripts/test-deliver-report.sh` 断言它必须被拒），正式报告属于 `docs/reports/`。之前把它预建出来等于播种一个被否决的目录。
- **模板复制改为白名单** `_TEMPLATE_INCLUDE = (project-harness, docs)`，取代整棵 `rglob` 复制。模板里的空目录（`decisions/`、`reports/`、`schemas/`）与治理仓库自用的 `.clawmate/README.md`（含相对治理仓的链接）因此不会再泄进新项目。

### convert 结果校验（新增 `_validate_project`）
- **取代原先的 `created` 布尔组**（4 个 `exists()`，无任何消费方）。现在返回 `validation`：`{ok, checks, issues, pending}`。
- **`issues`（结构性，决定 `ok`）**：marker / 基础文档 / harness 四文件 / git 仓库 / 运行目录缺失。
- **`pending`（预期待办，不影响 `ok`）**：harness 仍是占位符（探测 `project-alpha` / `项目名称` / `明确本项目要达成的目标`）——刚 convert 完本就未填写，由引导流程接管，因此不能当成失败。
- **`_ensure_git_repo` 改为返回 bool**：原先 `git init` 失败会被静默吞掉，现在会进入 `validation.issues`。
- **skill 与网页端同时消费**：骨架未铺、校验未通过、待填写项三类都会明确告知，不再静默。

### 目录文档去重（SKILL.md）
- **4 份近乎重复的目录树合并为 1 份权威结构**（原先「观点收集 / 产品方案 / 研发需求」各一份 + 测试隔离规则后又一份），改为单棵树 + 一张「按项目类型启用」对应表；并修正树形连接符错误。
- **AGENTS.md 模板重写**：原先把 `feedback.audit.jsonl / sessions / cache` 列为运行态（这些并不由 convert 创建），现改为治理锚点四目录 + 明确 `dev/`↔`src/`、`test/`↔`tests/` 的命名对应，并注明 `sessions/`、`cache/` 按需创建、报告与证据路径不混用。

### 目录命名统一：`dev/`+`test/` → `src/`+`tests/`
- **问题**：两套标准在打架。`project-harness/roles.yaml`（随每个新项目播种）的 Gateway sandbox bind 授权的是 `src/**`、`tests/**`；而 skill 与现有项目用的是 `dev/`、`test/`。结果是 sandbox 授权了一个**项目里并不存在的目录**，而实际存在且被写入的 `dev/**` 根本不在授权范围内——正是本项目一直在清理的那类「看起来生效、实际没有」的配置。
- **决定**：统一为 `src/` + `tests/`（治理契约是权威且被实际强制；非代码类项目用 `src/` 语义也比 `dev/` 更准）。已更新 `skills/clawmate/SKILL.md`（含「统一使用 `src/`」约定、CLAWLIST 汇总链接、测试目录隔离规则表）与 `_AGENTS_TEMPLATE` / `_CLAWLIST_TEMPLATE`。
- **现有项目不强制迁移**（保留旧名仍可工作）；新项目与文档一律用 `src/` + `tests/`。
- 需注意的陷阱：ClawMate 仓库**自身**的源码目录就叫 `dev/`、测试叫 `tests/`，因此修改时只改「项目目录约定」文本，绝不能误改仓库真实路径（已校验 `/dev/null` 等未被误伤）。

### `collect/` 并入 `research/`
- **依据**：`collect/` 是纯约定目录，在 ClawMate 与治理可执行物中**零代码消费者**，职责（存放收集的素材与来源材料）与 `research/` 完全重叠。实测仅 RAS 有内容（12 项），content-studio 为空目录。
- **标准侧**：`skills/clawmate/SKILL.md` 的类型表、`mkdir` 目录树、目录权威树与启用表均去除 `collect/`；`research/` 说明改为「研究计划/进度 + 收集的素材与来源材料」。
- **顺手修掉上一轮的验证漏洞**：`mkdir` 行用的是花括号展开 `{research,collect,prd,dev,test}`——里面没有斜杠，所以逃过了我上一轮 `dev/\|test/` 正则，旧目录名其实仍在生成。现已改为 `{research,prd,src,tests}`。
- **存量项目迁移**（磁盘层，未动 git index）：RAS 的 12 项内容 `mv` 到 `research/` 并改写 10 处交叉引用（`prd/` 追溯矩阵与需求列表、`harness/examples/ras-v1-definition.json`、`PROJECT_NOTE.md`、`CLAWLIST.md`、`scripts/relativize_preview_links.py` 默认目录列表）；content-studio 删除空目录并更新目录树；carpad / marketresearch 的旧版 `AGENTS.md` 按新模板重新生成。
- 刻意**保留**的两处 `collect`：content-studio `PROJECT_NOTE.md` 决策日志行（记录当时事实，改它等于篡改历史）、`dev/project_routes.py` 的 `_LLM_KINDS` 任务关键字（是任务语义，不是目录名）。

### 测试
- 新增 `tests/test_agents_template_dirs.py`：锁定 AGENTS 模板只描述真实存在的目录、不重新引入 legacy `.clawmate/reports`、**只**用 `src/`/`tests/`、且不再提供 `collect/`（`_AGENTS_TEMPLATE` 与 `_CLAWLIST_TEMPLATE` 双向断言）。
- `tests/test_project_harness_scaffold.py` 重写：锁定运行目录集收敛、legacy 与懒创建目录**绝不**被播种、模板白名单不外溢、以及校验的 issue/pending 区分。
- 全量测试：`580 passed, 46 deselected`；`test_preview_refresh.py` 的 1 个失败在 `git archive HEAD` 隔离树上同样复现（工作区既有问题，与本次改动无关，未触碰 `dev/static/js/preview.js`）。

## v1.56 (2026-09-14)
### 关停阻塞修复（重启需 90 秒强杀）
- **根因**：入口调用 `uvicorn.run()` 时未传 `timeout_graceful_shutdown`，其默认值为 `None`，即**无限等待**连接与后台任务排空。而本服务必然同时持有两者：面板存续期间一直打开的 WebSocket 代理（OpenClaw 聊天、terminal v2），以及永不自行结束的 `_idle_reaper` 后台循环。于是进程卡在 `deactivating`，直到服务管理器在 `TimeoutStopUSec` 到期后 `SIGKILL`——实测 90 秒，日志为 `Main process exited, code=killed, status=9/KILL`。
- **修复**：显式设定有界预算 `timeout_graceful_shutdown`（默认 15 秒，可用 `CLAWMATE_GRACEFUL_SHUTDOWN_SECONDS` 覆盖，非数字回退默认值）。到期由 uvicorn 主动取消残留任务后正常退出。
- **实测**：重启耗时 15.1 秒，日志 `Cancel 1 running task(s), timeout graceful shutdown exceeded` 后 `Stopped`，**不再出现 SIGKILL**。systemd 单元同步显式声明 `TimeoutStopSec=30`。
- 该预算必须显著小于服务管理器自身的强杀超时，否则进程会在 uvicorn 完成取消前先被杀掉。

### Agent 聊天气泡未占满面板、右侧留白
- **根因**：`.agent-chat-assistant` 声明 `align-self: flex-start`，覆盖了 flex 纵向容器默认的 `stretch`，使气泡按文字内容收缩，再由 `max-width: 90%` 封顶——右侧那片空白是「收缩后宽度」与「可用宽度」之差，而非留白设计。这也是为什么同一容器里的 `.agent-chat-input-wrap`（无 `max-width`、无 `align-self`）看起来正常。实测 680px 面板下内容盒 651px、助手气泡 585.9px，右侧固定损失约 65px。
- **修复**：助手气泡改 `align-self: stretch` 并满宽（`max-width: 100%`）；用户气泡保留 90% 上限并右对齐，维持「谁说的」视觉区分。移动端仅继续限制用户气泡。
- **同时修复样式缺失**：提交 `ee808c0` 的大范围清理**误删了仍在使用的 `.agent-chat-user` 与 `.agent-chat-error`**（同一提交还删掉了 `.card-actions-left/right`）。前端仍输出这两个类名，因此用户消息与错误消息完全没有气泡样式——背景透明、无主题色、无危险色，浅色主题下几乎不可见。已恢复两条规则。

### 清理死配置键 `agent.openclaw_ws_url`
- 该键**无任何消费者**：`/api/clawmate/config` 返回的同名值由 `routes._openclaw_ws_url()` 按请求 host 与 `public_base_url` 动态计算，从不读此字段。全树追踪确认 `dev/` 无读取方、无测试依赖、无属性访问，且 `AgentConfig` 构造为纯关键字形式，删除不会造成位置参数错位。
- 保留它是个陷阱：改它看起来像修好了，实际生效值来自别处。已从 `dev/config.py`、`config.example.json` 及本机 `config.json` 移除；旧配置残留该键不会报错（解析忽略未知字段）。

### 文档：`auth.local_hosts` 的权限边界
- 该配置授予的是**完整管理员权限**而非仅文件访问：命中本机绕过的客户端被绑定为 `is_admin=true` 的 `local-admin`，设置类接口（账户列表 / 增删用户 / 改授权）同样开放。README 已显式警示，并说明它与 `_is_local_network_host()`（仅影响 WS 地址计算，不参与认证决策）是两件不同的事。
- 本机 `config.json` 原有 `local_hosts: ["openclaw.lan"]`（解析到 192.168.254.130，**另一台机器**），近 7 天该来源请求数为 0，已改为 `[]`（只保留硬编码回环绕过）。

### 修复 `project` 配置段被静默忽略（真 bug）
- **根因**：`AppConfig.project` 声明为 `field(default_factory=ProjectConfig)`，但 `_parse_config()` 的返回里**从不传 `project=`**。于是无论 `config.json` 写什么，运行时永远拿 dataclass 默认值 `updatedb@qq.com` / `OpenClaw`。消费方是真实存在的：`dev/project_routes.py` 的 `_git_identity()` 读取 `cfg.project.git_user_email` / `cfg.project.git_user_name` 来签署项目提交。本机 `config.json` 的值恰与默认值相同，所以没有可见差异——这正是它危险的地方：改配置看起来生效了，实际没有。
- **修复**：新增 `_parse_project_config()`（与既有 `_parse_search_config()` 同构：缺段/缺键逐键回退默认值），并在 `_parse_config()` 中传 `project=`。

### 清理死配置键 `search.ai_summary` 与 `agent.terminal_v2`
- **`search.ai_summary`**：`SearchConfig` 只声明 `content` 字段，`_parse_search_config()` 只读 `raw["content"]`；全树确认 `dev/` 下无任何消费者。该功能此前已被移除（`search_routes` 至今显式 `result.pop("summary", None)`），但 `config.json` 里仍认真配着 `enabled` / `timeout_seconds` / `max_input_files` / `max_snippets_per_file` 四个参数。**决定：删除该配置块**，不再假装生效；若日后要恢复 AI 摘要，应按新功能重新设计而非沿用这段无消费者的键。
- **`agent.terminal_v2`**：`dev/config.py` 从未解析该键。protocol v2 端点 **无条件注册**（`agent_routes.py` 的 `@router.websocket("/api/clawmate/agent/terminal/v2")`，随 `agent_router` 始终挂载），`_terminal_v2_manager` 等只是内部变量名，与配置字段无关——这个开关从来关不掉任何东西。**决定：删除该配置键**。灰度期的回退说明只存在于历史 spec/plan 文档中，本仓库 README 与 CHANGELOG 均未承诺该开关。
- 两键均已从本机 `config.json` 移除（移除前已生成 `config.json.bak-*` 时间戳备份）；`config.example.json` 本就不含这两键。旧配置残留该键不会报错——解析忽略未知字段。

### 测试
- 新增 `tests/test_graceful_shutdown_budget.py`：锁定有界预算、环境变量覆盖与安全回退，并断言预算必须小于服务管理器强杀超时。
- 新增 `tests/test_dead_openclaw_ws_url_key.py`：锁定死键已移除、旧配置兼容，且 `/config` 仍输出动态计算的 `openclaw_ws_url`。
- 新增 `tests/test_config_project_section.py`：锁定 `config.json` 的非默认 project 值能传到 `cfg.project`，缺失/部分配置逐键回退默认值，`project_routes._git_identity()` 消费到解析值（而非 dataclass 默认值），且本机 `config.json` 的 project 段与解析结果一致。
- 新增 `tests/test_dead_config_keys.py`：锁定两个死键已移除、旧配置兼容，且 v2 终端 WebSocket 确实无条件注册。
- 全量测试：`563 passed, 46 deselected`。

## v1.55 (2026-09-11)
### 设置面板改版
- 模态拆成**列表视图**与**聚焦表单**：列表独占高度、整行可点，表单按需唤出。此前两者共用一个单列滚动，导致「读要滚过一张空表单」「编辑时看不见自己在改哪行」。
- 两个 tab 共用同一套行结构（此前 `.settings-root` 无分隔线、`.settings-user` 有）。
- 字段有了**可见标签**，不再靠占位符充当标签；密码字段的说明改为持久文字。
- 权限勾选区改为**两列网格**，勾选框恢复自然尺寸（此前被 `.settings-form input { width: 100% }` 拉伸到 308×30，标签被挤到第二行）。
- 删除改为**危险区原位两步确认**，不再走 `window.confirm`；破坏性操作与保存动作物理分离。
- 深色模式下自动填充不再覆盖主题底色；行内按钮归入 `.btn` 家族，删除呈危险态（新增通用的 `.btn.danger`）。

### 面板布局修复（窄屏）
- **历史会话 header**：三列网格 `minmax(0, 1fr) auto minmax(0, 1fr)` 在手机宽度下把两侧轨道压到 ~0，而中列无法低于 108px 筛选框的 min-content，标题又被 `justify-self: start` 按 max-content 定尺寸——于是横穿到中列。实测 375px 时标题被搜索框盖住 70%、320px 时控件压入标题 58px（344px 起关闭按钮也开始压住筛选框）。改为 `max-content minmax(0, 1fr) max-content`，控件保持内容宽度（`auto` 轨道会瓜分剩余空间，把桌面搜索框从 193px 撑到 237px）；标题省略号移到生效的内层元素上（`text-overflow` 对 flex 容器无效）。详情页 header 同一根因，≤320px 的返回按钮压住标题一并修复。
- **日期轴**：按钮数量在渲染时按固定 58px/按钮 估算且不随窗口重算（实测最宽按钮 66.5px），窗口变窄后两端日期被裁——380px 溢出 20px、320px 溢出 50px；容器 `overflow: hidden` + `justify-content: center` 居中裁两端且无法滚到。改为可横向滚动（滚动条隐藏，避免改变栏高）+ `safe center`。
- **高度对齐**：日期轴与 `.agent-toolbar` 实测 35/39（桌面）、38/41（移动），与注释声明的「34 / 38 互相镜像」不符——两者 `min-height` 相同但控件高度不同（30 vs 26），而 `min-height` 只是下限。toolbar 按钮降到 `--btn-h-sm` 后两栏一致。
- **统一响应式档位**：mobile ≤768 / tablet 769–1240 / desktop ≥1241，只有这一条阶梯。此前散着一个 **1500px** 阈值（`body.agent-open .sidebar` 与两处 JS 判断），它横切 tablet/desktop 边界，在两者根本不争列的 tablet 档把 Dir 侧栏藏掉。该规则已删除，`body.agent-open .sidebar` 不再存在。
- **Dir 面板与右侧面板不再互斥**：展开 Dir 面板曾无条件关闭项目面板与 Agent 面板；打开 Agent 面板也曾关闭 Dir 面板（1500px 以下）。现在 **769px 以上两个方向都不再关闭对方**——>1240 它们是并排的独立列，769–1240 它们是浮层抽屉、不占列。仅 mobile 档（≤768，全屏浮层）保持互斥。
- **768px 边界对齐**：CSS 一直用 `max-width: 768px` 定义 mobile，但 JS 用 `< 768`（把 768 当桌面）、preview.js 用 `<= 768`——同一宽度两套解释。现统一为 **768 属于 mobile**（`<= 768` / `> 768`），app.js 8 处、preview.js 14 处、terminal bundle 1 处。
- preview 页大纲的同类抑制（`<= 1500` 时只要右侧面板打开就隐藏）一并按同一模型收敛为**仅 mobile** 生效。

### 归档预览修复
- **归档树渲染成阶梯状**：展开归档后同层条目落在不同 x（实测 62 项 `.tar.gz`：depth 1 在 585，depth 2/3 在 712–933，且 depth 3 出现在 depth 2 左侧），缩进不带任何信息。JS 的缩进逻辑本就正确（`padding-left = depth * 20 + 12`），缺陷在 CSS：`.archive-entry` 是 nowrap flex 行、`.archive-name { flex: 1 }` 吃掉剩余空间，而子树容器是同一行的**兄弟**而非其下的元素——每层因此向右开新列，偏移量取决于该分支吸收了多宽。改为换行 + 子树满宽 basis，恢复一层一个 x（52 / 84 / 136 / 208）。所有归档格式共用。
- **目录名可直接展开**：归档树的目录名本身成为点击目标（`role="button"`、`tabindex`、Enter/Space），并同步 `aria-expanded`；此前只能点前面的小三角。

### 权限边界
- 管理员账号不再参与内容工作：agent 终端、项目面板、反馈面板对其不可见且不可达。闸口位于 `AuthMiddleware.dispatch()` 的会话分支内、按四个 API 前缀拒绝；两条 agent WebSocket 因不经中间件而在握手处单独拒绝（关闭码 4403）。loopback 与内部 token 调用方在更早的分支返回，因此本机操作者与执行器回调（`/review/result`）不受影响——这也让闸口无需豁免表。
- 前端隐藏三个顶栏入口（手机端 more-menu 镜像自动跟随），并抑制项目面板的首次访问自动展开。
- 管理员保留系统设置与文件浏览、预览、下载、上传能力。管理员始终可见系统根目录：`service.get_roots()` 无条件把 `ROOT_ID_SYSTEM` 交给管理员，`root_ids` 对管理员不参与解析（`user_store` 创建/更新时即置空）。

## v1.54 (2026-09-11)
### 多用户 Rootdir 与授权（核心）
- **Root 注册表**：根目录从 `config.json` 的 `roots` 数组迁出，落到私有 `roots.json`，条目为 `{id, label, dir, agent_id}`，`dir` 相对 `system_root_dir`。四个字段读取时**全部必填**——缺失或空白即拒绝加载，不再用 `label→id`、`dir→""`、`agent_id→"default"` 兜底（后者还会把显式 JSON `null` 强制成字符串 `"None"`）。新增 `dev/root_registry.py`。
- **用户授权按 id 引用**：`users.json` 用 `root_ids` 引用注册表 id，不再存路径；读取授权时不再重新校验（原实现下一个失效目录会连累所有登录）。新增 `dev/user_store.py`。
- **启动迁移**：新增 `dev/root_migration.py`，把旧 `roots` 一次性写入 `roots.json`（`dir` 改写为相对路径），旧账号的 `root_dirs` 改写为对应的 `root_ids`；改写 `users.json` 前先写出 `users.json.bak`。无法收纳于 `system_root_dir` 的路径、非法 `agent_id`、两个 root 共用同一目录，都会中止启动并打印问题路径。
- **授权 fail-closed**：新增 `dev/root_auth.py` 作为唯一鉴权闸口；`RootNotAuthorized` 经统一异常处理器映射为 **403**——此前 `except ValueError` 捕不到新异常，优雅降级路径会退化成 500。
- **客户端 IP 信任修复**：`get_client_ip` 不再无条件信任 `x-forwarded-for`。原实现下远端可自称 loopback 从而继承管理员身份（实测：未认证创建用户返回 201）。

### 无人值守路径与分享
- **未认证工作补 principal**：新增 `auth.request_user_scope()`；cron、启动孤儿恢复、会话 TTL 回收、会话历史改走 `service.registered_roots()`——注册后 legacy `cfg.roots` 为空，原扫描等于空转。
- **唤醒失败归还预留**：唤醒发不出去时调用 `store.release_execution_task()`，条目退回 `approved` 可重跑，不再永久卡在 `in_progress`（即 FD-CM-0185）。
- **读路径与分享路由**：preview / download / raw 回到普通会话路由；`/share/` 按能力拆分——铸造、列表、失效需会话，`/{token}/...` 保持匿名（token 即能力）。顺带堵住三个洞：`/active` 不再向匿名调用者返回全部共享清单、`/expire` 补授权校验、`share_asset` 改为相对共享文件自身目录解析（原来按 basename 比较，一处提到 `README.md` 会暴露该 root 下所有 `README.md`）。
- **分享接收方 principal** 绑定覆盖整个 handler（原来只包住 `safe_path()`），分享链接的反馈提交不再 403。

### 设置界面与目录选择器
- 设置模态拆成 **Rootdir** / **用户** 两个 tab；用户授权改为注册表复选框，前端全程发送 `root_ids`（表单原来读 `root_dirs`，渲染即抛错、保存 422）。
- 用户「编辑」改为就地填充表单（提交走 PATCH），取代原来的三个 `window.prompt`；空密码表示保持原密码。新增「取消编辑」。
- 设置入口同时是顶栏控件与 more-menu 镜像；补 `[hidden]` 规则——`.topbar-btn` / `.more-item` 的 `display: flex` 原来压过 UA 的 `[hidden]`，普通用户仍能看到并点开设置齿轮（内部请求全部 403）。
- 共享目录选择器新增**隐藏目录开关**；picker 抬到设置模态之上（两者同为 z-index 10000 的兄弟节点，DOM 顺序让设置盖住 picker 并吞掉点击）。

### 移动端顶栏折叠契约
- CSS-only 折叠 + more-menu 镜像补齐：preview 页找回 **Agent 终端**与**反馈面板**入口；`btnToggleRight` 更名 `btnToggleFeedback`（它打开的是反馈面板，与"第几个"无关）。
- `test_topbar_more_menu` 改为从页面自身 `topbar-actions` 推导期望集，并与镜像、折叠规则一起断言，不再只取 CSS 与页面恰好都出现的 id。

### 批量操作栏
- bar 归属**多选模式**而非选中结果：toggle 打开即出现，且只有 toggle 能关闭；清空选中不关闭栏，三个文件操作按钮置灰。
- 按钮改用 token（`--btn-h` 30px / `--btn-font` 12px / `--font-ui`；原为硬编码，实测 36.5px 高且落在 Arial）；批量删除启用一直未被应用的 `.danger` 样式。
- 修正移动端规则的源顺序——原来写在基础规则之前被整体覆盖，手机上是 143px 两行栏 → 68px 单行；fixed 栏通过 `--batch-bar-h` 预留底部空间，最后一行卡片不再被永久遮住。

### 修复
- Service Worker 不再把 SSE 等流式响应写入缓存，缓存写入失败也不再让已成功的请求变成未处理的拒绝；`CACHE_VERSION` 提升以丢弃旧 app-shell 缓存。
- 移动端（≤480px）反馈卡片头部不再溢出：id 让位给右侧 chrome。原预留 `calc(100% - 132px)` 少算了 3 个间隙（实需 143px），时间戳被截断、状态标签折行。
- 项目面板关闭前把焦点交还 toggle，避免焦点留在 `aria-hidden` 子树；toggle 已折叠进 more-menu 时则直接丢弃焦点。
- 面包屑复制绝对路径不再粘贴 `undefined`：`/api/clawmate/config` 与 `/auth/me` 恢复携带 `dir` 字段。

### 测试与文档
- 浏览器验收（`-m e2e`）恢复可跑：起临时实例（临时 system root、预置 `users.json`、随机端口、就绪轮询、自动清理）并驱动真实 Chromium 以**远程客户端**身份访问，覆盖 root CRUD 与「已被 N 位用户引用」提示、授权 422、picker 三条关闭路径、隐藏目录开关、设置入口对普通用户的可见性。19 项浏览器检查通过、无跳过。
- 三个失效 smoke 测试修复：`test_search` 引用已删除的 `.cp-item` 标记；`test_file_preview` 等待 `networkidle`——常开的 EventSource 使其**必然超时**，其后的面板断言从未执行过；面板断言本身与实测不符（.txt 预览两个侧栏都隐藏）。
- 新增 spec/plan：`docs/superpowers/specs|plans/2026-09-10-{multi-user-rootdir,rootdir-registry}-*.md`。
- README 重述 Rootdir 注册表模型与隐藏目录开关；标语按 FD-CM-0185 改为五项能力。`.gitignore` 忽略 `roots.json` 与 `users.json.bak`（后者含同样的密码哈希）。

## v1.53 (2026-09-10)
### 命令面板项目化（index，Ctrl/Cmd+K）
- 项目优先：默认只显示**项目卡片**（平铺，不按 root 分组），按**最近使用**降序（localStorage 记录优先、项目目录 `mtime` 兜底）。
- 输入即按名称过滤；点卡片跳转项目并记录 MRU、关闭面板。
- "文件搜索 / 内容搜索"作为输入框下**固定 chip 行**；点击执行搜索、关闭面板、结果在 index 展示。
- MRU 共享：`recordProjectUse`/`projectUseAt`（`clawmate.recentProjects`），面板打开与跳转均记录。
- 契约测试 `tests/test_command_palette_contract.py`（5 例）。

### 面板与顶栏统一（token 化）
- 面板头统一为 **48px / padding 0 12px / 普通标题（13px/600/text-primary）**；preview 大纲/反馈头去掉大写 label 风格；image-assets 头 40→48；agent 头 padding 14→12。
- 面板/顶栏按钮高度归入 **34/30/26** 三档 token（`--btn-h-lg/h/sm`），**清除 28px 离群值**：面包屑 copy/refresh→34、移动端 toolbar/preview 按钮→30、≤480 sort-pill 保持 26。
- 所有关闭按钮统一为 `.panel-close-btn` + 14px SVG ✕（image-assets 曾用文本"✕"）。
- 面板正文 padding 统一 `8px 12px`（project/大纲/反馈/image-assets）；内容驱动的 preview-right(flex) 与 agent 终端（满出血）保留例外。
- 顶栏：logo 26px（CSS 单一来源）· rootSelect 34px · 内部 gap 16→8，左边缘 padding 20 保留；面包屑 copy/refresh 按钮与文本垂直居中（`vertical-align: middle`）。
- 移动端 index/preview 顶栏动作折叠进 **more-menu**（⋯），菜单项随功能可用性动态显示（如非项目目录不显示"项目面板"）。

### 修复
- 移动端 project panel 不再遮挡 topbar（`z-index 30→8`，`padding-top:48px`，与 agent 面板一致）。
- Agent 面板 backend 选择器宽度 84→108（避免"OpenClaw"被截断），preview 选择器统一；历史面板（mobile/tablet）header 不再被顶栏遮挡（overlay `top:48px`）。

### 约定与文档
- AGENTS.md 新增「Frontend Naming & CSS Conventions」（ID：`btn<Action><Object>`/`<Area>Panel/List/Select...`；CSS：kebab + 面前缀 + BEM-lite；尺寸走 token）。存量代码不整体迁移，作为**以后统一标准**。
- AGENTS.md 面板头契约更新为"48px + 普通标题"。
- 新增设计 spec/plan：`docs/superpowers/specs|plans/2026-09-09-command-palette-projects-{design|implementation}.md`。

## v1.52 (2026-09-06)
### 目录自动监听刷新 + 会话级变更标记
- **后端（watchdog/inotify，事件驱动）**：新增 `dev/fs_watch.py` 文件监听服务，按客户端订阅的 `root+dir` 用 watchdog（Linux 底层 inotify）**非递归**监听「当前打开的目录」本身（1 个 inotify watch，与目录条目数量无关，不逐文件扫描）；引用计数（无客户端即停）、快速连续事件 debounce（0.4s，落在 300-500ms）；正常运行时**零轮询**，仅事件驱动。新增依赖 `watchdog`。
- **大目录/溢出兜底**：单个 debounce 窗口观察到大量不同路径（疑似 inotify 事件队列溢出，watchdog 对 `IN_Q_OVERFLOW`/wd==-1 静默丢弃，见 `inotify_c.py`）时，合并为一次 `refresh` 事件，让前端做一次完整重列（仅异常时扫描，平时零轮询）。
- **后端（SSE）**：新增 `dev/fs_routes.py` 端点 `GET /api/clawmate/fs/events?root=&dir=`，`text/event-stream` 推送 `{type:"change", path:<相对root路径>, kind:"added"|"modified"|"deleted"}`；沿用现有 AuthMiddleware 鉴权（会话 cookie），局域网/本机自动放行；断开自动退订。
- **前端（app.js）**：`loadDir` 打开目录后建立当前目录的 SSE 连接，切目录关闭旧连接/开新连接，离开/关闭页面关闭；维护页面会话级 `recentChanges`（path→kind），收到变更即 `debounce`（400ms）刷新当前目录（绕过该目录 30s 缓存）；仅当事件目录与当前查看目录一致才刷新，避免串目录。
- **前端标记**：列表行与画廊卡片对「本次页面打开期间」新增/修改的条目加 `新增`/`已修改` tag（`.recent-change-badge`）并高亮 mtime（`.mtime-changed`）；删除只刷新不标记。标记仅存于 JS 内存，刷新页面或切换目录后消失（会话级、不追溯历史）。
- **测试**：新增 `tests/test_fs_watch.py` — 监听服务新增/修改/删除事件与路由校验（422/503）。
- **修复（手动刷新不清标记）**：面包屑「刷新当前目录」按钮此前只清目录缓存，未清页面会话级 `_recentChanges`，导致刷新后 `新增`/`已修改` tag 残留（仅 F5 或切目录才清除）。现于该按钮 click 处理中、重新加载目录前执行 `_recentChanges = {}`，将手动刷新视为「干净视图」；SSE 自动刷新链（`_scheduleFsRefresh`/`loadDir` 内部/`_connectFsWatch` 收 change）不清，保 tag 功能不失效。

### 修复（点击打开文件清除标记）
- **前端（app.js `openEntryPreview`）**：会话级「新增/已修改」标记此前只能靠 F5/切目录/手动刷新清除，点击文件打开预览后该文件标记仍残留。现于打开预览前，对该文件**就地**清除标记：从 `_recentChanges` 删除该路径，并移除对应 `[data-path]` 节点上的 `.recent-change-badge` 与全部变更高亮 class（`.mtime-changed` / `.card.change-added` / `.card.change-modified`），覆盖画廊（grid）与列表（list）两种视图；只清被点击的这一条，其它条目标记保留，且不触发整列表重渲（不丢分页/滚动），SSE 自动刷新链与面包屑手动刷新清标记行为不变。

## v1.51 (2026-07-09)
### 分页阈值调整
- **主列表** grid 卡片模式分页：60 → **66** 条/页
- **主列表** list 模式分页：22 → **21** 条/页
- **Agent 会话历史**分页：15 → **20** 条/页
- **卡片徽标统一**：`card-match-badge` 大小/padding/margin 对齐 `.card-menu-btn`（22px 方形、padding 0、offset 6px）

### 搜索与内容匹配优化
- **搜索结果文案统一**：状态栏改为"综合匹配 X 项，显示 Y 项"，弹窗匹配数改为"内容匹配 X处/Y个文件"
- **列表徽标颜色修复**：`.list-match-badge` 亮色主题下文字颜色被覆盖
- **内容匹配弹窗居中**：Agent 面板打开时自动左移半个面板宽度，在剩余视口中视觉居中
- **行号可点击性提升**：accent 色 + 浅背景 + 下划线 hint

### 文件上下文去重（后端 + 前端）
- **后端**：`last_injected_file` → `known_files` Set，`_build_file_context_prompt` 输出简化（移除 `---` 包裹）
- **后端**：新增 `_normalize_known_file_path` / `_extract_known_file_path` 辅助函数，路径统一处理
- **后端**：`_input_batch` 批量队列移除，逐条记录 user turn；`SessionLogger.record_user()` 可选 `ts` 参数
- **前端**：`_knownFilesBySession` 去重机制 + typed-input 跟踪 + pending→session_key 作用域迁移

### 修复
- **WS 重连文件上下文保留**：重连时绕过 `hasKnownFile` 检查强制重新注入，服务端 `known_files` 同步清理
- **Transcript 收集路径修复**：on-demand transcript 使用 session 存储的 cwd（而非 project root）
- **"路径" → "位置"**：按钮重命名，点击改为跳转到文件所在目录（而非复制路径）

### 清理
- 移除 `.playwright-mcp/` 浏览器调试临时文件（22MB）
- 移除 `test/DeepSeek如何赋能职场应用？...pdf` 测试 fixture（9.6MB）
- 归档已完成 superpowers 计划/规格文档

## v1.50 (2026-07-07)
### 会话历史增强 — cwd 恢复、Transcript 路径匹配、文件上下文保留
- **cwd 恢复**：`_session_cwd_from_log_dir()` 从 index.json 或日志目录结构恢复 session cwd，`agent_session_log`/`agent_session_detail` 同步返回
- **Transcript 作用域限定**：`_find_codex_transcript()` 路径匹配改用 `expanduser().resolve()` 全路径比较 + `parents` 遍历，消除符号链接别名匹配错误
- **cwd 索引持久化**：session 创建时 `cwd` 字段写入 index.json，供后续恢复和 `_collect_transcript()` 使用
- **文件上下文保留**：Agent 关闭后重开自动恢复上次注入的文件上下文（`_lastFileContext`），WebSocket 重连不再用 `last_injected_file` 去重（每次重连重新注入）

### 代码预览行号重构（CSS Grid → 逐行 Flex）
- **布局重构**：`.code-with-lines` 从 CSS Grid 双列改为逐行 `.code-row` flex 布局，解决代码换行时行号错位
- **行号精准**：`.code-row-num` / `.code-row-text` 逐行独立，行高差异不影响对齐
- **标题滚动**：`&line=N` 源码模式改用 `.code-row` DOM 查找替代 `lineHeight` 算术运算，滚动精度 ±0px
- **Flash 高亮**：闪烁条使用 `row.offsetTop` 而非绝对位置计算，行号间无间隙

### "添加到会话" 桌面浮层
- **预览页浮层**：选中文本时显示 `#selAddToAgent` 浮动按钮（`→` 图标），点击将路径发送到 Agent 终端
- **画廊/列表菜单**：Agent 面板打开时，右键/⋮ 菜单显示"添加到会话"，列表行内显示终端图标按钮
- **API 暴露**：`Agent.sendText()` / `Agent.insertText()` 公开方法，PTY 模式下直接发送文本/插入输入缓冲区

### Agent 焦点修复
- 点击面板外非可聚焦元素不再抢回焦点（`_lastMousedownInPanel` 守卫），避免预览页选中文本被中断

### 测试
- 新增 `tests/test_agent_insert_and_file_context.py` — 文件上下文注入与保留
- 新增 `tests/test_preview_agent_panel_layout.py` — 预览面板布局
- 新增 `tests/test_preview_agent_selection.py` — 预览选中与浮层

## v1.49 (2026-07-05)
### Session History 增强 — 根级会话、输入批处理、跨 session 防护
- **根级会话支持**：无 project 标记的 session 存储在 root 自身 `.clawmate/sessions/`，TTL reaper 同步覆盖
- **输入批处理**：WebSocket → PTY 转发合并 1.5s idle 内的用户输入为单一 user turn（解决逐字符记录的噪音问题）
- **跨 session 污染防护**：transcript 解析按 `started_at` 过滤 60s 前内容，防止旧 assistant 消息错误关联到当前 session
- **Transcript 匹配优化**：Claude/Codex transcript 定位改用内容 timestamp 扫描替代 mtime 启发式算法
- **"分析文件" 记录**：前端分析文件 prompt 同步写入 `.chat.jsonl`，避免空会话被 API 过滤
- **计数修正**：`count_turns()` 仅统计 user role 条目，新增 JSON decode 错误兜底
- **会话数据规范化**：`_normalize_chat_turns()` 负责排序、合并连续 user turn、分配 turn_index
- **浏览器目录感知**：session API 新增 `dir` 参数，自动推断所属 project（无需手动切换目录）
- **提取辅助函数**：`_roots_for_session_query()`、`_projects_for_session_query()`、`_load_chat_turns()`、`_chat_log_stats()`
- **Session API 响应增强**：返回 `instruction_count`、`turn_count`、`total_turns`、`first_ts`、`last_ts` 统计字段
- **CSS/UI**：按钮 26×26 统一尺寸、flexbox 居中、border hover/active 态；浮层 header 改用 SVG 图标
- **测试**：新增 `tests/test_agent_history.py`

## v1.48 (2026-07-01)
### 分享功能增强
- index 卡片 ⋯ 菜单底部添加"生成分享链接 / 取消分享"（仅文件，目录不显示）
- 分享/取消成功同步更新状态栏（`setStatus`）+ `showToast`
- preview 页面分享按钮根据文件分享状态高亮（`active` class），点击 toggle 创建/取消分享
- 图片导航时自动刷新分享状态
- 删除 thumb 上独立的 `card-share-icon` 叠加图标（功能移至菜单）

### 后端新增 API
- `GET /api/clawmate/share/active` — 返回全部有效分享文件列表（按 root 分组）
- `POST /api/clawmate/share/expire` — 将指定文件分享标记为过期

## v1.45 (2026-06-27)
### Agent Panel 后端切换
- badge 点击循环切换后端 claude→codex→openclaw，前后端联动（WS 传递 backend 参数）
- header 精简 — 移除 agent-panel-root 标签，保留 badge + title
- Ctrl+L 清屏 → 改为 clear 按钮（本地 term.clear() + PTY 发送 \x0c）
- 面板最大宽度 +100px（默认 700→800，拖拽 800→900）

### Agent 渲染实验与回退
- ansi-up DOM 渲染器 + 按钮切换双模式（DOM/xterm）→ 回退到纯 xterm 方案
- xterm CSS transform:scale 适配面板宽度 → 回退，保留其他修复

### xterm.js 可靠性
- 多屏适配：实测字符宽度 + COLUMNS/LINES 环境变量 + 移除 reset
- 统一 index 与 preview 的 agent panel 宽度限制
- panelTitleEl 显示会话名 + drag 适配 DOM 模式 + null 守卫

### Mermaid 弹窗缩放
- 缩放控件增加弹窗查看按钮（expand dialog □）
- 弹窗内支持缩放/拖拽，内容居中
- 弹窗内鼠标滚轮直接缩放（不需 Ctrl）
- expand 按钮复用 iconSVG() 生成，改为纯文本 □

### Mobile 完善
- 移动端面板 z-index 调整为 overlay7 < panel8 < topbar10
- 目录/大纲条目点击后自动关闭侧边面板
- html,body 锁定视口 overflow:hidden（对齐 preview）
- bfcache 恢复时自动刷新 + CSS/JS 版本号更新

### PWA + 主题 + 图片导航
- PWA 支持（manifest + Service Worker）+ Agent 文件上下文注入 + 无限滚动
- 主题防闪烁（data-theme 在 <head> 同步设置）
- 自动模式图标从 sun 改为 sun-moon（与浅色模式区分）
- 图片导航按钮固定视口位置 + isImageMode 扩展支持全部图片格式

### Docs
- README 截图全部重新截取 + 精简为两张（文件管理/预览+反馈）
- SKILL.md 模板去重 + 章节编号修正 + 版本号 bump 至 2.7.2

## v1.47 (2026-06-29)
### Preview &line=N 滚动 + 搜索清除 + 内容匹配面板 + 源码高亮修复
- Preview: `&line=N` 渲染模式下不再强制切换源码视图，滚动到最近标题段落（`_scrollRenderedMarkdownToLine`）
- Preview: HTML 文件切换源码/编辑模式内容空白（`srcPre.style.display` 未同步 3 处）
- Preview: Markdown 源码模式高亮修复（`textContent` 和 `code` 元素重复导致裸文本覆盖高亮）
- Search: 清除搜索按钮完整清理内容匹配状态（IIFE 猴子补丁移到事件绑定之前）
- 内容匹配面板: `cmd-file-header` 点击区域修复（spacer 替代 `flex:1` 链接，仅文件名打开预览）
- 内容匹配面板: chevron 箭头方向修正（展开↓ 收起→）

## v1.46 (2026-06-28)
### Agent Panel 空白修复（grid-column 错位）
- 根因：`.agent-panel` 无显式 grid-column，auto-placement 在 sidebar/resize-handle 都 `display:none` 时把面板放到第 2 列（1fr≈25px→4px）
- 修复：`.agent-panel { grid-column: 4; }` 始终占第 4 列（750px）
- `createTerminal()` 容器尺寸检测加固：`clientWidth < 50px` 时用 600px 回退（4px 是 truthy 会绕过 `||600`）
- CSS transition 动画期间跳过 `fitAddon.fit()`（`doFit()` 守卫），ResizeObserver/win-resize 统一走 `doFit()`
- `connectWs()` 优先用预估算的 `_agentInitCols` 而非可能缩水后的 `term.cols`

### OpenClaw 输入框提示
- placeholder 添加 `/clawmate project` 切换项目提示

### README 业务架构图
- 用 `flowchart LR` 业务架构图替换技术实现图（去掉文件名、协议、端口）
- 结构：入口（skill/API）→ 功能域（filesystem/project/feedback）→ 后端（openclaw/codex/claude）
- 明确功能域与后端是正交维度，连线表示主要侧重而非绑定

## v1.44 (2026-06-26)
### Codex Agent 后端
- 新增 Codex 作为第三 Agent 后端（与 claude/openclaw 并列）
- session key 格式重构为 `{backend}:{root}[:{project}]`，确保不同后端会话隔离
- `get_claude_session` → `get_agent_session`，自动遍历所有 PTY 后端查找活跃会话
- 新增 `max_sessions` 上限（默认 10）+ `agent.env` 环境变量透传
- 新增 `CLAWMATE_AGENT_BACKEND` 环境变量覆盖配置，`config.example.json` 同步更新

### 画廊卡片菜单重构
- 卡片操作从底部 card-actions 迁移到右上角 ⋯ 菜单按钮（Dropdown 浮层）
- 复选框移入 thumb 内部，使用自定义无依赖样式（appearance:none + 对勾 ::after）
- 移动端菜单按钮尺寸调大（26px 触摸目标），dropdown 最小宽度 130px
- 列表视图新增行内复制按钮（.list-copy-btn）

### 文件移动 + 目录选择器
- 新增 `POST /api/clawmate/move` 端点 + `service.move_file()` 实现
- 安全校验：禁止目录移入自身/子目录、目标同名冲突检测
- 前端：目录选择器 Modal（树形展开 + 导航 + 确认），画廊 ⋯ 菜单集成
- `icons.js` 新增 `move` 图标（十字箭头）

### 面板 translate 动画
- 左右面板隐藏改用 `translate` 替代 `width/opacity` 过渡（GPU 合成层加速）
- 统一 `.preview-left/.preview-right/.preview-agent-panel` 三处动画模式
- share-view TOC 面板同步改为 translate 动效，新增 `hideTocInstant()` 无动画即时隐藏

### xterm.js 流控（输入延迟修复后续）
- 接入 `onFlowControlPause/Resume`：写入缓冲超限时丢弃帧而非无限堆积
- 终端断连时 `term.blur()` 暂停光标闪烁定时器，避免后台消耗主线程
- 重连时主动 `unobserve → observe` 避免 Firefox `InvalidStateError`
- 面板关闭时断开 `ResizeObserver`，减少后台回调竞争

### 其他
- 面包屑新增刷新按钮（带旋转 CSS 动画）
- deps: +websockets>=12.0, -aiofiles
- `.gitignore` 增加 `.claude/` 本地 IDE 配置排除


## v1.43 (2026-06-25)
### Mermaid 高度手动调整
- 每个 mermaid 图表底部新增拖拽手柄，支持鼠标/触摸拖拽调整显示区域高度
- DOM 结构重构：`.mermaid-inner` 承载滚动内容，handle 和 zoom controls 固定在外层不动
- 使用 Pointer Events + `setPointerCapture` 确保拖拽不与 mermaid zoom/pan 冲突
- handle 样式：无边框，12px 高，88px 宽柔色 grip 指示条

### Agent 输入延迟修复
- xterm 输入从 30ms debounce 改为立即 flush，消除 PTY echo 延迟导致的输入不可见问题

## v1.42 (2026-06-24)
### 图标系统重构
- 新增彩色字母标签：Markdown(M紫)/Python(Py蓝)/Shell($绿)/JSON({}橙)/Text(T灰)/JS(黄)
- 通用代码文件使用 `file-code` SVG（`<>` 尖括号图标），区别于默认 `file`
- 图标尺寸参数化：画廊 32px / 列表 22px，字体和圆角按比例自动缩放
- `_tag()` 辅助函数统一彩色标签生成，消除重复代码

### 侧边栏隐藏 dotfiles
- 目录树过滤 `.` 开头的隐藏目录（`.git`/`.clawmate`/`.claude` 等不再显示）

### Feedback 存储迁移
- `feedback.json` 从项目根目录迁移到 `.clawmate/feedback.json`
- 读取严格依赖 `.clawmate/` marker，无 marker 目录报错而非静默回退
- `feedback_api.py` + `store.py` 同步更新路径

### 新 API 端点
- `GET /api/clawmate/link` — 一站式搜索 + 预览链接生成（q/root/ext/limit）
- `POST /api/clawmate/mkdir` — 在指定目录下创建子目录
- `GET /api/clawmate/list?marker_filter=true` — 只返回含 `.clawmate/` marker 的项目目录

### Agent 面板增强
- PTY 输出 60fps 分组刷新，防止输出交错
- 用户输入后短暂 yield 确保 echo 先于输出到达
- chdir 时同步 session key 到所有已连接 WebSocket

### Auth 增强
- `auth.local_hosts` 配置项，支持 LAN 主机名/IP 免登录（`config.json`）

## v1.41 (2026-06-23)
### 压缩包预览
- `list_archive()` 支持 zip / tar / tar.gz / tar.bz2 / tar.xz / rar / 7z
- 预览页树形展开压缩包内容，显示文件/目录数、压缩前后大小
- 加密压缩包提示、下载按钮

### 文件移动
- `POST /api/clawmate/move` — 同 root 内移动文件/目录

### 目录面板修复
- 切换 root 时侧边栏和面包屑现在正确刷新（缓存 key 改为 `rootId:dir` 组合）
- 面包屑「复制」→「复制目录」，复制内容从相对路径改为绝对路径

### Feedback 存储
- `feedback.json` → `.feedback.json`，默认隐藏
- 所有 root 下现有 feedback.json 已重命名

## v1.40 (2026-06-22)
### 响应式策略统一 — Agent 面板打开时渐进隐藏
- Agent 打开时 `body.agent-open`，CSS 断点自动匹配移动端策略：
  - ≤1500px：隐藏目录面板 → ≤1300px：隐藏 label + 按钮文字 + list type/size 列
- 通用断点合并：≤1000px 隐藏 label + 按钮文字
- 目录自动隐藏/显示同步按钮状态（`matchMedia` + `getComputedStyle`）
- 目录隐藏时 agent 面板宽度不变，main 自动扩展

### 列表视图优化
- 日期缩短为 `M/D HH:mm` 格式
- `minmax(0, 1fr) + max-content` 自适应列宽，不换行
- ≤700px 隐藏 size，≤520px 隐藏 type
- 面包屑后添加「复制」链接

### Agent 面板
- 最大宽度降至 680px，默认 45vw
- 打开/关闭幻灯片动画（`forceExpand` 防 race condition）
- Claude Code 反馈注入（`get_claude_session` + `inject_to_session`）
- 修复 `open()` grid 不展开 bug

### 移动端
- 目录按钮替代 hamburger，sidebar overlay 与 agent 统一 `top:48px`
- Topbar 始终单行（`flex-wrap: nowrap`），搜索自适应收缩
- 搜索按钮高度/圆角与 topbar 按钮统一

### 清理
- 移除 `_md_to_ansi` 死代码
- Markdown 暗色主题改用 `[data-theme="dark"]`
- 注释 preview.js 4 个 debug `console.log`
- xterm addon CDN 版本对齐 5.5.0

## v1.39 (2026-06-22)
### Agent 面板 — Claude Code + OpenClaw 双后端
- 右侧面板嵌入 AI Agent 终端，支持拖拽调整宽度（360–1100px）
- **Claude Code 后端**：Python PTY 直连，完整 CLI 体验（--dangerously-skip-permissions）
- **OpenClaw 后端**：WebSocket JSON 协议 → Markdown 聊天视图（markdown-it 渲染）
- 会话持久化：Claude Code 进程存活于 WebSocket 断开期间（10min idle 超时），重连回放输出缓冲
- Feedback 任务路由：Claude 活跃时注入 PTY，否则回退 OpenClaw gateway webhook

### 首页改进
- 目录切换按钮（顶栏 📁），桌面端切换左侧栏显隐，移动端浮层滑入
- 切换 root 时自动关闭 Agent 面板（session root 绑定）
- Agent 按钮放在主题按钮之前
- 移动端顶栏：搜索始终同行，品牌名隐藏，≤480px 搜索按钮仅图标
- 移动端工具栏：隐藏多选/画廊/列表文字、隐藏类型/排序标签
- 侧栏浮层和 Agent 面板统一 top:48px 高度

### 预览页改进
- 反馈面板拖拽调整宽度（260–700px）
- 文件点击新标签页打开（保护 Agent 会话）
- 底栏移除「返回」按钮
- 反馈卡片删除按钮风格统一

### 配置文件
- config.json / config.example.json 新增 `agent` 配置块
- docker-compose.yml 新增 `CLAWMATE_AGENT_BACKEND` 环境变量

### 修复
- Ctrl+C/V 在终端中行为正常（有选区时复制，Ctrl+V 粘贴）
- 不支持文件类型显示友好 fallback + 下载按钮
- uvicorn WebSocket ping 间隔 30s，超时 60s
- 移动端 main 宽度修复（grid-column 错位）
- agent panel slide-in/slide-out 动画
- output_buffer 按条目数限制（200条），防止内存泄漏
- chat.history 响应消费，聊天重连状态提示，流式自动滚屏

## v1.38 (2026-06-21)
### 性能优化
- KaTeX CSS 按需加载：仅含 `$`/`$$` 数学公式的 Markdown 才注入 KaTeX 样式
- 本地化 CSS 资源（github-markdown-dark、highlight.js），不再依赖外部 CDN
- Logo 图片压缩（PNG → SVG/WebP）
- `<script defer>` 加载所有脚本，CSS 独立文件并行下载
- Mermaid/KaTeX/highlight.js 懒加载：首屏不阻塞
- 目录列表内存缓存（30s TTL），减少重复 API 请求

### PDF 预览重构
- 自托管 pdf.js viewer（`/clawmate/pdfjs/`），完全脱离 CDN 依赖
- PDF 文件直接使用 pdf.js 渲染，不再经过 ONLYOFFICE 编辑器

### ONLYOFFICE 修复
- `toolbarNoTabs` 移除，解决 `indexPostfix=_loader` 导致的 JS 加载失败
- 最小化 UI：紧凑工具栏（无侧面板、无标尺、无右侧面板）
- 查看/编辑模式统一 minimal chrome
- `forcesave`/`goback`/`feedback` 等无效 customization key 移除
- `dataclass.get()` 替换为属性访问（兼容性修复）

### 首页改进
- 类型过滤 `<select>`：选中非"全部"时紫色高亮
- 480-768px 断点顶栏重排：搜索输入置于品牌与操作按钮之间
- ≤768px 仅显示 logo（隐藏 "ClawMate" 文字）

### 分享视图修复
- HTML 文件在 iframe 中渲染（与 preview 行为一致）
- 非 Markdown 文件自动隐藏左侧 TOC 大纲
- 添加关闭按钮（返回首页）

### 移动端修复
- 反馈面板：选中文本延迟复制+高亮（等待面板开启），关闭时清理

### 登录页修复
- 资源/CSS 使用相对路径加载，多 base URL 部署可移植

### 不支持文件类型的预览体验
- `.tar.gz`/`.rar`/`.exe` 等二进制文件显示友好 fallback 页面：文件图标 + 名称/类型/大小 + 下载按钮
- `<img>` 加载失败显示降级提示，而非浏览器默认破碎图标
- `<video>`/`<audio>` 加载失败显示编码/损坏提示

### 杂物
- `.gitignore` 新增 Playwright 临时文件

## v1.37 (2026-06-19)
### 反馈存储性能优化
- 内存读缓存：基于 mtime_ns 校验，分离 cache_lock 避免读写互斥，LRU 淘汰(256条上限)
- 过期清理：done/failed/deleted 超过 cleanup_done_after_days(默认30天)自动删除
- pending/in_progress 条目永不清理；threshold=0 禁用清理

### 工具栏样式统一
- .tb-left label/select/button 统一 padding:0 左缘对齐
- select/button bordered 元素 padding:0 14px 呼吸空间
- 全部 active 状态去辉光 box-shadow，统一 accent填充+白字
- outline:none 消除 focus ring 与 active 视觉冲突
- hover:not(.active) 避免 active 状态下 hover 变色无法阅读

## v1.36 (2026-06-19)
### 反馈系统全面修复
- **移动端**：新增 touchend 事件监听解决 selectionchange 不可靠；选中文本跨面板开启/关闭保留
- **移动端**：提交成功自动关闭底部面板并打开右侧反馈栏，状态轮询移至侧边栏(10s间隔)
- **桌面端**：提交成功立即关闭 tooltip/输入卡，右侧反馈栏自动弹出；错误内联显示
- **侧边栏轮询**：打开时每10秒自动刷新 pending/in_progress 条目状态
- **桌面端轮询**：提交后8秒间隔跟踪新提交ID直至完成(进度显示 ⏳ 反馈 X/Y)

### KaTeX 渲染修复
- 移除 \\(\\)/\\[\\] 分隔符 — JS字符串 \\( 经KaTeX regex处理后错误匹配了所有普通()
- 导致文档中所有括号内容被当作数学公式用KaTeX字体渲染

### 中英文混排字体
- .markdown-body 字体栈加入 Noto Sans SC，消除括号内中日韩+ASCII字符的字体割裂

## v1.35 (2026-06-18)
### 响应式统一 — 桌面/移动端合并
- 删除 m/ 目录（m/index.html, m/preview.html, m/style.css），main.py 移除 UA 重定向
- index.html：移动端自动切列表视图、隐藏多选、隐藏分类过滤、列表卡片布局
- preview.html：三列网格 → 移动端单列+侧栏浮层、底栏精简、选区浮动按钮+底部反馈面板
- share-view.html：重构为与 preview 一致的三列布局 + 顶栏📑/🌓 + asset 端点

### 顶栏 & 底栏
- 大纲按钮移至顶栏（📑 💬 🌓 🚪），与反馈/主题/登出并列
- 顶栏按钮 active 态紫色 accent 高亮 + 外发光，CSS 顺序修正 hover/active
- 移动端底栏隐藏路径/导出/下载/重命名/删除，保留返回/分享/动态按钮
- 移动端顶栏 brand 替换为 ← 返回按钮

### 编辑模式增强
- 大纲点击跳转支持编辑 textarea、源码 pre、渲染视图三种模式
- Ctrl/Cmd+S 快捷键保存
- 编辑窗口高度填满视口
- Banner 美化（圆角 badge + 快捷键提示）

### 排序 & 列表
- 排序从下拉框改为 pill 按钮（↓最新 / ↑名称 / ↓大小）
- 列表日期右对齐，移动端 icon 缩进对齐
- 搜索框高度与排序行统一（30/28/26px 三档）

### 分享
- share_routes.py 新增 /share/{token}/asset 端点（引用图片服务）
- 前端 markdown 图片路径重写 + onerror 兜底

### 反馈面板
- 默认关闭，操作后自动打开 + 同步 grid 列宽 + 按钮态
- 移动端右侧面板保持浮层（非底部 sheet）
- 新增底部反馈添加面板（选区→✏️→底部滑出→填备注→提交）

### 代码质量
- CSS 去重 + 删除 200+ 行无用样式（preview-body、feedback-tooltip 等）
- JS hljs → window.hljs 统一引用，移除 debug 日志
- preview.js / preview-common.js 模块化，移动端 JS 提取为独立文件
- 文件类型常量统一到 preview-common.js，parseCodeOutline/buildHeadingTOC 等共享
### 分享链接（新增功能）
- POST /api/clawmate/share/create 生成 24h 短链，同一文件复用 token
- /clawmate/share-view.html?token=*** 免登录只读预览
- 支持 Markdown/Mermaid/KaTeX/highlight.js /图片/音视频/Office
- share_links.json 与 config.json 同目录（磁盘持久化）
- Auth 白名单放行 share-view.html + share API（免登录）

### 移动端
- 底栏新增 ↗️ 分享按钮，弹出面板与大纲/反馈统一 m-panel 风格
- note 字段移除必填校验（与桌面版对齐）

### 后端修复
- 重命名 API 支持目录（此前仅支持文件）
- GitHub Actions docker.yml 构建上下文修复（context: ./dev → .）

### Skill
- clawmate project 统一更名为 init
- 新增 clawmate plan（规划/更新 CLAWLIST）
- 安全说明声明：数据不传第三方、仅本地操作、init/do 需用户确认
- 清理 cron/cron-tick 引用（已废弃）
- CLAWMATE_URL 配置化（用户自行配置）

## v1.33 (2026-06-08)
- task/run 统一为唯一入口（selections 数组，删除 feedback_create）
- wake_agent_for_root / cron-tick 迁至 task_runner
- feedback_create 删除
- store: _get_feedback_path 不自动创建目录（目录不存在则回退到 root，记录错误日志）
- store: 删除 if not text: continue（空内容不跳过）
- 安全: 删除操作防根目录（safe_rel 空值检查）+ _normalize_rel_path 拦截 "."
- 安全: wake message 附加 scope 范围约束提醒
- subtitle.py 合并到 subtitle_routes.py
- cron_template.txt 删除
- Mobile: submit 移至 /task/run（selections 格式）
- Mobile: fbInputTags 从 task_templates 动态加载
- Mobile: position 格式与 desktop 统一（Line/Page/Section 按文件类型）
- Mobile: Markdown 渲染模式 detectSectionFromDOM → Section #xxx
- Mobile: 100dvh 防止浏览器 chrome 遮盖
- Mobile: 点击文件在当前窗口打开
- UI: preview.html <430px 隐藏 preview-btn-group

## v1.32 (2026-06-08)
- Store 死代码清理（_detect_position_prefix 等）+ 内存泄漏修复
- feedback card 倒序排列、position 优先使用 item.position
- CLAWLIST/CHANGELOG/计划/笔记 移出 git 跟踪
- Skill 接口 URL 统一使用 {base_url}、README 同步

## v1.31 (2026-06-07)
- 移除所有窄屏 @media 和抽屉覆盖，保持 3 列网格
- 移除 batch-process 端点
- Wake 全链路去重/冲突检测、HTTP 标记 in_progress
- root/project 拼接到 message 首行、前端直接传 task_id
- 禁止文件内容被浏览器缓存

## v1.30 (2026-06-07)
- Position 格式标准化（Section/Line/Time/Range）
- Task 体系加固：schema 补全 action/scope/task_id，note 优先保留
- 移除未使用的 FeedbackTag、feedback.tags

## v1.29 (2026-06-07)
- Task Template 统一体系：task_templates.json + task_runner.py
- subtitle 路由独立，wake message data-driven（agent 零额外 API 调用）
- 前端标签从 /api/config 动态渲染

## v1.28 (2026-06-06)
- 移动端独立页面：m/index.html（目录浏览）+ m/preview.html（阅读+反馈）

## v1.27 (2026-06-06)
- 排序 select/button 与 state 同步
- GitHub Markdown CSS CDN 动态暗色/亮色切换
- marked → markdown-it（container/emoji/footnote/task-lists 插件）

## v1.26 (2026-06-06)
- config.py（类型化 ConfigLoader + TTL 缓存）+ store.py（纯函数 FeedbackStore）
- feedback_api 重写、cron_template 重写、subtitle.py 死代码清理

## v1.25 (2026-06-06)
- webhook 配置从 env 文件移至 config.json（openclaw 节）
- 删除独立 webhook_wake.py，cron_manager 精简
- 删除 hooks.mappings 旧条目 + env 文件 + 独立审计日志

## v1.3 (2026-06-06)
- preview.html 全类型预览统一（图片/音视频/Office/PDF/代码/Markdown）
- ONLYOFFICE 编辑模式 + JWT 安全集成
- 反馈面板、底部工具栏

## v1.24-c (2026-06-05)
- 移除 disk audit，仅保留 journalctl INFO（强哥决策）

## v1.24-b (2026-06-05)
- 前端过滤空白名目录（renderSidebarTree 入口 1 行 filter）

## v1.24-a (2026-06-05)
- feedback API 5 端点补全 logger.info 审计

## v1.22 (2026-06-05)
- systemd unit 加 Environment=PATH（含 ~/.npm-global/bin），修复 wake

## v1.21 (2026-06-05)
- _wake_agent_for_root 加 success/failure INFO 日志
- ?status=all 字面过滤 bug 修复

## v1.20 (2026-06-05)
- README/PRD 标记 desktop-only（v1.19 mobile 回退说明）

## v1.19 (2026-06-05)
- 全面回退 mobile（~1903 行代码移除），仅保留 desktop 友好修复

## v1.18 (2026-06-05)
- preview-mask inset 改为 top:48px/bottom:48px 让出顶底栏

## v1.17 (2026-06-05)
- mobile UX 4 项修复（SPAPreview label、按钮隐藏等）

## v1.16 (2026-06-05)
- 移动端 button 28px、上传按钮改 fixed bottom bar

## v1.15 (2026-06-05)
- topbar/bottombar 元素垂直居中统一

## v1.14 (2026-06-05)
- topbar/bottombar 风格统一 + 状态机 bug 修复

## v1.13 (2026-06-04)
- preview-mask 桌面 display:none、SPAPreview 冗余 × 按钮移除

## v1.12 (2026-06-04)
- CLAWMATE_PUBLIC_BASE_URL 启动检查

## v1.11 (2026-06-04)
- 移动端 13 项一次性修复（Mermaid 缩放、44px 触摸目标、上传、SPA 预览等）

## v1.10 (2026-06-04)
- 移动端 P0 4 项修复（Sheet、遮罩、safe-area、断点）

## v1.9 (2026-06-04)
- DELETE 操作写 audit log（JSONL）、本机 bypass 保留但记录 caller

## v1.8 (2026-06-04)
- 异常日志结构化、_load_config TTL 缓存
- feedback.json 归档（90 天 done → archive）

## v1.7.1 (2026-06-04)
- 图片导航计数器改为 "N / M" 格式

## v1.7 (2026-06-04)
- 图片预览上/下一张、feedback 标签配置化

## v1.6.1 (2026-06-04)
- constants.py 工程化收尾（5 个 env 常量、替换 10 处硬编码）

## v1.6 (2026-06-04)
- 架构重构（feedback 路由独立 + cron 管理独立 + validators）
- Auth 改进（localhost bypass + query string 保留）
- 字幕提取（faster-whisper）、媒体工具栏集成

## v1.5 (2026-06-04)
- clawmate.service.system 模板参数化（__VAR__ 占位符）
- 删除 install.sh，README 更新

## v1.4 (2026-06-04)
- 502 故障修复：部署 user-level systemd + nginx 配置确认
- 验证：内部/外部全 200，无副作用

## v1.3 (2026-06-01)
- 反馈增强 + 代码大纲 + 质量提升（详见主 CLAWLIST）

## v1.2 (2026-05-31)
- Feedback 重构 + Standalone 三栏布局

## v1.1 (2026-05-30)
- Slash Commands 增强 + Feedback Push Wake

## v1.0 (2026-05-30)
- UI 增强 + 完善 + PDF 降级

## v0.4 (2026-05-30)
- 批量反馈 + Daemon

## v0.3 (2026-05-30)
- 反馈闭环

## v0.2 (2026-05-30)
- Standalone 预览 + Skill

## v0.1 (2026-05-30)
- MVP
