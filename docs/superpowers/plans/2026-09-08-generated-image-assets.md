# Controlled Generated Image Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled image-generation workspace to ClawMate image previews, using configured Agent/CLI backends and explicit user adoption.

**Architecture:** A new `generated_assets` service owns validated task metadata, source-adjacent candidate directories, result ingestion, manifest persistence, and cleanup. A dedicated API router launches existing `TaskExecutor` backends through a file contract. A lazily loaded, registry-backed preview panel exposes image-only creation, review, adoption and follow-up editing without changing existing source images.

**Tech Stack:** FastAPI, Pydantic request models, Python `pathlib`/JSON, existing `TaskExecutor`, vanilla JavaScript/CSS, existing `ClawMatePanels` registry, pytest and the repository Playwright workflow.

**Spec:** `docs/superpowers/specs/2026-09-08-generated-image-assets-design.md`

## Global Constraints

- Do not call OpenAI Platform APIs or expose any model credential to the browser.
- Use the configured `codex`, `claude`, `openclaw`, or `auto` Agent backend through the existing task-launch contract.
- Source images are never overwritten; candidate count is exactly constrained to 1--4.
- Candidate files live at `<source-directory>/candidates/<task-id>/`; task metadata lives at `.clawmate/generated-tasks/<task-id>/`.
- Accept only server-created task directories and validated image files; never accept Base64 or arbitrary output paths.
- Save adopted assets only to `assets/generated/<sanitized-topic>/` and append their provenance to `manifest.json`.
- Show an original generation prompt from manifest when available; show `未记录` otherwise.
- Reuse `ClawMatePanels`; every right-side panel has explicit grid placement, push layout, 40px header, `.panel-close-btn`, and mutual exclusion.
- File changes notify the user but do not auto-refresh an open preview.

---

## File Structure

- Create `dev/generated_assets.py`: pure task paths, request/result validation, image inspection, manifest reads/writes, adoption and cleanup.
- Create `dev/generated_asset_routes.py`: authenticated HTTP endpoints that resolve project context and call `GeneratedAssetService` plus `TaskExecutor`.
- Modify `dev/config.py` and `config.example.json`: typed generated-asset limits and allowed/default backend configuration without credentials.
- Modify `dev/main.py`: register the generated-asset router.
- Create `dev/static/js/image-assets-panel.js`: lazy, surface-scoped preview panel controller.
- Modify `dev/static/preview.html`, `dev/static/js/preview.js`, `dev/static/js/clawmate-panels.js`, and `dev/static/css/preview.css`: image-only entry point, explicit panel column and right-panel coordination.
- Create `tests/test_generated_assets.py`: service and route boundary regressions.
- Create `tests/test_generated_asset_frontend.py`: static/Node panel and layout contracts.
- Modify `tests/test_e2e_browser.py`: browser flow for image edit task review with a test double.

### Task 1: Define generated-asset configuration and pure service contract

**Files:**
- Create: `dev/generated_assets.py`
- Modify: `dev/config.py`
- Modify: `config.example.json`
- Test: `tests/test_generated_assets.py`

**Interfaces:**
- Produces `GeneratedAssetRequest`, `GeneratedAssetResult`, `GeneratedAssetService.create_task()`, `read_result()`, `adopt_candidate()`, `source_prompt()` and `cleanup_expired()`.
- Consumes `service.safe_path()` and `service.find_project_marker()` only at route boundaries; pure service methods accept resolved project-local paths.

- [ ] **Step 1: Write failing service tests for source-adjacent candidates and bounded requests**

```python
def test_create_task_uses_source_directory_candidates_and_project_metadata(tmp_path: Path):
    project = _project(tmp_path)
    source = project / "art" / "source.png"
    source.parent.mkdir(); source.write_bytes(PNG_1X1)
    task = GeneratedAssetService(project).create_task(
        source_path=source, prompt="turn the cabin display blue",
        purpose="PRD", topic="cabin-ui", width=1024, height=1024,
        candidate_count=2, backend="codex", operator="admin",
    )
    assert task.candidate_dir == source.parent / "candidates" / task.id
    assert task.metadata_dir == project / ".clawmate" / "generated-tasks" / task.id
    assert json.loads((task.metadata_dir / "request.json").read_text())["candidate_count"] == 2

def test_create_task_rejects_more_than_four_candidates(tmp_path: Path):
    with pytest.raises(ValueError, match="candidate_count"):
        GeneratedAssetService(_project(tmp_path)).create_task(
            source_path=None, prompt="new cover", purpose="cover", topic="cover",
            width=1024, height=1024, candidate_count=5, backend="codex", operator="admin",
        )
```

