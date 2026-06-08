# Save 接口格式校验方案

> 状态：待评审  
> 背景：2026-06-01 用户通过 ClawMate 编辑 `config.json` 时引入语法错误（缺逗号 + 多余逗号），导致服务端 JSON 解析失败，所有接口返回 403。需要防呆。

---

## 方案概览

在 `POST /api/clawmate/save` 中增加可选校验层，保存前检测文件类型并验证格式合法性。
不合法则拒绝写入，返回具体错误位置和描述。

---

## 1. JSON 校验

### 实现
```python
import json

def validate_json(content: str) -> tuple[bool, str]:
    """返回 (是否合法, 错误描述)"""
    try:
        json.loads(content)
        return True, ""
    except json.JSONDecodeError as e:
        # e.lineno 行号, e.colno 列号, e.msg 错误消息
        lines = content.split('\n')
        lineno = e.lineno
        colno = e.colno
        context_before = lines[lineno - 1][max(0, colno - 30):colno] if lineno <= len(lines) else ""
        context_after = lines[lineno - 1][colno:colno + 30] if lineno <= len(lines) else ""
        return False, (
            f"JSON 语法错误 (第 {lineno} 行, 第 {colno} 列): {e.msg}\n"
            f"  上下文: ...{context_before}>>>HERE<<<{context_after}..."
        )
```

### 特点
- **零依赖**：Python 标准库 `json` 模块
- **精确错误定位**：行号 + 列号 + 上下文
- **常见错误覆盖**：缺逗号、多余逗号、引号不匹配、括号不闭合

### API 响应示例
```json
{
  "ok": false,
  "error": "json_syntax_error",
  "detail": "JSON 语法错误 (第 12 行, 第 5 列): Expecting ',' delimiter\n  上下文: ...\"roots\": [>>>HERE<<<{\"id\": \"webprojects\"..."
}
```

---

## 2. CSS 校验

### 方案选择

| 方案 | 依赖 | 精度 | 推荐 |
|------|------|------|:--:|
| **tinycss2 词法分析** | tinycss2（已安装） | 中等 | ✅ |
| cssutils | cssutils（需安装） | 高 | ⚠️ 重量级 |
| 纯括号计数 | 零依赖 | 低 | ❌ 误报率高 |

**推荐 tinycss2**：已有依赖，能检测括号/引号不匹配、非法 token。

### 实现
```python
import tinycss2

def validate_css(content: str) -> tuple[bool, str]:
    """返回 (是否合法, 错误描述)"""
    try:
        # 忽略解析错误收集
        rules = tinycss2.parse_stylesheet(content, skip_whitespace=True, skip_comments=True)
        errors = [r for r in rules if r.type == 'error']
        if errors:
            err_lines = []
            for e in errors[:3]:  # 最多返回 3 个错误
                line = e.source_line if hasattr(e, 'source_line') else '?'
                col = e.source_column if hasattr(e, 'source_column') else '?'
                err_lines.append(f"  第 {line} 行, 第 {col} 列: {e.message}")
            return False, "CSS 语法错误:\n" + "\n".join(err_lines)
        return True, ""
    except Exception as e:
        return False, f"CSS 解析异常: {str(e)}"
```

### 特点
- **已有依赖**：tinycss2 已安装
- **标准兼容**：遵循 CSS Syntax Level 3
- **多错误报告**：一次返回最多 3 个错误

### API 响应示例
```json
{
  "ok": false,
  "error": "css_syntax_error",
  "detail": "CSS 语法错误:\n  第 45 行, 第 3 列: Expected '}'"
}
```

---

## 3. HTML 校验

### 方案选择

| 方案 | 依赖 | 精度 | 推荐 |
|------|------|------|:--:|
| **html5lib 严格解析** | html5lib（已安装） | 高 | ✅ |
| BeautifulSoup + lxml | bs4 + lxml（已安装） | 中 | ⚠️ 自动修复，不报错 |
| 纯标签计数 | 零依赖 | 低 | ❌ |

**推荐 html5lib**：已有依赖，严格模式解析，能检测标签不闭合。

