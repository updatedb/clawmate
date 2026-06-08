# Cron 任务重复创建问题分析

> 状态：已完成研究  
> 时间：2026-06-03 12:25 GMT+8

---

## 1. 现象

当前系统中有 **24 个** clawmate-feedback-inbox cron job（应为 6 个），按 agent 分组：

| agent | 应有 | 实有 | 冗余 |
|-------|:--:|:--:|:--:|
| helper | 1 | 4 | 3 |
| work | 1 | 4 | 3 |
| writer | 1 | 4 | 3 |
| travel | 1 | 4 | 3 |
| home | 1 | 4 | 3 |
| main | 1 | 4 | 3 |

---

## 2. 根因

### 2.1 `cron rm` 同样只接受 UUID，不接受名字

```bash
$ openclaw cron rm clawmate-feedback-inbox-work
GatewayClientRequestError: invalid cron.remove params: id not found

$ openclaw cron rm 6c97cd5e-7ca7-45e9-b2a8-f4a14dcc3464
{"ok": true, "removed": true}
```

### 2.2 `main.py` 两处删除逻辑都用了名字

```python
# 第一处：删除旧泛用 cron
for old_name in ("clawmate-feedback-inbox-check",):
    subprocess.run([cron_bin, "cron", "rm", old_name], timeout=5, capture_output=True)
    # ↑ 传名字 → 返回 error → 什么都不删

# 第二处：删除 per-agent 旧 cron
subprocess.run([cron_bin, "cron", "rm", cron_name], timeout=5, capture_output=True)
# cron_name = "clawmate-feedback-inbox-work" → 传名字 → 返回 error → 什么都不删
```

### 2.3 错误被静默吞掉

```python
except Exception:
    pass  # 删除失败？无所谓，继续创建新的
```

**结果**：每次服务器启动，6 个新的 cron job 被创建，旧的却从未删除。

---

## 3. 触发时机

每次服务器进程重启都会创建 6 个新 cron job：

```
main.py 启动
  → __name__ == "__main__"
  → _sync_cron_jobs()
  → cron rm <name>  ← 失败，静默跳过
  → cron add ...    ← 成功，创建 6 个新 job
```

服务器重启场景包括：
- 手动 `kill` + 重新启动
- 服务器 crash 后 systemd 自动重启（如配置了）
- `main.py` 代码更新后重启
- 系统重启

当前 24 个 job = 4 次重启 × 6 agent。每次调试 session 中服务器被反复 kill/restart 都会累加。

---

## 4. 为什么没有定时清除机制

`_sync_cron_jobs()` 的设计意图是「启动时同步」——先删旧的再建新的。这种模式依赖**删除成功**才能保证唯一性。

但删除从未成功过，所以：
- 没有定时清除机制
- 没有 cron job 过期策略
- 没有启动时的兜底扫描（比如先 `cron list` 再逐个 UUID 删除）
- 旧 job 永远留在系统中，直到手动清理

---

## 5. 修复方案

### 方案：`_sync_cron_jobs()` 加 name→UUID 解析

与 push wake 修复（commit `466a6df`）采用相同模式：

```python
def _resolve_cron_id(cron_bin, name):
    """通过 cron list 解析名字对应的 UUID"""
    result = subprocess.run(
        [cron_bin, "cron", "list"],
        timeout=10, capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.split("\n"):
        if name in line:
            return line.split()[0] if line.strip() else None
    return None

# 在 _sync_cron_jobs() 中：
for agent_id, root_ids in agent_roots.items():
    cron_name = f"clawmate-feedback-inbox-{agent_id}"
    
    # 删除旧 job（通过 UUID）
    old_id = _resolve_cron_id(cron_bin, cron_name)
    if old_id:
        subprocess.run([cron_bin, "cron", "rm", old_id], ...)
    
    # 创建新 job
    subprocess.run([cron_bin, "cron", "add", "--name", cron_name, ...])
```

### 局限性

- 如果存在多个同名的 cron job（当前状态），`_resolve_cron_id` 只删第一个匹配的
- 需要额外逻辑：循环删除直到找不到同名 job

### 增强方案

```python
# 删除所有同名 cron job
while True:
    old_id = _resolve_cron_id(cron_bin, cron_name)
    if not old_id:
        break
    subprocess.run([cron_bin, "cron", "rm", old_id], ...)
```

---

## 6. 当前清理

需要手动清理 23 个冗余 cron job（保留每个 agent 最新的 1 个）。

---

## 7. 预防建议

| 建议 | 说明 |
|------|------|
| `cron rm` 用 UUID | 与 `cron run` 一致，先 `cron list` 解析 |
| 启动时全量扫描 | 循环删除所有同名 job，再创建 1 个新的 |
| 加日志 | `cron rm` 失败时至少打印一行 warning |
| 不要 `except: pass` | 至少 log 错误原因，方便排查 |
