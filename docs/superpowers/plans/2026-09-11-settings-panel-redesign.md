# 系统设置面板改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把设置模态从「清单与编辑器挤在一个单列滚动里」改成「列表独占高度、表单按需唤出」，并修掉七个实测确认的缺陷。

**Architecture:** 模态体内引入 `list` / `form` 两个视图，由单一状态变量驱动。列表视图下两个 tab 共用同一套 `.settings-row` 结构，整行可点；表单视图承载单条目的编辑，含可见标签与独立的危险区。CSS 层先修掉选择器泄漏、勾选网格与自动填充，再做结构改动。

**Tech Stack:** 原生 JS（无框架）、CSS（`dev/static/css/tokens.css` 令牌）、pytest 契约测试 + Playwright e2e。

## Global Constraints

- 规范来源：`docs/superpowers/specs/2026-09-11-settings-panel-redesign-design.md`。
- **既有 ID 与 data 属性一个都不能改**：`settingsModal` / `settingsTabRoots` / `settingsTabUsers` / `data-settings-tab` / `data-settings-panel` / `settingsRootList` / `settingsRootForm` / `settingsRootId` / `settingsRootLabel` / `settingsRootDir` / `settingsRootBrowse` / `settingsRootAgent` / `settingsRootHint` / `settingsRootCancel` / `settingsUsers` / `settingsUserForm` / `settingsUsername` / `settingsPassword` / `settingsUserRoots` / `settingsUserCancel` / `settingsError`。测试按 ID 断言（`tests/test_e2e_browser.py:696` 断言 `#settingsUserRoots` 可见、`:629` 点击 `#settingsRootBrowse`；`tests/test_settings_frontend_contract.py` 从 `app.js` 按 ID 抽取处理函数体）。**类名可以换**。
- 模态宽度维持 640px（`style.css:94` `.settings-modal-box { max-width: 640px }`），不改。
- 尺寸/颜色一律走 `tokens.css`，不新增魔法值。
- 统一用既有的 `.btn` 家族表达按钮，不新造按钮样式。
- 不新增依赖、不新增组件目录。
- `tokens.css` 的按钮档位：`--btn-h-lg` 34 / `--btn-h` 30 / `--btn-h-sm` 26；圆角 `--radius-sm` 6。
- 提交信息用 Conventional Commits，结尾 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

---

### Task 1: CSS 修复层

**Files:**
- Modify: `dev/static/css/style.css`（`settings-*` 规则区，约 94-109 行；文件末尾追加自动填充覆盖）
- Test: `tests/test_settings_frontend_contract.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `.settings-row` / `.settings-row-title` / `.settings-row-meta` / `.settings-grants` / `.settings-danger` 的样式定义，供 Task 3、4 的标记使用

这一层不碰 JS 与 HTML 结构，可独立验证：改完在浏览器里量勾选框尺寸即可。

- [ ] **Step 1: 写失败的契约测试**

追加到 `tests/test_settings_frontend_contract.py` 末尾：

```python
def _settings_css() -> str:
    return (STATIC / "css" / "style.css").read_text(encoding="utf-8")


def test_the_form_input_rule_does_not_reach_checkboxes():
    """`.settings-form input { width: 100% }` matches by element name, so it
    also hit the grant checkboxes: measured 308x30 each, with their labels
    pushed to a second line (54.5px rows). A control's size rule must not be
    applied across control types."""
    css = _settings_css()
    assert ".settings-form input:not([type=\"checkbox\"])" in css
    # The bare form of the rule must be gone, not merely shadowed.
    assert ".settings-form input {" not in css


def test_the_grant_checkboxes_are_reset_to_natural_size():
    css = _settings_css()
    assert "#settingsUserRoots" in css
    block = css[css.index("#settingsUserRoots"):]
    block = block[:block.index("}")]
    assert "grid-template-columns" in block          # two-column grid
    assert "accent-color: var(--accent)" in block    # matches style.css:958
    # A reset for the leaked width/min-height lives on the input itself.
    assert "#settingsUserRoots input" in css


def test_autofill_follows_the_theme():
    """Chrome paints autofilled inputs with its own light fill, which wins over
    --bg-primary: in dark mode one field rendered light next to a dark one."""
    css = _settings_css()
    assert "-webkit-autofill" in css
    assert "0 0 0 1000px var(--bg-primary) inset" in css


