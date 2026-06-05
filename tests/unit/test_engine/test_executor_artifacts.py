from __future__ import annotations

from pathlib import Path

from qaplatform.engine import executor as executor_module
from qaplatform.engine.executor_artifacts import (
    ARTIFACT_TYPE_BY_EXT,
    artifact_mime_type,
    artifact_type_for_path,
    artifact_upload_info,
    iter_artifact_files,
)


def test_iter_artifact_files_recurses_and_sorts_files(tmp_path):
    results_dir = tmp_path / "results"
    (results_dir / "nested").mkdir(parents=True)
    (results_dir / "z.txt").write_text("z")
    (results_dir / "nested" / "a.xml").write_text("<xml/>")

    assert [
        path.relative_to(results_dir).as_posix()
        for path in iter_artifact_files(results_dir)
    ] == ["nested/a.xml", "z.txt"]


def test_artifact_upload_info_builds_storage_metadata(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    artifact_path = results_dir / "junit.xml"
    artifact_path.write_text("<testsuite/>")

    info = artifact_upload_info(
        run_id="run-123",
        results_dir=results_dir,
        path=artifact_path,
    )

    assert info.path == artifact_path
    assert info.rel_path == "junit.xml"
    assert info.rel_parts == ("junit.xml",)
    assert info.storage_path == "reports/run-123/junit.xml"
    assert info.size_bytes == len("<testsuite/>")
    assert info.type == "junit"
    assert info.mime_type in {"application/xml", "text/xml"}


def test_artifact_type_for_path_marks_allure_directories():
    assert (
        artifact_type_for_path(
            path=Path("app.js"),
            rel_parts=("allure-report", "assets", "app.js"),
        )
        == "allure-report"
    )
    assert (
        artifact_type_for_path(
            path=Path("result.json"),
            rel_parts=("allure-results", "result.json"),
        )
        == "allure-report"
    )


def test_artifact_mime_type_defaults_to_octet_stream(tmp_path):
    artifact_path = tmp_path / "artifact.unknownext"
    artifact_path.write_bytes(b"\x00")

    assert artifact_mime_type(artifact_path) == "application/octet-stream"


def test_executor_module_keeps_private_artifact_helper_exports():
    import qaplatform.engine.executor_artifacts as artifacts

    assert executor_module._ARTIFACT_TYPE_BY_EXT is ARTIFACT_TYPE_BY_EXT
    assert executor_module._ARTIFACT_TYPE_BY_EXT is artifacts.ARTIFACT_TYPE_BY_EXT
    assert executor_module._artifact_upload_info is artifacts.artifact_upload_info
    assert executor_module._iter_artifact_files is artifacts.iter_artifact_files
