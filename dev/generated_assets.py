"""Controlled generated-image task storage and provenance.

Agents receive a server-created candidate directory and task metadata path.
Only this module decides which files become project assets.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_BACKENDS = {"auto", "codex", "claude", "openclaw"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class GeneratedAssetTask:
    id: str
    project_dir: Path
    source_path: Path | None
    candidate_dir: Path
    metadata_dir: Path
    prompt: str
    purpose: str
    topic: str
    width: int
    height: int
    candidate_count: int
    backend: str
    operator: str
    created_at: str

    def request_payload(self) -> dict:
        source = ""
        if self.source_path:
            source = self.source_path.relative_to(self.project_dir).as_posix()
        return {
            "task_id": self.id,
            "source_path": source,
            "candidate_dir": self.candidate_dir.relative_to(self.project_dir).as_posix(),
            "prompt": self.prompt,
            "purpose": self.purpose,
            "topic": self.topic,
            "width": self.width,
            "height": self.height,
            "candidate_count": self.candidate_count,
            "backend": self.backend,
            "operator": self.operator,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class GeneratedAssetCandidate:
    id: str
    file: Path
    summary: str
    width: int | None = None
    height: int | None = None
    parent_candidate_id: str = ""


@dataclass(frozen=True)
class GeneratedAssetResult:
    task: GeneratedAssetTask
    candidates: list[GeneratedAssetCandidate]


@dataclass(frozen=True)
class AdoptedAsset:
    task_id: str
    candidate_id: str
    path: Path


class GeneratedAssetService:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        if not (self.project_dir / ".clawmate").is_dir():
            raise ValueError("project marker is required")

    def create_task(
        self, *, source_path: Path | None, prompt: str, purpose: str, topic: str,
        width: int, height: int, candidate_count: int, backend: str, operator: str,
    ) -> GeneratedAssetTask:
        prompt = str(prompt or "").strip()
        topic = self._safe_topic(topic)
        backend = str(backend or "").strip().lower()
        if not prompt:
            raise ValueError("prompt is required")
        if len(prompt) > 8000:
            raise ValueError("prompt is too long")
        if not 1 <= int(candidate_count) <= 4:
            raise ValueError("candidate_count must be between 1 and 4")
        if not 64 <= int(width) <= 4096 or not 64 <= int(height) <= 4096:
            raise ValueError("image dimensions must be between 64 and 4096")
        if backend not in _BACKENDS:
            raise ValueError("unsupported backend")
        source = self._validated_source(source_path)
        task_id = uuid.uuid4().hex
        base_dir = source.parent if source else self.project_dir
        candidate_dir = base_dir / "candidates" / task_id
        metadata_dir = self.project_dir / ".clawmate" / "generated-tasks" / task_id
        task = GeneratedAssetTask(
            id=task_id, project_dir=self.project_dir, source_path=source,
            candidate_dir=candidate_dir, metadata_dir=metadata_dir, prompt=prompt,
            purpose=str(purpose or "").strip()[:500], topic=topic, width=int(width),
            height=int(height), candidate_count=int(candidate_count), backend=backend,
            operator=str(operator or "").strip()[:200], created_at=_now(),
        )
        metadata_dir.mkdir(parents=True, exist_ok=False)
        try:
            candidate_dir.mkdir(parents=True, exist_ok=False)
            self._write_json_atomic(metadata_dir / "request.json", task.request_payload())
        except Exception:
            shutil.rmtree(metadata_dir, ignore_errors=True)
            shutil.rmtree(candidate_dir, ignore_errors=True)
            raise
        return task

    def load_task(self, task_id: str) -> GeneratedAssetTask:
        if not re.fullmatch(r"[0-9a-f]{32}", str(task_id)):
            raise ValueError("invalid task id")
        metadata_dir = self.project_dir / ".clawmate" / "generated-tasks" / task_id
        try:
            payload = json.loads((metadata_dir / "request.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("task not found") from exc
        source_rel = str(payload.get("source_path") or "")
        source = self._project_path(source_rel) if source_rel else None
        candidate_dir = self._project_path(str(payload.get("candidate_dir") or ""))
        if candidate_dir.name != task_id or candidate_dir.parent.name != "candidates":
            raise ValueError("invalid candidate directory")
        return GeneratedAssetTask(
            id=task_id, project_dir=self.project_dir, source_path=source,
            candidate_dir=candidate_dir, metadata_dir=metadata_dir, prompt=str(payload.get("prompt") or ""),
            purpose=str(payload.get("purpose") or ""), topic=self._safe_topic(str(payload.get("topic") or "")),
            width=int(payload.get("width") or 0), height=int(payload.get("height") or 0),
            candidate_count=int(payload.get("candidate_count") or 0), backend=str(payload.get("backend") or ""),
            operator=str(payload.get("operator") or ""), created_at=str(payload.get("created_at") or ""),
        )

    def read_result(self, task_id: str) -> GeneratedAssetResult:
        task = self.load_task(task_id)
        try:
            raw = json.loads((task.metadata_dir / "result.json").read_text(encoding="utf-8"))
            rows = raw["candidates"]
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("candidate result is unavailable") from exc
        if not isinstance(rows, list) or not 1 <= len(rows) <= task.candidate_count:
            raise ValueError("candidate count is outside request limit")
        candidates = [self._validated_candidate(task, row) for row in rows]
        if len({item.id for item in candidates}) != len(candidates):
            raise ValueError("candidate ids must be unique")
        return GeneratedAssetResult(task=task, candidates=candidates)

    def adopt_candidate(self, task_id: str, candidate_id: str) -> AdoptedAsset:
        result = self.read_result(task_id)
        candidate = next((item for item in result.candidates if item.id == candidate_id), None)
        if candidate is None:
            raise ValueError("candidate not found")
        target_dir = self.project_dir / "assets" / "generated" / result.task.topic
        target_dir.mkdir(parents=True, exist_ok=True)
        target = self._next_target_path(target_dir, candidate.file.name)
        shutil.copy2(candidate.file, target)
        self._append_manifest(target_dir, result.task, candidate, target)
        return AdoptedAsset(task_id=task_id, candidate_id=candidate_id, path=target)

    def source_prompt(self, source_path: Path) -> str | None:
        source = source_path.resolve()
        try:
            relative = source.relative_to(self.project_dir).as_posix()
        except ValueError:
            return None
        manifest = source.parent / "manifest.json"
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8")).get("assets", [])
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        for item in reversed(rows):
            if item.get("output_path") == relative:
                prompt = str(item.get("generation_prompt") or "").strip()
                return prompt or None
        return None

    def _validated_source(self, source_path: Path | None) -> Path | None:
        if source_path is None:
            return None
        source = Path(source_path).resolve()
        try:
            source.relative_to(self.project_dir)
        except ValueError as exc:
            raise ValueError("source image is outside project") from exc
        if not source.is_file() or source.suffix.lower() not in _IMAGE_EXTENSIONS:
            raise ValueError("source image is invalid")
        return source

    def _validated_candidate(self, task: GeneratedAssetTask, row: object) -> GeneratedAssetCandidate:
        if not isinstance(row, dict):
            raise ValueError("candidate is invalid")
        candidate_id = str(row.get("id") or "")
        filename = str(row.get("file") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", candidate_id):
            raise ValueError("candidate id is invalid")
        if not filename or Path(filename).name != filename:
            raise ValueError("candidate path is invalid")
        path = (task.candidate_dir / filename).resolve()
        try:
            path.relative_to(task.candidate_dir.resolve())
        except ValueError as exc:
            raise ValueError("candidate path is invalid") from exc
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTENSIONS:
            raise ValueError("candidate file is invalid")
        return GeneratedAssetCandidate(
            id=candidate_id, file=path, summary=str(row.get("summary") or "")[:500],
            width=self._optional_int(row.get("width")), height=self._optional_int(row.get("height")),
            parent_candidate_id=str(row.get("parent_candidate_id") or "")[:120],
        )

    def _append_manifest(self, target_dir: Path, task: GeneratedAssetTask,
                         candidate: GeneratedAssetCandidate, target: Path) -> None:
        path = target_dir / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = {"assets": []}
        assets = manifest.get("assets")
        if not isinstance(assets, list):
            assets = []
            manifest["assets"] = assets
        assets.append({
            "task_id": task.id, "candidate_id": candidate.id,
            "source_path": task.source_path.relative_to(self.project_dir).as_posix() if task.source_path else "",
            "candidate_path": candidate.file.relative_to(self.project_dir).as_posix(),
            "output_path": target.relative_to(self.project_dir).as_posix(),
            "generation_prompt": task.prompt, "purpose": task.purpose, "topic": task.topic,
            "width": candidate.width or task.width, "height": candidate.height or task.height,
            "backend": task.backend, "operator": task.operator, "created_at": task.created_at,
            "adopted_at": _now(), "summary": candidate.summary,
            "parent_candidate_id": candidate.parent_candidate_id,
        })
        self._write_json_atomic(path, manifest)

    def _project_path(self, value: str) -> Path:
        if not value:
            raise ValueError("path is required")
        target = (self.project_dir / value).resolve()
        try:
            target.relative_to(self.project_dir)
        except ValueError as exc:
            raise ValueError("path is outside project") from exc
        return target

    @staticmethod
    def _safe_topic(value: str) -> str:
        topic = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-_")
        if not topic:
            raise ValueError("topic is required")
        return topic[:80]

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("candidate dimensions are invalid")

    @staticmethod
    def _next_target_path(directory: Path, filename: str) -> Path:
        stem, suffix = Path(filename).stem, Path(filename).suffix.lower()
        target = directory / (stem + suffix)
        index = 2
        while target.exists():
            target = directory / f"{stem}-{index}{suffix}"
            index += 1
        return target

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
