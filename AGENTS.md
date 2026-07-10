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

## Testing Guidelines

Tests use `pytest`, FastAPI `TestClient`, `tmp_path`, and `monkeypatch`. Add regression coverage for behavior changes, especially route responses, session handling, filesystem boundaries, and frontend layout contracts. Keep tests deterministic and isolated from real user data. There is no coverage threshold; prioritize meaningful assertions for changed paths.

## Commit & Pull Request Guidelines

Recent history commonly uses concise Conventional Commit prefixes such as `feat:`, `fix:`, `refactor:`, and `style:`; use an imperative, narrowly scoped subject. Pull requests should explain the problem and solution, list validation performed, link relevant issues, and include screenshots or recordings for visible UI changes. Call out configuration, migration, or deployment impacts explicitly.

## Security & Configuration Tips

Do not commit `config.json`, credentials, tokens, password hashes, or real filesystem paths. Use `config.example.json` for safe examples and environment variables for deployment overrides.
