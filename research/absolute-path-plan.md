# 文件真实路径展示方案

> 状态：审批通过，开始实施 | 日期：2026-06-02

## 1. 背景

用户在使用 ClawMate 浏览文件时，需要获取文件的**操作系统绝对路径**，用于：
- 复制路径给 Agent 执行操作（如"修改 `~/webprojects/clawmate/README.md`"）
- 在终端中直接操作文件
- 分享给其他工具

当前全线只暴露**相对路径**（`clawmate/README.md`），用户无法直接获取绝对路径。

## 2. 现状

| 位置 | 已有路径信息 | 类型 |
|------|-------------|------|
| `file_info()` | `"path": rel_path` | 相对路径 |
| `list_dir` API | `"path": rel_path` | 相对路径 |
| preview.html | `filePath` from URL param | 相对路径 |
| index.html 卡片 | `entry.relPath` | 相对路径 |
| index.html 面包屑 | `currentPath` | 相对路径 |

后端 `safe_path()` 第一个返回值就是 `root_path`（解析后的绝对路径），组合即可得到绝对路径：`root_path / rel_path`。

## 3. 方案（已批准）

> 原方案被否决。新思路：**仅在 preview.html 中实现路径拷贝**，不涉及 index.html。

### 3.1 前端：preview.html 仅改 BottomBar

将 preview.html BottomBar 现有的「📋 拷贝」按钮替换为「📁 路径」按钮：

```
桌面端 BottomBar:  [← 返回] │ [📁 路径] [📥 导出] [⬇ 下载] [✏️ 重命名] │ [🗑 删除]
                                ↑ 点击复制绝对路径到剪贴板 → Toast "路径已复制"
```

实现：
```javascript
pathBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(absPath).then(() => showToast('✅ 路径已复制'));
});
```

**不涉及 index.html 改动**（文件卡片、面包屑均不做修改）。

## 4. 安全考虑

| 风险 | 缓解 |
|------|------|
| 暴露服务器文件系统路径 | ClawMate 本身就是文件浏览器，root 目录已对用户可见 |
| 路径可能包含敏感信息（用户名等） | 仅显示 root 内的路径段，root 前缀可配置是否显示 |
| 剪贴板 API 限制 | `navigator.clipboard` 需要 HTTPS 或 localhost，当前环境满足 |

## 5. 任务列表

| # | 任务 | 描述 | 文件 |
|---|------|------|------|
| P1 | preview.html BottomBar 拷贝按钮替换为路径按钮 | 将现有 📋 拷贝按钮替换为 📁 路径按钮，点击复制绝对路径 → Toast | `preview.html` |

## 6. 预估工作量

- 后端：1 处修改（`file_info` 加 1 行）
- preview.html：BottomBar 拷贝按钮替换为路径按钮 + Toast

总计约 15 行代码。
