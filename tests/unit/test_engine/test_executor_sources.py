from __future__ import annotations

from types import SimpleNamespace

from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_sources as sources


def test_run_metadata_prefers_orm_metadata_column():
    run = SimpleNamespace(
        metadata_={"git_url": "https://example.com/orm.git"},
        metadata={"git_url": "https://example.com/domain.git"},
    )

    assert sources.run_metadata(run) == {"git_url": "https://example.com/orm.git"}


def test_run_metadata_falls_back_to_domain_metadata():
    run = SimpleNamespace(
        metadata_=None,
        metadata={"git_url": "https://example.com/domain.git"},
    )

    assert sources.run_metadata(run) == {
        "git_url": "https://example.com/domain.git"
    }


def test_run_metadata_ignores_non_dict_metadata_column():
    run = SimpleNamespace(
        metadata_=["not", "a", "dict"],
        metadata={"git_url": "https://example.com/domain.git"},
    )

    assert sources.run_metadata(run) == {}


def test_git_url_for_run_returns_empty_string_when_missing():
    assert sources.git_url_for_run(SimpleNamespace(metadata_={})) == ""


def test_clone_ref_for_run_prefers_full_commit_sha():
    run = SimpleNamespace(
        git_ref="main",
        git_sha="0123456789abcdef0123456789abcdef01234567",
    )

    assert sources.clone_ref_for_run(run) == (
        "0123456789abcdef0123456789abcdef01234567"
    )


def test_clone_ref_for_run_falls_back_to_git_ref_for_short_sha():
    run = SimpleNamespace(git_ref="main", git_sha="abc123")

    assert sources.clone_ref_for_run(run) == "main"


def test_executor_module_keeps_source_helper_compatibility_exports():
    assert executor_module._FULL_GIT_SHA_RE is sources.FULL_GIT_SHA_RE
    assert executor_module._run_metadata is sources.run_metadata
    assert executor_module._git_url_for_run is sources.git_url_for_run
    assert executor_module._clone_ref_for_run is sources.clone_ref_for_run
