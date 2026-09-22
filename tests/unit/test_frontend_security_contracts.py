"""Minimal frontend security contract smoke tests.

Verifies that critical security functions exist in the source code.
Real behavior testing is in tests/e2e/frontend-security.spec.ts.

This file only checks that security functions are present, not their implementation
details. It serves as a fast smoke check that security code hasn't been accidentally
deleted during refactoring.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PREVIEW = ROOT / "frontend" / "src" / "components" / "runs" / "artifact-preview.tsx"
RUN_DETAIL_PAGE = ROOT / "frontend" / "src" / "pages" / "runs" / "detail.tsx"


def test_artifact_preview_iframe_has_sandbox_attribute():
    """Verify iframe sandbox attribute exists (not allow-same-origin)."""
    source = ARTIFACT_PREVIEW.read_text(encoding="utf-8")

    assert 'sandbox="allow-scripts"' in source
    assert "allow-same-origin" not in source
    assert 'referrerPolicy="no-referrer"' in source


# Removed test_artifact_url_validation_function_exists: it grepped detail.tsx
# source text, which AGENTS.md bans as a meta-test and which broke when
# isSafeArtifactUrl moved to lib/utils. The URL-safety behavior (javascript:/
# file: rejection) is verified end-to-end in tests/e2e/frontend-security.spec.ts.
