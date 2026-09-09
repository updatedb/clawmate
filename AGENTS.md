# Repository Guidelines

## Project Structure & Module Organization

ClawMate is a FastAPI service with a framework-free frontend. Backend modules live in `dev/`: `main.py` creates the application, `*_routes.py` files define endpoints, and service/configuration logic lives in modules such as `service.py`, `store.py`, and `config.py`. Browser assets are under `dev/static/` (`js/`, `css/`, vendor libraries, and HTML). Tests belong in `tests/`; use `scripts/` for maintenance utilities. Deployment files are at the repository root, while screenshots and documentation live in `assets/` and `docs/`.

## Build, Test, and Development Commands

- `cp config.example.json config.json` creates a local configuration; update root paths and service URLs before starting.
- `python3 -m venv dev/.venv && dev/.venv/bin/pip install -r requirements.txt` prepares the Python environment.
- `cd dev && .venv/bin/python main.py` starts the service on the configured port (5533 by default).
- `dev/.venv/bin/python -m pytest` runs the test suite from the repository root. Install `pytest` if needed.
- `docker build -t clawmate:latest .` verifies the production image. `docker compose up -d` runs the configured container stack.

## Coding Style & Naming Conventions

Use four-space indentation and type annotations for new Python code. Follow existing module boundaries: route modules handle HTTP concerns, while reusable filesystem or business logic belongs in services or stores. Name Python functions and files with `snake_case`, classes with `PascalCase`, and tests `test_<behavior>`. Frontend code uses vanilla JavaScript and CSS; preserve the local formatting and reuse tokens from `dev/static/css/tokens.css`. No repository-wide formatter or linter is currently enforced, so keep diffs focused and consistent with neighboring code.

## Frontend Panel Layout Conventions

Side panels (TOC/大纲, feedback/review 反馈/评审, Agent 终端, project 项目面板) share a single layout model across `preview.html`, `share-view.html`, and `index.html`:

- Each page is a CSS grid: `<left panel> <main 1fr> <right panels...>`. The main content always occupies the `1fr` column.
- Every grid item must declare an explicit `grid-column` (never rely on auto-placement) — otherwise the main column collapses when a sibling panel is hidden.
- Panels **push** content: their grid column expands from `0px` to their width when open (grid reflow), rather than floating over it. No `position: fixed`/overlay panels except a mobile-only fallback.
- A single grid-update function drives `grid-template-columns` from the current open/closed state of each panel.
- **Mutual exclusion**: only one right-side panel (feedback / agent / project) is open at a time — opening one closes the others.
- Close buttons use the shared `.panel-close-btn` (a 14px SVG "✕"); panel headers have uniform `height: 48px; box-sizing: border-box; align-items: center` and a plain title (13px/600/text-primary).

Any new side panel must follow this same pattern: grid-column push + explicit `grid-column` + mutual exclusion + `.panel-close-btn` + 48px header.

## Frontend Naming & CSS Conventions

Conventions for new frontend code. Existing code was not migrated wholesale (high churn / risk); apply these when writing new markup/JS/CSS or touching existing lines.

### Element IDs (camelCase, type-suffix driven)

- **Button**: `btn<Action><Object>` — always the `btn` prefix. `btnToggleSidebar` / `btnCloseAgent` / `btnCopyFilename`.
  - Action verbs: Toggle / Open / Close / Copy / Refresh / Search / Clear / New / Add / Delete / Move / Rename / Download / Share / Select / Back / Submit / Cancel / Confirm.
- **Panel**: `<Area>Panel` (index/shared unprefixed; `preview<Area>Panel`, `share<Area>Panel` for the preview/share pages). `projectPanel` / `agentPanel` / `previewAgentPanel` / `tocPanel` / `feedbackPanel`.
- **Panel body**: `<Area>PanelBody`. `projectPanelBody` / `tocPanelBody`.
- **List**: `<Area>List`. `dirList` / `cardList` / `cpList`.
- **Column**: kebab CSS class `.content-col`; as an ID use `<area>Col` (avoid camel `shareThreeCol`).
- **Select**: `<Area>Select`. `rootSelect` / `agentBackendSelect`.
- **Wrap / Modal / Input / Status / Menu**: `<Area>` + `Wrap` / `Modal` / `Input` / `Status` / `Menu`. `pathTitleWrap` / `versionModal` / `agentChatInput` / `indexMoreMenu`.

### CSS classes (kebab-case + surface prefix + BEM-lite)

- **Block**: kebab-case noun — `agent-panel`, `project-card`, `preview-left`, `share-right`, `cp-box`, `fb-card`.
- **Surface prefix** for cross-page shared components: `preview-`, `share-`, `cp-`, `fb-`, `agent-`, `pst-`, `cmd-`. **Unprefixed = index/shared** (`topbar`, `content-col`, `dir-list`, `panel-close-btn`).
- **Element** (child of a block): flat kebab `block-element` — `project-panel-header`, `cp-card-name`, `agent-history-item-title`.
- **State classes**: `.active`, `.hidden`, `.is-selected`.
- **Sizing/tiers**: always via design tokens (`--btn-h-lg/h/sm`, `--radius-*`, `--bg-*`); no magic numbers. Button height tiers: 34 (`--btn-h-lg`) icons / 30 (`--btn-h`) standard / 26 (`--btn-h-sm`) compact.
- `:root`-level tokens live in `dev/static/css/tokens.css`; surfaces must not define their own hardcoded sizes/colors if a token exists.

## Testing Guidelines

Tests use `pytest`, FastAPI `TestClient`, `tmp_path`, and `monkeypatch`. Add regression coverage for behavior changes, especially route responses, session handling, filesystem boundaries, and frontend layout contracts. Keep tests deterministic and isolated from real user data. There is no coverage threshold; prioritize meaningful assertions for changed paths.

## Commit & Pull Request Guidelines

Recent history commonly uses concise Conventional Commit prefixes such as `feat:`, `fix:`, `refactor:`, and `style:`; use an imperative, narrowly scoped subject. Pull requests should explain the problem and solution, list validation performed, link relevant issues, and include screenshots or recordings for visible UI changes. Call out configuration, migration, or deployment impacts explicitly.

## Release & Push Rule (docs-first)

Before **publishing to GitHub** (a push that updates `main` or a release tag), first complete project-documentation maintenance:

1. **CHANGELOG.md** — add a `## vX.Y (YYYY-MM-DD)` entry dated today that summarizes the changes being pushed. This is the enforcee signal.
2. **README.md** — update only if user-facing behavior/features changed.
3. **AGENTS.md** — update only if repo conventions/contracts changed.

This file (AGENTS.md) is read by all agents (Claude reads CLAUDE.md/this file; **Codex reads AGENTS.md**), so the rule is visible to every agent that pushes.

The repo ships a **git pre-push hook** (`.githooks/pre-push`, activated via `git config core.hooksPath .githooks`) that **enforces** it for any push — by Claude, Codex, or a human CLI — by aborting a `main`/tag push whose newest commit is dated after the newest CHANGELOG entry. Feature / PR branch pushes are exempt (iterative, not a release).

- Install on a fresh clone: `git config core.hooksPath .githooks`
- Bypass: `git push --no-verify` (git-native, not a setting toggle)

## Security & Configuration Tips

Do not commit `config.json`, credentials, tokens, password hashes, or real filesystem paths. Use `config.example.json` for safe examples and environment variables for deployment overrides.
