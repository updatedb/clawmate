# ClawMate 回归测试计划 — v0.1–v1.2

**项目**：ClawMate
**测试范围**：v0.1, v0.2, v0.3, v0.4, v1.0, v1.1, v1.2 全版本
**测试时间**：2026-05-30
**测试环境**：`python3 main.py` → http://localhost:5533/clawmate/

---

## 1. 测试范围

### v0.1 文件管理
- 目录浏览、面包屑、root 切换
- 画廊/列表双视图
- 类型过滤、排序、搜索
- 分页、下载、删除（二次确认）
- 批量多选、批量下载、批量删除
- 复制路径

### v0.2 Standalone 预览
- `?mode=standalone` 直达预览
- 去侧边栏/工具栏，内容最大化
- 底部返回链接
- clawmate_preview 链接生成

### v0.3 Feedback 闭环
- 预览页选中文本 → 操作浮层弹出（仅预览区）
- 备注输入 → 「加入列表」→ 面板累积
- 「✅ 提交」→ 写入 FEEDBACK.md → push wake
- feedback 面板（三栏布局右侧栏）

### v0.4 批量操作 + Daemon
- 多选→批量删除/下载
- 拖拽上传（drag-drop → upload API → 列表刷新）
- install.sh 语法检查

### v1.0 UI + PDF 降级
- 界面美观（卡片圆角/阴影/颜色/主题切换）
- 移动端响应式（<768px 汉堡菜单）
- 骨架屏
- PDF 降级（ONLYOFFICE 不可用时 pdf.js 兜底）

### v1.1 Slash Commands
- `/clawmate preview <filename>` → 可点击链接
- `/clawmate list` → 今天全部 feedback
- `/clawmate list pending` → 待处理
- `/clawmate list done` / `list wait` / `list failed`
- `/clawmate list 黄昏` → 按文件名过滤
- `/clawmate list pending 黄昏 2026-05-30`
- Feedback 创建 → push wake

### v1.2 Feedback 重构 + 三栏
- Feedback 无 type 字段
- `/feedback/list` 三参数过滤
- 默认 today 过滤
- Standalone 三栏布局（左目录/中预览/右 feedback panel）
- 底部工具栏（复制/导出/下载/删除/返回）

### API 端点（18个）
```
GET  /api/clawmate/config
GET  /api/clawmate/list
GET  /api/clawmate/search
GET  /api/clawmate/preview
GET  /api/clawmate/download
GET  /api/clawmate/raw
GET  /api/clawmate/batch-download
POST /api/clawmate/upload
GET  /api/clawmate/preview-link
GET  /api/clawmate/onlyoffice/script-url
GET  /api/clawmate/onlyoffice/config
GET  /api/clawmate/onlyoffice/file
POST /api/clawmate/feedback
GET  /api/clawmate/feedback/list
POST /api/clawmate/feedback/update
GET  /api/clawmate/feedback/status
DELETE /api/clawmate/delete
DELETE /api/clawmate/delete-dir
```

---

## 2. 测试方法

| 方法 | 适用范围 |
|------|----------|
| **API 自动化测试** | 所有 18 个后端端点（curl 脚本验证响应码+JSON 结构） |
| **代码审查** | JS 前端逻辑（骨架屏/拖拽/三栏布局/主题切换） |
| **CSS 审查** | UI 美观性（圆角/阴影/颜色变量/响应式断点） |
| **路由审查** | Standalone 模式、参数传递 |

---

## 3. 测试数据

- `test/短篇小说-黄昏图书馆.md` — 中文文件名测试文件（用于文件名模糊匹配测试）
- `/tmp/test_upload.txt` — 上传测试临时文件
- `Openclaw` root 的 `outbound/` `browser/` 目录 — 现有图片/文本文件用于预览测试

---

## 4. 通过标准

- 所有 API 端点返回 2xx/4xx 正确状态码（无 500）
- Feedback 写入正确 → 读取验证
- 上传/删除 循环验证
- JS 代码无语法错误（静态分析）
- 已有功能无回归（对比 CLAWLIST.md 记录）