### 实现
```python
import html5lib
from html5lib.html5parser import ParseError

def validate_html(content: str) -> tuple[bool, str]:
    """返回 (是否合法, 错误描述)"""
    try:
        parser = html5lib.HTMLParser(strict=True)
        parser.parse(content)
        return True, ""
    except ParseError as e:
        return False, f"HTML 语法错误: {str(e)}"
    except Exception as e:
        # 宽松模式：仅检测标签平衡
        return _check_html_balance(content)

def _check_html_balance(content: str) -> tuple[bool, str]:
    """后备方案：检查标签开闭平衡"""
    import re
    # 提取所有标签
    tags = re.findall(r'</?(\w+)[^>]*>', content)
    stack = []
    自闭合标签 = {'br', 'hr', 'img', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
    
    for tag in tags:
        # 简化处理：用 raw tag string 判断
        pass
    
    # 简化版：计算 <tag 和 </tag> 数量差异
    opens = len(re.findall(r'<(\w+)[>\s]', content))
    closes = len(re.findall(r'</(\w+)>', content))
    if opens != closes:
        return False, f"HTML 标签不平衡：{opens} 个开标签, {closes} 个闭标签"
    return True, ""
```

> ⚠️ html5lib strict 模式对真实 HTML 过于严格（常因空白/编码问题误报）。  
> 建议：html5lib strict 作为首选，失败时降级到标签平衡检查（轻量级，足够检测编辑引入的闭合错误）。

### 特点
- **已有依赖**：html5lib 已安装
- **两级校验**：strict → balance 降级
- **覆盖场景**：忘写 `</div>`、标签嵌套错误

---

## 4. 整体架构

### 校验调度
```python
# routes.py 中 clawmate_save 端点

VALIDATORS = {
    '.json': validate_json,
    '.css': validate_css,
    '.html': validate_html,
    '.htm': validate_html,
}

@router.post("/api/clawmate/save")
async def clawmate_save(request: Request):
    # ... 现有参数解析 ...
    
    # 格式校验（可跳过，通过 validate=false）
    validate = body.get("validate", True)
    if validate:
        ext = Path(file_path).suffix.lower()
        validator = VALIDATORS.get(ext)
        if validator:
            ok, error_msg = validator(content)
            if not ok:
                return JSONResponse(
                    {"ok": False, "error": f"{ext[1:]}_syntax_error", "detail": error_msg},
                    status_code=422
                )
    
    # ... 现有保存逻辑 ...
```

### API 行为
| 场景 | 行为 |
|------|------|
| `validate=true`（默认） | 校验失败 → 422 + 错误详情 |
| `validate=false` | 跳过校验，直接保存 |
| 非白名单扩展名 | 跳过校验 |

---

## 5. 前端集成

在 `preview.html` 编辑模式下：
1. 用户编辑 → 点击保存
2. 后端返回 422 → 前端解析错误详情
3. 在编辑器中显示错误提示（红色边框 + 错误消息浮层）
4. 用户修正 → 重新保存

### 前端改动（最小方案）
```javascript
// preview.html saveContent 函数
if (res.status === 422) {
  const data = await res.json();
  if (data.error && data.error.includes('syntax_error')) {
    showToast('❌ ' + data.detail, 5000);
    // 高亮错误行（如果编辑器支持）
    if (data.error === 'json_syntax_error') {
      const lineMatch = data.detail.match(/第 (\d+) 行/);
      if (lineMatch) highlightLine(parseInt(lineMatch[1]));
    }
    return;
  }
}
```

---

## 6. 实施计划

| 阶段 | 内容 | 预估工时 |
|------|------|:--:|
| Phase 1 | JSON 校验（零依赖，最高 ROI） | 0.5h |
| Phase 2 | CSS + HTML 校验（已有依赖） | 1h |
| Phase 3 | 前端错误展示 | 0.5h |
| Phase 4 | 测试覆盖（各格式合法/不合法样本） | 0.5h |

---

## 7. 风险与限制

| 风险 | 缓解 |
|------|------|
| html5lib strict 误报 | 降级到标签平衡检查 |
| tinycss2 报错信息不友好 | 包装错误，添加上下文 |
| 大文件校验耗性能 | 仅在 save 时触发，不阻塞预览 |
| Markdown 无格式校验 | 暂不纳入（Markdown 无标准语法树） |