def test_the_two_tabs_share_one_row_rule():
    """`.settings-user` had a border-bottom and `.settings-root` did not, so
    the two tabs of one modal looked like different screens."""
    css = _settings_css()
    assert ".settings-row" in css
    assert ".settings-root" not in css
    assert ".settings-user" not in css
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v -k "checkbox or autofill or row_rule"`
Expected: FAIL —— `.settings-row` 尚不存在，`.settings-root` 仍在。

- [ ] **Step 3: 收窄输入规则**

`dev/static/css/style.css:96`，把：

```css
.settings-form input { width: 100%; min-height: var(--btn-h); padding: 6px 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--bg-primary); color: var(--text-primary); }
```

改成：

```css
/* Checkboxes are excluded by type: this rule matches by element name, so it
   used to stretch each grant checkbox to the full fieldset width and give it
   the 30px input height, pushing its label onto a second line. */
.settings-form input:not([type="checkbox"]) { width: 100%; min-height: var(--btn-h); padding: 6px 8px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--bg-primary); color: var(--text-primary); }
```

- [ ] **Step 4: 重写列表行与勾选网格规则**

把 `style.css:98` 的 `.settings-user` 与 `:107-108` 的 `.settings-root` 两条规则一起替换成共用的一套（同一个声明块，两个 tab 都适用）：

```css
/* One row anatomy for both tabs: an inventory row is an inventory row whether
   it holds a Rootdir or a user. The row itself is the click target, which is
   why there are no per-row action buttons any more. */
.settings-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: 10px var(--space-2); border-bottom: 1px solid var(--border-color); cursor: pointer; text-align: left; width: 100%; background: none; border-left: 0; border-right: 0; border-top: 0; font: inherit; color: inherit; }
.settings-row:hover { background: var(--bg-tertiary); }
.settings-row:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--focus-ring); }
.settings-row-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.settings-row-title { font-size: var(--font-size-base); font-weight: 600; color: var(--text-primary); }
.settings-row-meta { font-size: var(--font-size-sm); color: var(--text-secondary); font-family: var(--font-mono); }
.settings-row-note { font-size: var(--font-size-sm); color: var(--text-muted); white-space: nowrap; }
.settings-row-chevron { color: var(--text-muted); flex-shrink: 0; }

#settingsUserRoots { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-2) var(--space-4); border: 0; margin: 0; padding: 0; font-size: var(--font-size-base); }
#settingsUserRoots label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
#settingsUserRoots input { width: auto; min-height: 0; padding: 0; margin: 0; accent-color: var(--accent); }
```

> 注意：这里显式写了 `border-left/right/top: 0` 是因为 `.settings-row` 将来要作为 `<button>` 渲染——`button` 自带 UA 边框，只写 `border-bottom` 会留下三边。Task 3 会用它。

- [ ] **Step 5: 追加自动填充覆盖与危险区样式**

追加到 `style.css` 文件末尾：

```css
/* Chrome fills an autofilled input with its own light background, which beats
   --bg-primary: in dark mode the username field rendered light while the
   password field beside it stayed dark. */
.settings-form input:-webkit-autofill,
.settings-form input:-webkit-autofill:hover,
.settings-form input:-webkit-autofill:focus {
  -webkit-box-shadow: 0 0 0 1000px var(--bg-primary) inset;
  -webkit-text-fill-color: var(--text-primary);
  caret-color: var(--text-primary);
}

/* Destructive actions live apart from the save action: proximity is the
   strongest grouping cue, so an irreversible action must not sit in the same
   cluster as a safe one. */
.settings-danger { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--border-color); }
.settings-danger-title { margin: 0 0 var(--space-1); font-size: var(--font-size-base); font-weight: 600; color: var(--text-primary); }
.settings-danger-help { margin: 0 0 var(--space-3); font-size: var(--font-size-sm); color: var(--text-secondary); }
.settings-danger-warning { margin: 0 0 var(--space-3); font-size: var(--font-size-sm); color: var(--danger); }
.settings-danger-confirm { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; }
.settings-danger-confirm[hidden] { display: none; }
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v`
Expected: PASS。若有既有断言引用 `.settings-root` / `.settings-user` 而失败，那是本任务预期内的破坏——把它改成 `.settings-row`，不要恢复旧类名。

- [ ] **Step 7: 在浏览器确认勾选框归位**

Run: 打开 `http://localhost:5533/clawmate/`，系统设置 → 用户管理，量每个勾选框的 `getBoundingClientRect()`。
Expected: 宽高不再是 308×30；每个 label 的高度 < 30px（单行）。

