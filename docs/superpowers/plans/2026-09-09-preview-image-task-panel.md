# Preview Image Task Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Preview's controlled generated-asset panel into a two-entry image-task workflow with annotation masks, project references, and auditable candidate adoption.

**Architecture:** `GeneratedAssetService` stays the sole owner of task metadata, candidate directories, adoption, and manifests. The existing lazy Preview panel serializes a normalized intent and regions list; routes validate it and compile an executor request with only project-local paths.

**Tech Stack:** FastAPI, Python dataclasses/pathlib, pytest/TestClient, vanilla JavaScript, existing preview grid and panel registry.

**Spec:** `docs/superpowers/specs/2026-09-09-preview-image-task-panel-design.md`

## Global Constraints

- Reuse the generated-assets service and routes; do not create a parallel store.
- Resolve all source, reference, mask, candidate, and output paths below the active project.
- Do not overwrite source or candidate files; default candidates to 1 and cap them at 4.
- Normalize legacy prompt-only requests to `edit_source_image` with an overall requirement.
- Keep explicit grid column 4, a 40px header, `.panel-close-btn`, and right-panel mutual exclusion.
- Distinguish route/browser tests from real provider generation evidence.

---

### Task 1: Normalize and persist task intent, regions, and lineage

**Files:**
- Modify: `dev/generated_assets.py`
- Modify: `tests/test_generated_assets.py`

**Interfaces:**
- Consumes: `create_task(..., intent=None, regions=None, reference=None, parent_task_id="", parent_candidate_id="")`.
- Produces: `GeneratedAssetTask.intent`, `.regions`, `.parent_task_id`, `.parent_candidate_id`, and normalized request/manifest metadata.

- [ ] **Step 1: Write the failing storage tests**

```python
def test_task_persists_intent_and_copies_project_mask(tmp_path: Path):
    project = _project(tmp_path)
    (project / "art").mkdir()
    source, mask = project / "art/source.png", project / "art/mask.png"
    source.write_bytes(PNG_1X1); mask.write_bytes(PNG_1X1)
    task = GeneratedAssetService(project).create_task(
        source_path=source, prompt="", purpose="", topic="cockpit", width=1920,
        height=720, candidate_count=1, backend="codex", operator="tester",
        intent={"mode":"edit_source_image", "overall_requirements":"keep warnings"},
        regions=[{"id":"risk", "mask_path":str(mask), "action":"overlay_risk_zone",
                  "description":"amber", "enabled":True, "order":1}])
    payload = json.loads((task.metadata_dir / "request.json").read_text())
    assert payload["intent"]["mode"] == "edit_source_image"
    assert payload["regions"][0]["mask_path"].startswith(".clawmate/generated-tasks/")

def test_task_rejects_outside_mask_and_blank_replacement(tmp_path: Path):
    service = GeneratedAssetService(_project(tmp_path))
    with pytest.raises(ValueError, match="mask"):
        service.create_task(source_path=None, prompt="x", purpose="", topic="x", width=64,
            height=64, candidate_count=1, backend="codex", operator="t",
            intent={"mode":"create_from_reference"},
            regions=[{"id":"r", "mask_path":"/tmp/x.png", "action":"recolor"}])
```

- [ ] **Step 2: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py -q`; expect failure because the new arguments do not exist.**

- [ ] **Step 3: Implement immutable fields and helpers**

```python
@dataclass(frozen=True)
class GeneratedAssetTask:
    # existing fields
    intent: dict[str, object]
    regions: list[dict[str, object]]
    parent_task_id: str = ""
    parent_candidate_id: str = ""
```

Add `_normalize_intent`, `_store_regions`, and `_validate_task_input`. Copy only
PNG/JPEG/WebP masks located within the project into `metadata_dir / "masks"`,
persist relative paths, reject duplicate IDs/nonpositive order, require an image
source for edit mode, and require replacement descriptions.

- [ ] **Step 4: Load absent modern fields as legacy defaults and include all new fields in `request_payload()` and `_append_manifest()`.**
- [ ] **Step 5: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py -q`; expect PASS.**
- [ ] **Step 6: Commit with `git add -- dev/generated_assets.py tests/test_generated_assets.py && git commit -m "feat: persist image task intent and regions"`.**

### Task 2: Stage masks, references, and safe executor instructions