- [ ] **Step 2: Run the focused tests and verify they fail because the module is absent**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -k create_task -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'generated_assets'`.

- [ ] **Step 3: Add typed configuration and the minimal task creation implementation**

```python
@dataclass
class GeneratedAssetsConfig:
    enabled: bool = True
    default_backend: str = "auto"
    allowed_backends: list[str] = field(default_factory=lambda: ["auto", "codex", "claude", "openclaw"])
    max_candidates: int = 4
    task_ttl_hours: int = 168
    allowed_extensions: list[str] = field(default_factory=lambda: ["png", "jpg", "jpeg", "webp"])

class GeneratedAssetService:
    def create_task(self, *, source_path: Path | None, prompt: str, purpose: str,
                    topic: str, width: int, height: int, candidate_count: int,
                    backend: str, operator: str) -> GeneratedAssetTask:
        self._validate_request(prompt, topic, width, height, candidate_count, backend)
        task = GeneratedAssetTask.new(self.project_dir, source_path, topic, prompt, purpose,
                                       width, height, candidate_count, backend, operator)
        task.metadata_dir.mkdir(parents=True, exist_ok=False)
        task.candidate_dir.mkdir(parents=True, exist_ok=False)
        self._write_json_atomic(task.metadata_dir / "request.json", task.request_payload())
        return task
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -k create_task -v`

Expected: PASS.

- [ ] **Step 5: Commit the service contract**

```bash
git add dev/generated_assets.py dev/config.py config.example.json tests/test_generated_assets.py
git commit -m "feat: add generated asset task contract"
```

### Task 2: Validate Agent result files and persist adopted asset provenance

**Files:**
- Modify: `dev/generated_assets.py`
- Modify: `tests/test_generated_assets.py`

**Interfaces:**
- Consumes `GeneratedAssetTask` from Task 1 and a `result.json` written only into its metadata directory.
- Produces `GeneratedAssetService.read_result(task_id) -> GeneratedAssetResult`, `adopt_candidate(task_id, candidate_id) -> AdoptedAsset`, and `source_prompt(path) -> str | None`.

- [ ] **Step 1: Write failing tests for hostile results, adoption, and original prompt lookup**

```python
def test_read_result_rejects_candidate_outside_server_created_directory(tmp_path: Path):
    service, task = _service_with_task(tmp_path)
    (task.metadata_dir / "result.json").write_text(json.dumps({"candidates": [
        {"id": "bad", "file": "../../secret.png", "summary": "bad"}
    ]}))
    with pytest.raises(ValueError, match="candidate"):
        service.read_result(task.id)

def test_adopt_candidate_copies_asset_and_records_prompt(tmp_path: Path):
    service, task = _service_with_valid_candidate(tmp_path, prompt="make it blue")
    adopted = service.adopt_candidate(task.id, "one")
    manifest = json.loads((adopted.path.parent / "manifest.json").read_text())
    assert adopted.path.is_file()
    assert manifest["assets"][-1]["generation_prompt"] == "make it blue"
    assert service.source_prompt(adopted.path) == "make it blue"
```

- [ ] **Step 2: Run the tests and verify expected failure**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -k 'result or adopt or prompt' -v`

Expected: FAIL because result ingestion and adoption are not implemented.

- [ ] **Step 3: Implement strict result validation and atomic manifest updates**

```python
def read_result(self, task_id: str) -> GeneratedAssetResult:
    task = self.load_task(task_id)
    raw = json.loads((task.metadata_dir / "result.json").read_text(encoding="utf-8"))
    candidates = [self._validated_candidate(task, item) for item in raw["candidates"]]
    if not 1 <= len(candidates) <= task.candidate_count:
        raise ValueError("candidate count is outside request limit")
    return GeneratedAssetResult(task=task, candidates=candidates)

def adopt_candidate(self, task_id: str, candidate_id: str) -> AdoptedAsset:
    result = self.read_result(task_id)
    candidate = next(item for item in result.candidates if item.id == candidate_id)
    target_dir = self.project_dir / "assets" / "generated" / self._safe_topic(result.task.topic)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = self._next_target_path(target_dir, candidate.file.name)
    shutil.copy2(candidate.file, target)
    self._append_manifest(target_dir, result.task, candidate, target)
    return AdoptedAsset(task_id=task_id, candidate_id=candidate_id, path=target)
```