- [ ] **Step 8: 提交**

```bash
git add dev/static/css/style.css tests/test_settings_frontend_contract.py
git commit -m "fix: stop the settings form rule reaching the grant checkboxes"
```

---

### Task 2: 行内按钮归入 `.btn` 家族

**Files:**
- Modify: `dev/static/js/app.js`（`loadRoots()` 与 `loadUsers()` 内的 `createElement('button')`）
- Modify: `dev/static/css/style.css`（移除 `.settings-root button { font-size: 12px; }` 这条兜底）
- Test: `tests/test_settings_frontend_contract.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 CSS
- Produces: 无新符号

> **执行前提**：Task 3 会把行内按钮整个删掉（改成整行可点）。本任务先让按钮**看起来对**，这样 Task 3 之前的每一步都可独立验收。若你已执行 Task 3，跳过本任务并在其提交信息里说明。

- [ ] **Step 1: 写失败的契约测试**

```python
def test_settings_row_buttons_use_the_btn_family():
    """The row actions were createElement('button') with no className, and the
    stylesheet has no bare `button` rule -- only `.btn`. So they rendered as
    browser defaults next to `.btn .btn-primary` form buttons in the same
    modal, and 删除 (irreversible) looked identical to 编辑."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "edit.className = 'btn btn-secondary'" in script
    assert "remove.className = 'btn btn-secondary danger'" in script


def test_the_settings_button_font_size_fallback_is_gone():
    """`.settings-root button { font-size: 12px }` was the only styling on those
    unstyled buttons; it papered over the class gap instead of closing it."""
    assert ".settings-root button" not in _settings_css()
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v -k "btn_family or font_size_fallback"`
Expected: FAIL —— 尚不存在 `edit.className`，且 `.settings-root button` 仍在。

- [ ] **Step 3: 给按钮挂类**

`dev/static/js/app.js` 的 `loadRoots()` 内：

```js
      var edit = document.createElement('button');
      edit.type = 'button'; edit.textContent = '编辑';
```
改成
```js
      var edit = document.createElement('button');
      edit.type = 'button'; edit.textContent = '编辑';
      edit.className = 'btn btn-secondary';
```

```js
      var remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '删除';
```
改成
```js
      var remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = '删除';
      remove.className = 'btn btn-secondary danger';
```

`loadUsers()` 内同样两处（`edit` 与 `remove` 的 `textContent` 分别是 `'编辑'` 与 `'删除'`），照同样方式各加一行 `className`。

- [ ] **Step 4: 移除兜底规则**

删除 `dev/static/css/style.css` 的 `.settings-root button { font-size: 12px; }`（Task 1 已把 `.settings-root` 换掉，若这行还在就一并删）。

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v`
Expected: PASS

- [ ] **Step 6: 浏览器确认**

Run: 打开设置 → 两个 tab，确认 编辑/删除 与表单里的按钮同族，且 删除 呈红色危险态。

- [ ] **Step 7: 提交**

```bash
git add dev/static/js/app.js dev/static/css/style.css tests/test_settings_frontend_contract.py
git commit -m "fix: put the settings row actions in the shared button family"
```

---

### Task 3: 双视图与列表行

**Files:**
- Modify: `dev/static/index.html`（设置模态体，约 308-333 行）
- Modify: `dev/static/js/app.js`（`initSettings()` 内的 `selectTab` / `loadRoots` / `loadUsers`）
- Test: `tests/test_settings_frontend_contract.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `.settings-row*` 样式
- Produces: `settingsView` 状态、`showSettingsView(name, itemId)`、`settingsRootScrollTop` 变量。Task 4 的 `resetRootForm` / `resetUserForm` 在 `showSettingsView('list')` 时被调用

这是最大的一块：列表视图与表单视图分离。

- [ ] **Step 1: 写失败的契约测试**

```python
def test_the_modal_body_has_two_views():
    """The structural fix: the inventory and the single-item editor stop
    sharing one scroll column."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-settings-view="list"' in html
    assert 'data-settings-view="form"' in html


