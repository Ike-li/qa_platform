from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def _validate_workspace_relative_path(raw_path: object, *, field: str) -> str:
    value = str(raw_path)
    if not value.strip():
        raise ValueError(f"{field} must be a relative path inside the workspace")
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise ValueError(f"{field} must be a relative path inside the workspace")
    return value


def safe_workspace_output_path(raw_path: object, default: str, *, field: str) -> str:
    """Return a report path that cannot escape the mounted workspace."""
    return _validate_workspace_relative_path(raw_path or default, field=field)


def safe_workspace_paths(
    raw_paths: object,
    default: list[str] | None = None,
    *,
    field: str,
) -> list[str]:
    """Return CLI paths that stay inside the mounted workspace."""
    paths = raw_paths
    if paths is None:
        paths = default or []
    if isinstance(paths, str):
        paths = [paths]
    return [_validate_workspace_relative_path(path, field=field) for path in paths]