- [ ] **Step 4: Run the focused tests and full generated-asset unit suite**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -v`

Expected: PASS.

- [ ] **Step 5: Commit provenance handling**

```bash
git add dev/generated_assets.py tests/test_generated_assets.py
git commit -m "feat: persist generated asset provenance"
```

### Task 3: Add authorized API endpoints and Agent/CLI dispatch

**Files:**
- Create: `dev/generated_asset_routes.py`
- Modify: `dev/main.py`
- Modify: `tests/test_generated_assets.py`

**Interfaces:**
- Consumes JSON bodies with `root`, `project`, `source_path`, `prompt`, `purpose`, `topic`, `width`, `height`, `candidate_count`, and optional `backend`.
- Produces `POST /api/clawmate/generated-assets/tasks`, `GET /api/clawmate/generated-assets/tasks/{task_id}`, `POST /api/clawmate/generated-assets/tasks/{task_id}/adopt`, and `GET /api/clawmate/generated-assets/source-prompt`.
- Calls `TaskExecutor.launch(task_run_id=task.id, message=build_agent_instruction(task), cwd=str(project_dir), root_id=root, backend=backend, name="clawmate-generated-asset")`.

- [ ] **Step 1: Write failing route tests for project scope and configured backend dispatch**

```python
def test_create_generated_asset_task_dispatches_selected_allowed_backend(client, monkeypatch):
    launched = {}
    monkeypatch.setattr(routes, "TaskExecutor", lambda cfg: _Executor(launched))
    response = client.post("/api/clawmate/generated-assets/tasks", json={
        "root": "demo", "project": "project", "source_path": "project/art/source.png",
        "prompt": "annotate the safety zone", "purpose": "review", "topic": "safety",
        "width": 1024, "height": 1024, "candidate_count": 2, "backend": "codex",
    })
    assert response.status_code == 201
    assert launched["backend"] == "codex"

def test_task_endpoint_rejects_source_outside_project(client):
    response = client.post("/api/clawmate/generated-assets/tasks", json={"root": "demo", "project": "project", "source_path": "other/x.png"})
    assert response.status_code == 403
```

- [ ] **Step 2: Run route tests and verify they fail because the router is absent**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -k 'endpoint or dispatch or outside_project' -v`

Expected: FAIL with 404 or import error.

- [ ] **Step 3: Implement router ownership and a file-contract-only Agent prompt**

```python
@router.post("/api/clawmate/generated-assets/tasks", status_code=201)
async def create_task(request: Request) -> dict:
    body = await request.json()
    root_dir, source, project_dir = _resolve_generated_asset_context(body)
    task = GeneratedAssetService(project_dir).create_task_from_payload(body, source, request.state.operator)
    receipt = TaskExecutor(load_cfg()).launch(
        task_run_id=task.id, message=build_agent_instruction(task), cwd=str(project_dir),
        root_id=str(body["root"]), backend=task.backend, name="clawmate-generated-asset")
    return {"task": task.public_payload(), "launch": receipt.payload()}
```

- [ ] **Step 4: Run route and existing task-executor tests**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py tests/test_task_executor.py -v`

Expected: PASS.

- [ ] **Step 5: Commit API and dispatch**

```bash
git add dev/generated_asset_routes.py dev/main.py tests/test_generated_assets.py
git commit -m "feat: dispatch controlled generated asset tasks"
```

### Task 4: Build the lazy registry-backed image asset panel

**Files:**
- Create: `dev/static/js/image-assets-panel.js`
- Modify: `dev/static/js/clawmate-panels.js`
- Modify: `dev/static/preview.html`
- Modify: `dev/static/js/preview.js`
- Modify: `dev/static/css/preview.css`
- Test: `tests/test_generated_asset_frontend.py`

**Interfaces:**
- Produces `window.ClawMateImageAssetsPanel.mount(options)` with `open()`, `close()`, `refresh()`, and `isOpen()`.
- Consumes `getContext() -> {root, project, file}`, `notify(message)`, and `fetch`; its task requests use Task 3 endpoints.
- Registers as `imageAssets` for the `preview` surface and closes `feedback`, `agent`, and `project` before opening.

- [ ] **Step 1: Write failing static and Node behavior tests**

```python
def test_image_asset_panel_is_lazy_registered_and_has_no_base64_transport():
    preview = PREVIEW_JS.read_text(encoding="utf-8")
    panel = PANEL_JS.read_text(encoding="utf-8")
    assert "loadImageAssetsPanel" in preview
    assert "ClawMatePanels.install('preview', {imageAssets:" in preview
    assert "data:image" not in panel
    assert "candidate_count" in panel and "Math.min(4" in panel

