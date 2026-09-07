import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTILS = ROOT / "dev" / "static" / "js" / "utils.js"


def test_utils_are_pure_and_export_the_shared_contract():
    source = UTILS.read_text(encoding="utf-8")

    assert "global.utils = Object.freeze" in source
    assert "document" not in source
    assert "navigator" not in source


def test_utils_contract_handles_escaping_sizes_times_copy_and_toasts():
    script = """
const fs = require('fs');
const vm = require('vm');
const timers = [];
const context = { window: {}, setTimeout: (fn, delay) => timers.push({fn, delay}) };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const utils = context.window.utils;
(async () => {
  const writes = [];
  const statuses = [];
  let current = '';
  const copied = await utils.copyText(42, value => writes.push(value));
  const missingWriter = await utils.copyText('x');
  utils.showToast('ready', value => { current = value; statuses.push(value); }, () => current, 7);
  timers[0].fn();
  process.stdout.write(JSON.stringify({
    escaped: utils.escHtml('<&\\"\\\'>'),
    empty: utils.escHtml(null),
    sizes: [utils.formatSize(0), utils.formatSize(null), utils.formatSize(1024), utils.formatSize(1024 ** 3)],
    times: [utils.formatMtime(0), utils.formatMtime('bad'), utils.formatMtime(1)],
    copied, missingWriter, writes, statuses, delay: timers[0].delay
  }));
})();
"""
    env = {**os.environ, "TZ": "UTC"}
    completed = subprocess.run(
        ["node", "-e", script, str(UTILS)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.stdout == (
        '{"escaped":"&lt;&amp;&quot;&#039;&gt;","empty":"null",'
        '"sizes":["-","-","1.0 KB","1.0 GB"],'
        '"times":["-","-","1/1 00:00"],"copied":true,'
        '"missingWriter":false,"writes":["42"],"statuses":["ready",""],"delay":7}'
    )


def test_index_loads_utils_before_app_and_app_uses_shared_exports():
    index = (ROOT / "dev" / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "dev" / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert index.index('./js/utils.js') < index.index('./js/app.js')
    for name in ("escHtml", "formatSize", "formatMtime", "copyText", "showToast", "setStatus"):
        assert f"function {name}(" not in app
    assert "utils.escHtml(" in app
    assert "utils.formatSize(" in app
    assert "utils.formatMtime(" in app
    assert "utils.copyText(" in app
    assert "utils.showToast(" in app


def test_preview_and_share_load_utils_before_preview_common_without_duplicate_exports():
    preview = (ROOT / "dev" / "static" / "preview.html").read_text(encoding="utf-8")
    share = (ROOT / "dev" / "static" / "share-view.html").read_text(encoding="utf-8")
    common = (ROOT / "dev" / "static" / "js" / "preview-common.js").read_text(encoding="utf-8")
    index = (ROOT / "dev" / "static" / "index.html").read_text(encoding="utf-8")

    for page in (preview, share):
        assert page.index('./js/utils.js') < page.index('./js/preview-common.js')
    assert './js/preview-common.js' not in index
    for name in ("escHtml", "formatSize", "showToast", "copyText"):
        assert f"global.{name} =" not in common
    assert "global.utils.copyText" in common
