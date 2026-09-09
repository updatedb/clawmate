"""HTTP boundary for controlled generated-image tasks."""
from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from config import load as load_cfg
from generated_assets import GeneratedAssetService
from service import safe_path
from task_executor import TaskExecutor


router = APIRouter()
_MASK_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_MAX_MASK_BYTES = 8 * 1024 * 1024


def _project(root: str, project: str) -> Path:
    try:
        _, directory, _ = safe_path(root, project)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    if not directory.is_dir() or not (directory / ".clawmate").is_dir():
        raise HTTPException(status_code=404, detail="Project not found")
    return directory


def _source(project_dir: Path, value: object) -> Path | None:
    path = str(value or "").strip()
    if not path:
        return None
    candidate = (project_dir / path).resolve()
    try:
        candidate.relative_to(project_dir)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Source is outside project") from exc
    return candidate


def _agent_instruction(task) -> str:
    return (
        "ClawMate 受控生成资产任务。仅可使用你自身已经配置好的图像能力；不要访问或写入任务指定路径外的文件。\n"
        f"任务 ID：{task.id}\n源图：{task.source_path or '无'}\n候选输出目录：{task.candidate_dir}\n"
        f"任务元数据目录：{task.metadata_dir}\n需求：{task.prompt}\n用途：{task.purpose}\n"
        f"输出尺寸：{task.width}x{task.height}；候选数：{task.candidate_count}。\n"
        "把每张候选图片写入候选输出目录，并在任务元数据目录写 result.json。"
        "result.json 必须是 {\"candidates\":[{\"id\":\"...\",\"file\":\"filename.png\",\"summary\":\"...\"}]}。"
        "不得覆盖源图，不得使用 Base64，不得自行采用或移动候选图。"
    )


@router.post("/api/clawmate/generated-assets/{root}/{project}/masks", status_code=201)
async def stage_mask(root: str, project: str, mask: UploadFile = File(...)):
    suffix = _MASK_TYPES.get(str(mask.content_type or "").lower())
    if suffix is None:
        raise HTTPException(status_code=422, detail="mask must be a PNG, JPEG, or WebP image")
    content = await mask.read(_MAX_MASK_BYTES + 1)
    if not content or len(content) > _MAX_MASK_BYTES:
        raise HTTPException(status_code=422, detail="mask must be between 1 byte and 8 MiB")
    project_dir = _project(root, project)
    target_dir = project_dir / ".clawmate" / "generated-tasks" / "staged-masks"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (uuid.uuid4().hex + suffix)
    target.write_bytes(content)
    return {"mask_path": target.relative_to(project_dir).as_posix()}


@router.post("/api/clawmate/generated-assets/{root}/{project}/tasks", status_code=201)
async def create_task(root: str, project: str, request: Request):
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    project_dir = _project(root, project)
    cfg = load_cfg()
    try:
        service = GeneratedAssetService(project_dir)
        task = service.create_task(
            source_path=_source(project_dir, body.get("source_path")), prompt=body.get("prompt"),
            purpose=body.get("purpose"), topic=body.get("topic"), width=body.get("width"),
            height=body.get("height"), candidate_count=body.get("candidate_count"),
            backend=cfg.agent.backend, operator="clawmate-user",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    receipt = TaskExecutor(cfg).launch(
        task_run_id=task.id, message=_agent_instruction(task), cwd=str(project_dir), root_id=root,
        backend=task.backend, name="clawmate-generated-asset",
    )
    status = "running" if receipt.status in {"starting", "running", "waiting_input"} else "failed"
    return JSONResponse(status_code=201, content={"task": {"id": task.id, "status": status, **task.request_payload()}, "launch": receipt.payload()})


@router.get("/api/clawmate/generated-assets/{root}/{project}/tasks/{task_id}")
async def get_task(root: str, project: str, task_id: str):
    try:
        result = GeneratedAssetService(_project(root, project)).read_result(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task": {"id": result.task.id, "status": "awaiting_review", **result.task.request_payload()}, "candidates": [
        {"id": item.id, "path": item.file.relative_to(result.task.project_dir).as_posix(), "summary": item.summary,
         "width": item.width, "height": item.height, "parent_candidate_id": item.parent_candidate_id}
        for item in result.candidates
    ]}


@router.post("/api/clawmate/generated-assets/{root}/{project}/tasks/{task_id}/adopt")
async def adopt_task_candidate(root: str, project: str, task_id: str, request: Request):
    try:
        body = await request.json()
        adopted = GeneratedAssetService(_project(root, project)).adopt_candidate(task_id, str(body.get("candidate_id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "path": adopted.path.relative_to(_project(root, project)).as_posix()}


@router.get("/api/clawmate/generated-assets/{root}/{project}/source-prompt")
async def source_prompt(root: str, project: str, path: str = ""):
    project_dir = _project(root, project)
    prompt = GeneratedAssetService(project_dir).source_prompt(_source(project_dir, path) or project_dir)
    return {"prompt": prompt, "recorded": bool(prompt)}
