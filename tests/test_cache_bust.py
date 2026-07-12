from pathlib import Path

from dev.cache_bust import StaticCacheMiddleware


def test_html_cache_buster_versions_terminal_dist_assets(tmp_path: Path):
    terminal_js = tmp_path / "dist" / "terminal.js"
    terminal_css = tmp_path / "dist" / "terminal.css"
    terminal_js.parent.mkdir()
    terminal_js.write_text("js", encoding="utf-8")
    terminal_css.write_text("css", encoding="utf-8")

    html = (
        '<link rel="stylesheet" href="./dist/terminal.css">'
        '<script src="./dist/terminal.js" defer></script>'
    ).encode()

    rewritten = StaticCacheMiddleware(None, static_dir=str(tmp_path))._inject_mtime_versions(
        html, tmp_path
    ).decode()

    assert f'./dist/terminal.css?v={int(terminal_css.stat().st_mtime)}' in rewritten
    assert f'./dist/terminal.js?v={int(terminal_js.stat().st_mtime)}' in rewritten


def test_html_cache_buster_versions_preview_vendor_assets(tmp_path: Path):
    highlight_js = tmp_path / "vendor" / "highlight.min.js"
    highlight_css = tmp_path / "vendor" / "github.min.css"
    highlight_js.parent.mkdir()
    highlight_js.write_text("js", encoding="utf-8")
    highlight_css.write_text("css", encoding="utf-8")
    html = (
        '<link rel="stylesheet" href="./vendor/github.min.css">'
        '<script src="./vendor/highlight.min.js" defer></script>'
    ).encode()

    rewritten = StaticCacheMiddleware(None, static_dir=str(tmp_path))._inject_mtime_versions(
        html, tmp_path
    ).decode()

    assert f'./vendor/github.min.css?v={int(highlight_css.stat().st_mtime)}' in rewritten
    assert f'./vendor/highlight.min.js?v={int(highlight_js.stat().st_mtime)}' in rewritten
