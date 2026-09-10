# 设置面板修复设计

## 目标

修掉系统设置模态（Rootdir 管理 / 用户管理）在评审中实测确认的缺陷：一处控件布局被选择器泄漏压垮，一处行内按钮完全未样式化，以及四处一致性与可访问性问题。

不引入新概念、新组件、新令牌——全部用 `tokens.css` 既有值，把设置面板拉回站内既有的组件惯例。

## 背景：实测确认的缺陷

每条都在真实浏览器中用真实标记 + 真实样式表量过，不是看图推断。

### 1. `.settings-form input` 选择器泄漏到权限复选框（严重）

`dev/static/css/style.css:96`：

```css
.settings-form input { width: 100%; min-height: var(--btn-h); padding: 6px 8px;
  border: 1px solid var(--border-color); border-radius: var(--radius-sm);
  background: var(--bg-primary); color: var(--text-primary); }
```

按**元素名**匹配，因此也命中了 `#settingsUserRoots` 内的 `<input type="checkbox">`。实测（1280px 视口，fieldset 宽 308px）：

| 量 | 实测值 |
|---|---|
| 复选框尺寸 | **308 × 30**（应为 13 × 13 左右的自然尺寸） |
| 外层 `<label>` 高度 | **54.5px**（标签文字被挤到方块下一行） |
| `accent-color` | `auto`（渲染成 UA 蓝，与品牌 teal 不符） |
| `background` | `rgb(248,250,252)` = `--bg-primary` |

结果就是评审截图里那个"勾选框独占一行、文字掉到下一行"的布局。

站内已有正确做法可比照：`style.css:958` `.list-item .list-check { accent-color: var(--accent); }`。

### 2. 行内「编辑 / 删除」是未挂类的 UA 默认按钮（严重）

`dev/static/js/app.js:3224` 与 `:3237` 用 `document.createElement('button')` 创建，**没有赋任何 className**：

```js
var edit = document.createElement('button');
edit.type = 'button'; edit.textContent = '编辑';
```

全站**没有 `button {}` 基类规则**，只有 `.btn` 这个类。唯一修饰是 `.settings-root button { font-size: 12px; }`。因此这两个按钮渲染为浏览器默认外观——**而同一个模态里的表单按钮用的是 `.btn .btn-primary` / `.btn .btn-secondary`**，两套外观并存。

附带后果：`删除` 不可逆，却与 `编辑` 完全同权。站内另有两处 `.danger` 先例（`style.css:843` card-actions、`style.css:1369` batch-actions）。

### 3. 占位符当标签（严重，可访问性）

`index.html:311-330` 的全部输入只有 `placeholder`，没有任何 `<label for>`：

- `settingsRootId` / `settingsRootLabel` / `settingsRootDir` / `settingsRootAgent`
- `settingsUsername` / `settingsPassword`

违反 WCAG 3.3.2（Labels or Instructions）。占位符在输入后消失，表单不再自我说明——管理员回头核对"这条 root 的 agent 填的是什么"时无从对照。

`#settingsUserRoots` 的 fieldset 有 `aria-label="可访问 Rootdir"`，是这一片里唯一正确的。

### 4. 两个 tab 的列表行样式分裂（一致性）

```css
.settings-user { ... padding:8px 0; border-bottom:1px solid var(--border-color); }  /* 有分隔线 */
.settings-root { ... padding: 6px 0; font-size: 13px; }                            /* 无分隔线 */
```

同一模态、同一层级的两个列表，一个有分隔线一个没有。

### 5. 深色模式下自动填充压过主题（一致性）

全站 **0 处** `-webkit-autofill` 覆盖。实测截图里 `settingsUsername` 是浅底、紧邻的 `settingsPassword` 是深底——Chrome 的自动填充底色赢了 `--bg-primary`。

### 6. 删除确认绕开统一模态系统（一致性）

`css/style.css` 开头即声明 "Unified Modal System"，而 `app.js:3238` 的删除用户确认走 `window.confirm`。视觉与焦点管理都不在同一套里。

## 范围

**包含**：上述 6 项、以及两项顺手可修的打磨（列表行信息层级、空授权值的破折号）。

**不包含**：

- **`window.confirm` 的替换**。站内统一模态系统是否已有可复用的确认对话框 API，需要先查；若没有，新建一个确认组件超出本次范围。本次只**记录**该问题。
- **创建/编辑共用一个表单**的双角色设计。这是一个需要真实使用数据才能定的问题（管理员以创建为主还是以编辑为主？），不是设计原则能定的。留给后续调研，不在本次改动。
- 设置面板以外的任何界面。

## 设计

### 1. 收窄选择器，复选框归位