def test_image_asset_panel_has_explicit_push_grid_column_and_shared_close_button():
    css = PREVIEW_CSS.read_text(encoding="utf-8")
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert "#previewImageAssetsPanel { grid-column: 4;" in css
    assert 'id="previewImageAssetsPanel"' in html
    assert "panel-close-btn" in html
```

- [ ] **Step 2: Run frontend contract tests and verify they fail**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_asset_frontend.py -v`

Expected: FAIL because the panel and entry point do not exist.

- [ ] **Step 3: Implement the minimum preview UI and panel controller**

```javascript
function openImageAssets() {
  closePreviewRightPanelsExcept('imageAssets');
  return loadImageAssetsPanel().then(function () {
    return window.ClawMateImageAssetsPanel.mount({getContext: getImageAssetContext, notify: showToast}).open();
  });
}
```

Use `<input type="number" min="1" max="4">`, show source prompt or `未记录`, submit only paths and JSON fields, render candidate action buttons disabled until review state, and retain the current preview image unchanged.

- [ ] **Step 4: Run frontend contracts and related shared panel tests**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_asset_frontend.py tests/test_clawmate_panels.py tests/test_preview_agent_panel_layout.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the preview workspace**

```bash
git add dev/static/js/image-assets-panel.js dev/static/js/clawmate-panels.js dev/static/preview.html dev/static/js/preview.js dev/static/css/preview.css tests/test_generated_asset_frontend.py
git commit -m "feat: add generated asset preview workspace"
```

### Task 5: Verify lifecycle, cleanup and rendered behavior

**Files:**
- Modify: `dev/generated_assets.py`
- Modify: `dev/generated_asset_routes.py`
- Modify: `tests/test_generated_assets.py`
- Modify: `tests/test_e2e_browser.py`

**Interfaces:**
- Consumes task state snapshots and candidate directories from Tasks 1--3.
- Produces explicit `queued`, `running`, `awaiting_review`, `failed`, `cancelled`, and `adopted` API states; cleanup only removes expired, unadopted candidate and metadata directories.

- [ ] **Step 1: Write failing cleanup and browser-flow tests**

```python
def test_cleanup_removes_only_expired_unadopted_task_and_candidate_dir(tmp_path: Path):
    service, expired, adopted = _expired_and_adopted_tasks(tmp_path)
    service.cleanup_expired(now=FROZEN_NOW)
    assert not expired.metadata_dir.exists()
    assert not expired.candidate_dir.exists()
    assert adopted.metadata_dir.exists()

def test_image_preview_opens_asset_workspace(page: Page):
    page.goto(image_preview_url)
    page.get_by_role("button", name="编辑图片").click()
    expect(page.locator("#previewImageAssetsPanel")).to_be_visible()
    expect(page.get_by_text("原图生成提示词")).to_be_visible()
```

- [ ] **Step 2: Run focused tests and verify expected failure**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py -k cleanup -v`

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_e2e_browser.py -k image_preview_opens_asset_workspace -v`

Expected: FAIL until lifecycle cleanup and test fixture support are present.

- [ ] **Step 3: Implement cleanup and test fixture task completion**

```python
def cleanup_expired(self, *, now: datetime) -> list[str]:
    removed = []
    for task in self._iter_tasks():
        if task.expires_at > now or self._task_has_adopted_candidate(task):
            continue
        shutil.rmtree(task.candidate_dir, ignore_errors=True)
        shutil.rmtree(task.metadata_dir, ignore_errors=True)
        removed.append(task.id)
    return removed
```

Add `_complete_task_fixture(service, task)` in `tests/test_e2e_browser.py`: write `PNG_1X1` to `task.candidate_dir / "one.png"`, then write `{"candidates":[{"id":"one","file":"one.png","summary":"fixture","width":1,"height":1}]}` to `task.metadata_dir / "result.json"`; configure the route test double to return the fixture task instead of starting a real Agent/CLI.

- [ ] **Step 4: Run unit, frontend, and browser validation**

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_generated_assets.py tests/test_generated_asset_frontend.py -v`

Run: `PYTHONPATH=dev dev/.venv/bin/python -m pytest tests/test_e2e_browser.py -k 'image_preview or generated_asset' -v`

Expected: PASS. Then use the repository Playwright workflow on the running application to verify desktop and mobile: image preview -> 编辑图片 -> submit fixture task -> review candidate -> 采用 -> generated asset link; inspect console errors and confirm no automatic preview reload on file notification.

- [ ] **Step 5: Commit verification and lifecycle handling**

```bash
git add dev/generated_assets.py dev/generated_asset_routes.py tests/test_generated_assets.py tests/test_e2e_browser.py
git commit -m "test: cover generated asset lifecycle"
```