**Files:**
- Modify: `dev/generated_assets.py`
- Modify: `dev/generated_asset_routes.py`
- Modify: `tests/test_generated_assets.py`

**Interfaces:**
- Consumes: multipart `mask`, and `reference={"source_kind":"image|markdown|html","source_path":"relative/path"}`.
- Produces: a relative staged-mask path, reference snapshot beneath task metadata, and compiled ordered instructions.

- [ ] **Step 1: Write failing route/reference tests**

```python
def test_stage_mask_returns_project_relative_path(tmp_path: Path, monkeypatch):
    response = TestClient(app).post(
        "/api/clawmate/generated-assets/demo/project/masks",
        files={"mask": ("mask.png", PNG_1X1, "image/png")})
    assert response.status_code == 201
    assert response.json()["mask_path"].startswith(".clawmate/generated-tasks/staged-masks/")

def test_task_snapshots_markdown_reference(tmp_path: Path):
    project = _project(tmp_path)
    (project / "brief.md").write_text("# cockpit", encoding="utf-8")
    task = GeneratedAssetService(project).create_task(
        source_path=None, prompt="", purpose="", topic="brief", width=1024,
        height=768, candidate_count=1, backend="codex", operator="tester",
        intent={"mode":"create_from_reference", "overall_requirements":"wireframe"},
        reference={"source_kind":"markdown", "source_path":"brief.md"})
    assert (task.metadata_dir / "reference/brief.md").is_file()
```

- [ ] **Step 2: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py -q`; expect failure because the mask endpoint/reference support is absent.**
- [ ] **Step 3: Add `POST /api/clawmate/generated-assets/{root}/{project}/masks` using `UploadFile`; accept only PNG/JPEG/WebP up to 8 MiB, save with a server UUID under `.clawmate/generated-tasks/staged-masks`, and return only a relative path.**
- [ ] **Step 4: Permit only image/Markdown/HTML references inside the project, enforce extension-kind agreement, copy the source to `metadata_dir / "reference"`, and reject PDF/Office references with 422.**
- [ ] **Step 5: Change `_agent_instruction(task)` to include normalized intent, snapshot path, and ordered enabled regions; list only copied task mask paths and retain the existing no-overwrite/no-auto-adopt rules.**
- [ ] **Step 6: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py -q`; expect PASS.**
- [ ] **Step 7: Commit with `git add -- dev/generated_assets.py dev/generated_asset_routes.py tests/test_generated_assets.py && git commit -m "feat: compile controlled image task instructions"`.**

### Task 3: Replace the legacy Preview form with a two-entry composer

**Files:**
- Modify: `dev/static/preview.html`
- Modify: `dev/static/js/image-assets-panel.js`
- Modify: `dev/static/css/preview.css`
- Modify: `tests/test_generated_asset_frontend.py`

**Interfaces:**
- Consumes: `getContext() -> {root, project, file}` plus task and staged-mask endpoints.
- Produces: the existing `open`, `close`, `refresh`, and `isOpen` controller plus serialized intent/regions.

- [ ] **Step 1: Write failing DOM contracts**

```python
def test_image_task_panel_has_two_modes_and_intent_controls():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    assert 'name="previewImageTaskMode"' in html
    assert 'value="edit_source_image"' in html
    assert 'value="create_from_reference"' in html
    assert 'id="previewImageArtifactType"' in html
    assert 'id="previewImageVisualStyle"' in html
    assert 'id="previewImageUseCase"' in html
    assert 'id="previewImageRegions"' in html
```