```css
/* style.css:96 —— 排除复选框：一行控件的尺寸规则不该跨控件类型套用 */
.settings-form input:not([type="checkbox"]) { width: 100%; min-height: var(--btn-h); padding: 6px 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--bg-primary); color: var(--text-primary); }

/* 复选框回到自然尺寸，并对齐站内既有的 accent-color 用法（style.css:958） */
#settingsUserRoots input[type="checkbox"] { width: auto; min-height: 0; padding: 0; margin: 0 6px 0 0; accent-color: var(--accent); }
```

`#settingsUserRoots { display: flex; flex-direction: column; gap: 4px; }`（`style.css:109`）保持不变——它本来就是对的，是被内层控件撑坏的。

### 2. 行内按钮归入 `.btn`，删除补危险态

```js
edit.className = 'btn btn-secondary';
remove.className = 'btn btn-secondary danger';
```

```css
/* 与 card-actions / batch-actions 的既有写法对齐 */
.settings-root button.danger, .settings-user button.danger { color: var(--danger); border-color: var(--danger-border); }
.settings-root button.danger:hover, .settings-user button.danger:hover { background: var(--danger-bg); border-color: var(--danger); }
```

`.settings-root button { font-size: 12px; }` 保留（`.btn` 的字号更大，行内按钮应更紧凑），但它不再是无类名按钮的唯一修饰。

### 3. 可见标签

给每个输入加 `<label for>`，视觉上保持现在的紧凑感——用站内已有的 sr-only 模式还是可见小标签，**取决于站内是否已有此类工具类**（实现前先查 `style.css` 与 `preview.html`）。若没有，倾向加**可见的 12px `--text-secondary` 标签**，因为管理员在长表单里核对字段时可见标签更有用，而这正是本次要修的场景。

字段文案沿用现有 placeholder 的文字（`显示名`、`目录（相对系统根目录）`、`Agent（默认 default）` 等），只是从占位符升格为标签，外加保留同样的 placeholder 作为示例。

### 4. 列表行统一

让 `.settings-root` 与 `.settings-user` 共用同一套行样式。两者唯一的实质差异是 `.settings-root` 不需要 `justify-content: space-between` 之外的布局差别——实现时提取一个共用声明块，两个选择器并列，不新建 class。

### 5. 自动填充跟随主题

```css
.settings-form input:-webkit-autofill,
.settings-form input:-webkit-autofill:hover,
.settings-form input:-webkit-autofill:focus {
  -webkit-box-shadow: 0 0 0 1000px var(--bg-primary) inset;
  -webkit-text-fill-color: var(--text-primary);
  caret-color: var(--text-primary);
}
```

### 6. 顺手打磨

- 空授权值：`app.js:3223` 的 `(granted || '—')` 在无授权时渲染出 `admin（管理员）· —`，读起来像故障。改为整段省略分隔符与破折号。
- `浏览…` 是 `.btn`，但作为 grid 项被拉伸成整行宽，看起来像输入框而非动作。让它不与输入框同宽（靠左、自然宽度）。

## 测试

| 断言 | 类型 |
|---|---|
| `.settings-form input` 规则不再命中复选框（选择器含 `:not([type="checkbox"])`） | 契约（读 CSS 源码） |
| `#settingsUserRoots input[type="checkbox"]` 重置了 `width`/`min-height` | 契约 |
| 行内按钮被赋予 `.btn`，删除含 `danger` | 契约（读 app.js 源码） |
| 每个设置表单输入都有对应的 `<label for>` | 契约 |
| `.settings-root` 与 `.settings-user` 声明在同一组选择器内 | 契约 |
| `-webkit-autofill` 覆盖存在且用 `--bg-primary` | 契约 |
| 打开设置 → 用户管理，实测复选框宽高为自然尺寸、label 高度 < 30px | e2e（真实浏览器，量 `getBoundingClientRect`） |
| 深色模式下 `settingsUsername` 与 `settingsPassword` 背景一致 | e2e（含自动填充场景，若可稳定构造） |

现有 `tests/test_settings_frontend_contract.py` 是同类契约测试的既有位置，新增断言优先并入该文件；仅当主题明显不同时才新建文件。

## 未决问题

- **创建/编辑共用表单**是否值得拆开，需要真实使用数据（管理员以创建为主还是以编辑为主？）。这不是设计原则能定的，本次不动。

## 已查证并据此定稿

- **站内没有 sr-only / visually-hidden 工具类**（`css/` 全量检索为空）。因此第 3 项用**可见的 12px `--text-secondary` 标签**，不新建工具类——而且管理员在长表单里核对字段时，可见标签本来就比占位符有用，这正是本次要修的场景。
- **站内没有可复用的确认对话框**：`.modal-overlay` 这套统一模态系统只提供容器，没有 confirm API；`window.confirm` 在 `app.js` 里用了 4 处。因此替换它意味着新建一个确认组件，**确认超出本次范围**——第 6 项只在范围里保留"记录该问题"。
