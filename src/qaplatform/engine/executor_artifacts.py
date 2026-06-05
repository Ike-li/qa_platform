"""Artifact path and metadata helpers for run execution."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path


ARTIFACT_TYPE_BY_EXT = {
    ".xml": "junit",
    ".html": "report",
    ".htm": "report",
    ".json": "json",
    ".log": "log",
    ".txt": "log",
}


@dataclass(frozen=True)
class ArtifactUploadInfo:
    path: Path
    rel_path: str
    rel_parts: tuple[str, ...]
    storage_path: str
    size_bytes: int
    type: str
    mime_type: str


def iter_artifact_files(results_dir: Path) -> list[Path]:
    return sorted(path for path in results_dir.rglob("*") if path.is_file())


def artifact_type_for_path(path: Path, rel_parts: tuple[str, ...]) -> str:
    if any(part in {"allure-report", "allure-results"} for part in rel_parts[:-1]):
        return "allure-report"
    return ARTIFACT_TYPE_BY_EXT.get(path.suffix.lower(), "other")


def artifact_mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or "application/octet-stream"


def artifact_upload_info(
    *,
    run_id: str,
    results_dir: Path,
    path: Path,
) -> ArtifactUploadInfo:
    rel_parts = path.relative_to(results_dir).parts
    rel_path = Path(*rel_parts).as_posix()
    return ArtifactUploadInfo(
        path=path,
        rel_path=rel_path,
        rel_parts=rel_parts,
        storage_path=f"reports/{run_id}/{rel_path}",
        size_bytes=path.stat().st_size,
        type=artifact_type_for_path(path, rel_parts),
        mime_type=artifact_mime_type(path),
    )
