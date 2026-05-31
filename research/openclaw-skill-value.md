# ClawMate Skill 设计

**日期**: 2026-05-29
**修订**: 2026-05-29

## 核心定位

**Skill 只做两件事**：① 让 Agent 生成能直接预览的文件链接 ② 让用户能选中内容发回给 Agent 继续处理。

文件 CRUD（list/read/write/delete/search）Agent 用 `exec` 跑 shell 命令即可，不需要 Skill。

---

## Skill API 设计

```javascript
// clawmate skill tools（仅 2 个）
{
  "clawmate_preview":  { root, path } → Agent 生成文件后可嵌入的预览 URL
  "clawmate_feedback": { root, path, selection, note?, targetSession? } → 选中内容+备注发回 Agent
}
```

### clawmate_preview — 预览模式区分

| 场景 | 触发方 | 预览形态 | URL 参数 |
|------|--------|---------|---------|
| Agent 聊天中发链接 | Agent 通过 skill 生成 | **独立页面**（全屏渲染） | `&mode=standalone` |
| ClawMate 内浏览 | 用户点击文件 | **弹出窗口**（保持现有行为） | 默认（modal） |

### clawmate_feedback — 反馈闭环

**阶段 1**（MVP）: 用户在预览页选中文本 → 发回 Agent
**阶段 2**（后续）: 多选 + 备注 + 积累成 todo list → 批量发送

**会话路由逻辑**:
```
选中文本 → 发回时:
  ├─ 操作该文件的会话还活着 → 发回同一会话（继续上下文）
  └─ 会话已过期/关闭 → 开启新会话 + 注入项目背景
       └─ 用户重新打开当前项目 → Agent 加载项目上下文
```

## 不需要 Skill 做的

- ❌ 不需要文件 CRUD（Agent 用 `exec` 跑 shell 命令即可）
- ❌ 不需要文件搜索（同上，`find`/`grep` 更快）
- ❌ 不需要 ONLYOFFICE 预览管理（ClawMate 服务层处理）

**Skill 只做两件事**：① 让 Agent 生成能直接预览的文件链接 ② 让用户能选中内容发回给 Agent 继续处理。