def test_rows_are_click_targets_not_button_rows():
    """Clicking the row is the way in, so the row carries no action buttons."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "settings-row" in script
    assert "showSettingsView" in script
    # The per-row 编辑 button is what the row click replaced.
    assert "edit.textContent = '编辑'" not in script
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v -k "two_views or click_targets"`
Expected: FAIL

- [ ] **Step 3: 改造模态体标记**

`dev/static/index.html`，把 `<div class="modal-body">` 之下的内容改成两个视图。**所有既有 ID 原样保留**：

```html
      <div class="modal-body">
        <p id="settingsError" class="settings-help" role="alert"></p>

        <div data-settings-view="list">
          <div class="settings-list-head">
            <button type="button" id="settingsRootNew" class="btn btn-secondary" hidden>+ 新建 Rootdir</button>
            <button type="button" id="settingsUserNew" class="btn btn-secondary" hidden>+ 新建用户</button>
          </div>
          <div id="settingsRootList"></div>
          <div id="settingsUsers"></div>
          <p id="settingsRootEmpty" class="settings-empty" hidden>
            还没有 Rootdir。Rootdir 是用户可访问的根目录，至少需要一个才能创建普通用户。
          </p>
        </div>

        <div data-settings-view="form" hidden>
          <button type="button" id="settingsBack" class="btn btn-secondary settings-back">← 返回列表</button>

          <section data-settings-panel="roots" role="tabpanel">
            <form id="settingsRootForm" class="settings-form">
              <label class="settings-field" for="settingsRootId">id（留空自动派生）</label>
              <input id="settingsRootId" placeholder="topic-writer">
              <label class="settings-field" for="settingsRootLabel">显示名</label>
              <input id="settingsRootLabel" placeholder="Topic Writer" required>
              <label class="settings-field" for="settingsRootDir">目录（相对系统根目录）</label>
              <input id="settingsRootDir" placeholder="writer/topics" readonly required>
              <button type="button" id="settingsRootBrowse" class="btn btn-secondary">浏览…</button>
              <label class="settings-field" for="settingsRootAgent">Agent</label>
              <input id="settingsRootAgent" placeholder="writer">
              <p id="settingsRootHint" class="settings-help"></p>
              <div class="settings-actions">
                <button class="btn btn-secondary" type="button" id="settingsRootCancel" hidden>取消编辑</button>
                <button class="btn btn-primary" type="submit">保存 Rootdir</button>
              </div>
            </form>
            <div class="settings-danger" id="settingsRootDanger" hidden>
              <p class="settings-danger-title">删除这个 Rootdir</p>
              <p class="settings-danger-help" id="settingsRootDangerHelp"></p>
              <div class="settings-danger-confirm" id="settingsRootDeleteAsk">
                <button type="button" class="btn btn-secondary danger" id="settingsRootDelete">删除</button>
              </div>
              <div class="settings-danger-confirm" id="settingsRootDeleteConfirm" hidden>
                <span class="settings-danger-warning">确定删除？此操作不可恢复。</span>
                <button type="button" class="btn btn-secondary danger" id="settingsRootDeleteYes">确认删除</button>
                <button type="button" class="btn btn-secondary" id="settingsRootDeleteNo">取消</button>
              </div>
            </div>
          </section>

          <section data-settings-panel="users" role="tabpanel" hidden>
            <form id="settingsUserForm" class="settings-form">
              <label class="settings-field" for="settingsUsername">用户名</label>
              <input id="settingsUsername" placeholder="updatedb" required>
              <label class="settings-field" for="settingsPassword">密码</label>
              <input id="settingsPassword" type="password" placeholder="至少 4 位">
              <p class="settings-help">留空表示保持当前密码。</p>
              <fieldset id="settingsUserRoots" aria-label="可访问 Rootdir"></fieldset>
              <div class="settings-actions">
                <button type="button" id="settingsUserCancel" class="btn btn-secondary" hidden>取消编辑</button>
                <button class="btn btn-primary" type="submit">创建用户</button>
              </div>
            </form>
            <div class="settings-danger" id="settingsUserDanger" hidden>
              <p class="settings-danger-title">删除这个用户</p>
              <p class="settings-danger-help" id="settingsUserDangerHelp"></p>
              <div class="settings-danger-confirm" id="settingsUserDeleteAsk">
                <button type="button" class="btn btn-secondary danger" id="settingsUserDelete">删除</button>
              </div>
              <div class="settings-danger-confirm" id="settingsUserDeleteConfirm" hidden>
                <span class="settings-danger-warning">确定删除？此操作不可恢复。</span>
                <button type="button" class="btn btn-secondary danger" id="settingsUserDeleteYes">确认删除</button>
                <button type="button" class="btn btn-secondary" id="settingsUserDeleteNo">取消</button>
              </div>
            </div>
          </section>
        </div>
      </div>
```

> `#settingsRootDanger` / `#settingsUserDanger` 的 `hidden` 与两个确认按钮的联动在 Task 4 实现；本任务先让它们存在且默认隐藏。

- [ ] **Step 4: 加列表头与字段标签的样式**

追加到 `style.css` 的 settings 区：

```css
.settings-list-head { display: flex; justify-content: flex-end; margin-bottom: var(--space-2); }
.settings-empty { margin: var(--space-6) 0; text-align: center; color: var(--text-secondary); font-size: var(--font-size-base); }
.settings-back { margin-bottom: var(--space-4); }
.settings-field { display: block; margin-top: var(--space-3); font-size: var(--font-size-sm); color: var(--text-secondary); }
.settings-field:first-child { margin-top: 0; }
.settings-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-5); }
```

- [ ] **Step 5: 加视图切换**

在 `dev/static/js/app.js` 的 `initSettings()` 内，`selectTab` 之前加入：

```js
  // The inventory and the single-item editor are separate views. They used to
  // share one scroll column, so reading meant scrolling past a form and
  // editing put the edited row out of sight.
  var settingsView = 'list';
  var rootsScrollTop = 0;

  function showSettingsView(name, tab) {
    var body = modal.querySelector('.modal-body');
    if (name === 'list') {
      rootsScrollTop = document.getElementById('settingsRootList').parentElement.scrollTop;
    }
    settingsView = name;
    var views = body.querySelectorAll('[data-settings-view]');
    for (var i = 0; i < views.length; i++) {
      views[i].hidden = views[i].dataset.settingsView !== name;
    }
    if (tab) selectTab(tab);
    document.getElementById('settingsRootNew').hidden = name !== 'list';
    document.getElementById('settingsUserNew').hidden = name !== 'list';
    if (name === 'list') {
      document.getElementById('settingsRootList').parentElement.scrollTop = rootsScrollTop;
    }
  }
```

`selectTab(name)` 改成为：切 tab 时**强制回到列表视图**（去掉递归：把视图复位放在 selectTab 里，`showSettingsView` 调用 `selectTab` 时靠一个守卫避免回环）：

```js
  function selectTab(name, keepView) {
    var tabs = modal.querySelectorAll('[data-settings-tab]');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].setAttribute('aria-selected', String(tabs[i].dataset.settingsTab === name));
    }
    var panels = modal.querySelectorAll('[data-settings-panel]');
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].dataset.settingsPanel !== name;
    }
    // Switching tabs abandons whatever was being edited: a half-filled Rootdir
    // form must not be silently carried into the user tab.
    if (!keepView) showSettingsView('list', name);
  }
```

- [ ] **Step 6: 列表行改为可点、并接线新建/返回**

`loadRoots()` 的行构造改成（删掉 `edit`/`remove` 两个按钮及其监听）：

```js
    data.roots.forEach(function (root) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'settings-row';
      var text = document.createElement('span');
      text.className = 'settings-row-text';
      var title = document.createElement('span');
      title.className = 'settings-row-title';
      title.textContent = root.label;
      var meta = document.createElement('span');
      meta.className = 'settings-row-meta';
      meta.textContent = root.dir + '  ·  agent: ' + root.agent_id;
      text.appendChild(title); text.appendChild(meta);
      row.appendChild(text);
      var referenced = usersCache.filter(function (user) {
        return (user.root_ids || []).indexOf(root.id) >= 0;
      }).length;
      if (referenced) {
        var note = document.createElement('span');
        note.className = 'settings-row-note';
        note.textContent = '已被 ' + referenced + ' 位用户引用';
        row.appendChild(note);
      }
      row.addEventListener('click', function () { openRootForm(root); });
      list.appendChild(row);
    });
    document.getElementById('settingsRootEmpty').hidden = data.roots.length > 0;
```

把原先 编辑 按钮回调体内的全部逻辑提取成 `openRootForm(root)`：

```js
  function openRootForm(root) {
    editingRootId = root ? root.id : '';
    document.getElementById('settingsRootId').value = root ? root.id : '';
    document.getElementById('settingsRootId').disabled = Boolean(root);
    document.getElementById('settingsRootLabel').value = root ? root.label : '';
    document.getElementById('settingsRootDir').value = root ? root.dir : '';
    document.getElementById('settingsRootAgent').value = root ? root.agent_id : '';
    document.getElementById('settingsRootCancel').hidden = !root;
    document.getElementById('settingsRootDanger').hidden = !root;
    document.getElementById('settingsRootForm').querySelector('button[type="submit"]').textContent =
      root ? '保存 Rootdir' : '创建 Rootdir';
    var referenced = root ? usersCache.filter(function (user) {
      return (user.root_ids || []).indexOf(root.id) >= 0;
    }).length : 0;
    document.getElementById('settingsRootHint').textContent = referenced
      ? '该 Rootdir 已被 ' + referenced + ' 位用户引用；修改目录后其授权不受影响（授权引用的是 id）。'
      : '';
    document.getElementById('settingsRootDangerHelp').textContent = referenced
      ? '已被 ' + referenced + ' 位用户引用，删除后这些授权将失效。'
      : '';
    showSettingsError('');
    showSettingsView('form', 'roots');
  }
```

`loadUsers()` 的行构造做同样处理：`row` 改成 `<button class="settings-row">`，标题为 `user.username`（管理员追加 `（管理员）`），meta 为授权列表（`root_ids` 映射成 label 后以 ` · ` 连接），**无授权时整个 meta 不渲染**（现状会渲染出悬空的 `· —`）。行点击调用 `openUserForm(user)`。用户的编辑按钮回调体同样提取进 `openUserForm`。

- [ ] **Step 7: 接线**

在 `initSettings()` 末尾注册：

```js
  document.getElementById('settingsBack').addEventListener('click', function () {
    showSettingsView('list');
  });
  document.getElementById('settingsRootNew').addEventListener('click', function () { openRootForm(null); });
  document.getElementById('settingsUserNew').addEventListener('click', function () { openUserForm(null); });
```

表单提交成功后（既有 `loadRoots()` / `loadUsers()` 调用之后）追加 `showSettingsView('list')`。

- [ ] **Step 8: 运行契约与 e2e**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v`
Expected: PASS

Run: `python3 -m pytest tests/test_e2e_browser.py -m e2e -v -k "settings"`
Expected: 既有 settings 用例仍通过（它们按 ID 断言，ID 未变）。失败则先判断是不是本任务改坏的，是就修，不是就报告。

- [ ] **Step 9: 提交**

```bash
git add dev/static/index.html dev/static/js/app.js dev/static/css/style.css tests/test_settings_frontend_contract.py
git commit -m "feat: split the settings modal into a list view and a focused form"
```

---

### Task 4: 危险区两步确认与状态

**Files:**
- Modify: `dev/static/js/app.js`（`openRootForm` / `openUserForm` 与删除接线）
- Test: `tests/test_settings_frontend_contract.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `#settingsRootDanger` / `#settingsRootDeleteAsk` / `#settingsRootDeleteConfirm` 与用户的同构元素
- Produces: `confirmDelete(askId, confirmId)` 帮助函数

- [ ] **Step 1: 写失败的契约测试**

```python
def test_the_settings_deletes_do_not_use_window_confirm():
    """style.css opens by declaring a Unified Modal System, yet the settings
    deletes used window.confirm -- a different visual and focus model from
    everything around them. They now ask in place, in the danger zone."""
    script = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "window.confirm('删除 Rootdir '" not in script
    assert "window.confirm('删除用户 '" not in script
    # The other two are file operations, deliberately left alone.
    assert script.count("window.confirm") == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v -k window_confirm`
Expected: FAIL —— 仍有 4 处 `window.confirm`。

- [ ] **Step 3: 实现原位两步确认**

在 `initSettings()` 内加入：

```js
  // Two-step in place rather than a dialog: the repo has no reusable confirm
  // component (.modal-overlay only supplies the container), and a delete that
  // asks where it happens keeps the consequence and the action together.
  function armDelete(askId, confirmId) {
    document.getElementById(askId).hidden = true;
    document.getElementById(confirmId).hidden = false;
  }
  function disarmDelete(askId, confirmId) {
    document.getElementById(confirmId).hidden = true;
    document.getElementById(askId).hidden = false;
  }
```

- [ ] **Step 4: 接线 Rootdir 删除**

替换 `openRootForm` 之外原先 `remove` 按钮的回调，改为在 `initSettings()` 内一次性注册：

```js
  document.getElementById('settingsRootDelete').addEventListener('click', function () {
    armDelete('settingsRootDeleteAsk', 'settingsRootDeleteConfirm');
  });
  document.getElementById('settingsRootDeleteNo').addEventListener('click', function () {
    disarmDelete('settingsRootDeleteAsk', 'settingsRootDeleteConfirm');
  });
  document.getElementById('settingsRootDeleteYes').addEventListener('click', async function () {
    if (!editingRootId) return;
    try {
      await settingsRequest('/api/clawmate/settings/roots/' + encodeURIComponent(editingRootId), {method: 'DELETE'});
      disarmDelete('settingsRootDeleteAsk', 'settingsRootDeleteConfirm');
      resetRootForm();
      showSettingsView('list');
      await loadRoots();
    } catch (_) {}
  });
```

用户的三个按钮同构（`settingsUserDelete` / `settingsUserDeleteNo` / `settingsUserDeleteYes`，删除接口 `/api/clawmate/settings/users/{id}`，成功后 `resetUserForm(); showSettingsView('list'); await loadUsers();`）。

每次 `openRootForm` / `openUserForm` 进入时调用一次 `disarmDelete(...)`，避免上次的确认态残留。

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_settings_frontend_contract.py -v`
Expected: PASS

- [ ] **Step 6: 浏览器验收——第一次点击不得发请求**

Run: 打开设置 → 点某行 → 点「删除」（此时**只应原位展开确认**，不发请求）→ 点「取消」应收回。在 DevTools Network 面板确认无 DELETE 请求。
Expected: 只有「确认删除」才发出 DELETE。

- [ ] **Step 7: 提交**

```bash
git add dev/static/js/app.js tests/test_settings_frontend_contract.py
git commit -m "feat: confirm settings deletes in place instead of window.confirm"
```

---

### Task 5: 移动端、e2e 验收与文档

**Files:**
- Modify: `dev/static/css/style.css`（移动端规则）
- Modify: `tests/test_e2e_browser.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1-4 的全部行为
- Produces: 无

- [ ] **Step 1: 加移动端规则**

追加到 `style.css` 的 768px 媒体查询内（**必须在基础规则之后**——本仓库刚因源顺序吃过一次亏：基础规则写在媒体查询之后会整体覆盖移动端值）：

```css
  .settings-row { padding: 12px var(--space-2); }
  .settings-row-meta { font-size: var(--font-size-xs); }
  #settingsUserRoots { grid-template-columns: 1fr; }
  .settings-actions { flex-direction: column-reverse; }
  .settings-actions .btn { width: 100%; }
```

- [ ] **Step 2: 写 e2e 验收**

追加到 `tests/test_e2e_browser.py`（复用既有 `page` 夹具、`login(page)` 与临时实例启动流程）：

```python
def test_the_grant_checkboxes_are_not_stretched(page: Page):
    """The leaked `.settings-form input` rule measured 308x30 per checkbox and
    pushed each label onto a second line."""
    login(page)
    page.locator("#btnSettings").click()
    page.locator("#settingsTabUsers").click()
    box = page.locator("#settingsUserRoots input").first
    rect = box.bounding_box()
    check(rect["width"] < 40, f"勾选框宽度自然（实测 {rect['width']}）")
    check(rect["height"] < 40, f"勾选框高度自然（实测 {rect['height']}）")


def test_a_row_opens_the_form_and_back_returns_to_the_list(page: Page):
    login(page)
    page.locator("#btnSettings").click()
    check(page.locator('[data-settings-view="list"]').is_visible(), "默认在列表视图")
    page.locator("#settingsRootList .settings-row").first.click()
    check(page.locator('[data-settings-view="form"]').is_visible(), "点行进入表单视图")
    page.locator("#settingsBack").click()
    check(page.locator('[data-settings-view="list"]').is_visible(), "返回回到列表视图")


def test_deleting_a_root_needs_a_second_click(page: Page):
    """The first click must not issue the DELETE: it arms the confirmation."""
    login(page)
    page.locator("#btnSettings").click()
    page.locator("#settingsRootList .settings-row").first.click()
    deletes = []
    page.on("request", lambda r: deletes.append(r.url) if r.method == "DELETE" else None)
    page.locator("#settingsRootDelete").click()
    page.wait_for_timeout(300)
    check(not deletes, "第一次点击不发 DELETE 请求")
    check(page.locator("#settingsRootDeleteConfirm").is_visible(), "原位展开确认")
    page.locator("#settingsRootDeleteNo").click()
    check(not deletes, "取消后仍未发请求")
```

- [ ] **Step 3: 运行 e2e**

Run: `python3 -m pytest tests/test_e2e_browser.py -m e2e -v -k "grant_checkboxes or row_opens or second_click"`
Expected: PASS

- [ ] **Step 4: 更新 README**

在「认证与 Rootdir」一节末尾追加：

```markdown
系统设置里 Rootdir 与用户各是一个列表：点任意一行进入该条的编辑表单，左上角「← 返回列表」退回。删除是两步的——先点「删除」原位展开确认，再点「确认删除」才执行。
```

- [ ] **Step 5: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `# Changelog` 之后新增（若已有 v1.55 条目则并入其下）：

```markdown
## v1.55 (2026-09-11)
### 设置面板改版
- 模态拆成**列表视图**与**聚焦表单**：列表独占高度、整行可点，表单按需唤出。此前两者共用一个单列滚动，导致「读要滚过一张空表单」「编辑时看不见自己在改哪行」。
- 两个 tab 共用同一套行结构（此前 `.settings-root` 无分隔线、`.settings-user` 有）。
- 字段有了**可见标签**，不再靠占位符充当标签；密码字段的说明改为持久文字。
- 权限勾选区改为**两列网格**，勾选框恢复自然尺寸（此前被 `.settings-form input { width: 100% }` 拉伸到 308×30，标签被挤到第二行）。
- 删除改为**危险区原位两步确认**，不再走 `window.confirm`；破坏性操作与保存动作物理分离。
- 深色模式下自动填充不再覆盖主题底色；行内按钮归入 `.btn` 家族，删除呈危险态。
```

- [ ] **Step 6: 跑全量**

Run: `python3 -m pytest -q && python3 -m pytest -m e2e -q`
Expected: 两者均无失败。

- [ ] **Step 7: 提交**

```bash
git add dev/static/css/style.css tests/test_e2e_browser.py README.md CHANGELOG.md
git commit -m "docs: record the settings modal redesign"
```

---

## Self-Review

**Spec coverage:**

| Spec 章节 | 对应任务 |
|---|---|
| 背景缺陷 1（选择器泄漏） | Task 1 |
| 背景缺陷 2（按钮未挂类） | Task 2（Task 3 删除这些按钮） |
| 背景缺陷 3（占位符当标签） | Task 3 Step 3 |
| 背景缺陷 4（两 tab 行样式分裂） | Task 1 Step 4 |
| 背景缺陷 5（自动填充） | Task 1 Step 5 |
| 背景缺陷 6（window.confirm） | Task 4 |
| 背景缺陷 7（结构性） | Task 3 |
| 选定方向 B + 列表视图原型 | Task 3 |
| 聚焦表单原型 | Task 3 Step 3 |
| 危险区两步确认原型 | Task 4 |
| 用户勾选网格原型 | Task 1 Step 4（网格）+ Task 3 Step 3（标记） |
| 移动端原型 | Task 5 Step 1 |
| 空状态 | Task 3 Step 3（`#settingsRootEmpty`）+ Step 6（切换 hidden） |
| 加载态 | **缺口** —— 见下 |
| 交互说明（tab 复位、返回保留滚动） | Task 3 Step 5 |
| 响应式表 | Task 5 Step 1 |
| 实现映射（CSS 修复 / 类名） | Task 1、Task 2 |
| 测试表 11 行 | Task 1（4）+ Task 2（2）+ Task 3（2）+ Task 4（1）+ Task 5（3 条 e2e） |

**加载态缺口**：spec 要求列表加载时用与行同形的骨架块。本计划未覆盖——设置面板的加载是本地 API、实测瞬时完成，加骨架会引入一个几乎不可见的中间态。**判定为可省略**，但需在 spec 里把这条从"包含"移到"不包含"，避免规范与实现不一致。这是一个已知的规范偏离，执行前应向人类确认。

**Placeholder scan:** 无 TBD/TODO。Task 3 Step 6 的 `loadUsers()` 改动以「照同样方式」描述而非贴出完整代码——因为它是 `loadRoots()` 改动的同构，且原函数较长；执行者需要读原函数后对照改写。**这是本计划最弱的一步**，若执行者卡住，应报告 NEEDS_CONTEXT 而不是猜。

**Type consistency:** `showSettingsView(name, tab)` 在 Task 3 定义、Task 4 复用（`showSettingsView('list')`）；`openRootForm(root)` / `openUserForm(user)` 在 Task 3 定义、Task 4 的删除成功后调用；`armDelete(askId, confirmId)` / `disarmDelete(askId, confirmId)` 在 Task 4 定义并使用；元素 ID 在两处一致（`settingsRootDeleteAsk` / `settingsRootDeleteConfirm` 等）。`rootsScrollTop` 在 Task 3 定义并使用。