- [ ] **Step 2: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_asset_frontend.py -q`; expect failure because the legacy form has no task intent controls.**
- [ ] **Step 3: Add radio modes; artifact-type, visual-style, and use-case selects; size/constraint controls; topic/count; overall requirements; and a `<details>` request summary. Keep `aria-live` status and hide region controls in create mode.**

```javascript
function taskPayload(context) {
  return {source_path: selectedSourcePath(context), prompt: overall.value.trim(),
    purpose: useCase.value, topic: topic.value.trim(), width: Number(width.value),
    height: Number(height.value), candidate_count: boundedCount(count.value),
    intent: {mode: selectedMode(), artifact_type: artifactType.value,
      visual_style: visualStyle.value, use_case: useCase.value,
      overall_requirements: overall.value.trim()}, regions: serializedRegions()};
}
```

- [ ] **Step 4: Preserve `#previewImageAssetsPanel { grid-column: 4; }`, shared header/close styles, `hidden` behavior, and mutual exclusion. Add a `max-width: 700px` stacked layout retaining text-only whole-image submission.**
- [ ] **Step 5: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_asset_frontend.py -q && node --check dev/static/js/image-assets-panel.js`; expect PASS.**
- [ ] **Step 6: Commit with `git add -- dev/static/preview.html dev/static/js/image-assets-panel.js dev/static/css/preview.css tests/test_generated_asset_frontend.py && git commit -m "feat: add image task composer modes"`.**

### Task 4: Add multiple canvas regions and keyboard alternatives

**Files:**
- Modify: `dev/static/preview.html`
- Modify: `dev/static/js/image-assets-panel.js`
- Modify: `dev/static/css/preview.css`
- Modify: `tests/test_generated_asset_frontend.py`

**Interfaces:**
- Consumes: staged mask uploads and Task 3 payload serialization.
- Produces: ordered region cards, uploaded PNG masks, and non-destructive candidate follow-up drafts.

- [ ] **Step 1: Write failing interaction contracts**

```python
def test_image_task_panel_exposes_region_controls_and_binary_masks():
    html = PREVIEW_HTML.read_text(encoding="utf-8")
    js = PANEL_JS.read_text(encoding="utf-8")
    assert 'id="previewImageTaskCanvas"' in html
    assert 'id="previewImageAddRegion"' in html
    assert "canvas.toBlob" in js
    assert "FormData" in js
    assert "moveRegion" in js
    assert "replace_locally" in js
```

- [ ] **Step 2: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_asset_frontend.py -q`; expect failure because no region authoring exists.**
- [ ] **Step 3: Implement rectangle-drag and brush-stroke masks. Before submit, convert each canvas via `toBlob`, stage it with `FormData`, then place the returned path in its region record.**
- [ ] **Step 4: Render focusable region cards with name/action/description, enable toggle, delete, and earlier/later controls. Normalize order after every operation and display overlap warnings. The list is the keyboard alternative to canvas operations.**

```javascript
function moveRegion(id, offset) {
  var index = regions.findIndex(function (item) { return item.id === id; });
  var next = index + offset;
  if (index < 0 || next < 0 || next >= regions.length) return;
  regions.splice(next, 0, regions.splice(index, 1)[0]);
  regions.forEach(function (item, order) { item.order = order + 1; });
  renderRegions();
}
```

- [ ] **Step 5: Add `用作下一轮原图` and `生成变体`; they initialize a fresh draft with parent IDs and never change the parent file.**
- [ ] **Step 6: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py tests/test_generated_asset_frontend.py -q && node --check dev/static/js/image-assets-panel.js && git diff --check`; expect PASS.**
- [ ] **Step 7: Commit with `git add -- dev/static/preview.html dev/static/js/image-assets-panel.js dev/static/css/preview.css tests/test_generated_asset_frontend.py && git commit -m "feat: add annotated image task regions"`.**

### Task 5: Browser acceptance and honest provider reporting

**Files:**
- Modify: `tests/test_generated_asset_frontend.py` only when an interactive check exposes a deterministic missing contract.

**Interfaces:**
- Consumes: the completed routes and panel.
- Produces: evidence separated into deterministic, browser, and real-provider layers.

- [ ] **Step 1: Run `PYTHONPATH=. dev/.venv/bin/python -m pytest tests/test_generated_assets.py tests/test_generated_asset_frontend.py tests/test_preview_agent_panel_layout.py tests/test_visual_consistency_contract.py -q && node --check dev/static/js/image-assets-panel.js && git diff --check`; expect PASS.**
- [ ] **Step 2: In a running Preview, test image edit mode with two regions, candidate submission, panel mutual exclusion, Markdown/HTML reference mode, narrow-viewport text-only mode, and keyboard list operations. Inspect network payloads and browser console.**
- [ ] **Step 3: If an approved configured backend returns a real candidate, record that outcome; otherwise report route/browser evidence only and state that provider generation remains unverified.**

## Plan self-review

- Tasks 1-2 cover schema, legacy compatibility, path boundaries, metadata snapshots, masks, provenance, and executor isolation.
- Tasks 3-4 cover both entry modes, panel conventions, local edit actions, accessibility, responsive fallback, and lineage.
- Task 5 explicitly separates deterministic and browser success from a real configured image-provider result.
