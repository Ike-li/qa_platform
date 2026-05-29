from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PREVIEW = ROOT / "frontend" / "src" / "components" / "runs" / "artifact-preview.tsx"


def test_artifact_preview_iframe_keeps_report_origin_sandboxed():
    source = ARTIFACT_PREVIEW.read_text(encoding="utf-8")

    assert 'sandbox="allow-scripts"' in source
    assert "allow-same-origin" not in source
    assert 'referrerPolicy="no-referrer"' in source
