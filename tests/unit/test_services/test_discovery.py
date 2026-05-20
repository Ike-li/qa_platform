"""Unit tests for DiscoveryService."""
from __future__ import annotations

import pytest
from pathlib import Path

from qaplatform.domain.models.project import TestSelector
from qaplatform.domain.services.discovery import DiscoveryService


@pytest.fixture
def svc():
    return DiscoveryService()


# ── helpers ──────────────────────────────────────────────────────────────

def _make_tree(base: Path, files: list[str]) -> None:
    """Create a directory tree with empty files under *base*."""
    for f in files:
        p = base / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")


# ── tests ────────────────────────────────────────────────────────────────


class TestIncludePaths:
    """Glob include_paths filtering."""

    def test_matches_pattern(self, svc, tmp_path):
        _make_tree(tmp_path, ["tests/test_a.py", "tests/test_b.py", "src/main.py"])
        selector = TestSelector(include_paths=["tests/*.py"])
        result = svc.discover_tests(selector, tmp_path)
        assert "tests/test_a.py" in result
        assert "tests/test_b.py" in result
        assert "src/main.py" not in result

    def test_multiple_patterns(self, svc, tmp_path):
        _make_tree(tmp_path, ["tests/test_a.py", "specs/test_b.js", "lib/util.py"])
        selector = TestSelector(include_paths=["tests/*.py", "specs/*.js"])
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["specs/test_b.js", "tests/test_a.py"]

    def test_no_include_returns_all(self, svc, tmp_path):
        _make_tree(tmp_path, ["a.py", "b.py"])
        selector = TestSelector(include_paths=[])
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["a.py", "b.py"]


class TestExcludePaths:
    """Glob exclude_paths filtering."""

    def test_excludes_pattern(self, svc, tmp_path):
        _make_tree(tmp_path, ["tests/test_a.py", "tests/__pycache__/test_b.py"])
        selector = TestSelector(exclude_paths=["*__pycache__*"])
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["tests/test_a.py"]

    def test_exclude_with_include(self, svc, tmp_path):
        _make_tree(tmp_path, ["tests/test_a.py", "tests/test_fixture.py", "src/main.py"])
        selector = TestSelector(
            include_paths=["tests/*.py"],
            exclude_paths=["*fixture*"],
        )
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["tests/test_a.py"]


class TestRegexFilter:
    """Regex filter on filename."""

    def test_matches_regex(self, svc, tmp_path):
        _make_tree(tmp_path, ["test_login.py", "test_logout.py", "conftest.py"])
        selector = TestSelector(regex=r"^test_")
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["test_login.py", "test_logout.py"]

    def test_no_match_returns_empty(self, svc, tmp_path):
        _make_tree(tmp_path, ["lib.py", "util.py"])
        selector = TestSelector(regex=r"^test_")
        result = svc.discover_tests(selector, tmp_path)
        assert result == []


class TestEmptyDir:
    """Empty / non-existent directories."""

    def test_empty_dir(self, svc, tmp_path):
        selector = TestSelector()
        result = svc.discover_tests(selector, tmp_path)
        assert result == []

    def test_nonexistent_dir(self, svc, tmp_path):
        selector = TestSelector()
        result = svc.discover_tests(selector, tmp_path / "nope")
        assert result == []


class TestHiddenDirs:
    """Directories starting with '.' should be skipped."""

    def test_hidden_dir_skipped(self, svc, tmp_path):
        _make_tree(tmp_path, ["visible.py", ".hidden/secret.py", ".git/config"])
        selector = TestSelector()
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["visible.py"]


class TestSorting:
    """Results should be sorted."""

    def test_sorted_output(self, svc, tmp_path):
        _make_tree(tmp_path, ["z.py", "a.py", "m/sub.py", "m/a.py"])
        selector = TestSelector()
        result = svc.discover_tests(selector, tmp_path)
        assert result == ["a.py", "m/a.py", "m/sub.py", "z.py"]
