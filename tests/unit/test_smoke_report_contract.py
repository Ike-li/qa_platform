from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = ROOT / "scripts" / "smoke" / "lib" / "common.sh"
SMOKE_RUN_ALL = ROOT / "scripts" / "smoke" / "run-all.sh"


def _run_smoke_report(
    tmp_path: Path,
    body: str,
    *,
    allow_skips: bool = False,
) -> subprocess.CompletedProcess[str]:
    results_dir = tmp_path / "smoke-results"
    env = os.environ.copy()
    env.update(
        {
            "BASE_URL": "http://smoke.local",
            "RESULTS_DIR": str(results_dir),
            "SMOKE_ALLOW_SKIPS": "1" if allow_skips else "0",
        }
    )
    script = f"""
set -euo pipefail
source "{COMMON_SH}"
init_results_dir
{body}
generate_report
"""
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )


def test_smoke_report_fails_when_required_steps_are_skipped(tmp_path: Path):
    result = _run_smoke_report(
        tmp_path,
        'log_step "project-content" "skip" "无项目卡片"',
    )

    assert result.returncode == 1
    report = (tmp_path / "smoke-results" / "report.txt").read_text(encoding="utf-8")
    assert "跳过: 1" in report
    assert "结果: FAIL" in report
    assert "SMOKE_ALLOW_SKIPS=1" in report


def test_smoke_report_allows_explicit_exploratory_skips(tmp_path: Path):
    result = _run_smoke_report(
        tmp_path,
        'log_step "optional-widget" "skip" "实验性检查"',
        allow_skips=True,
    )

    assert result.returncode == 0
    report = (tmp_path / "smoke-results" / "report.txt").read_text(encoding="utf-8")
    assert "跳过: 1" in report
    assert "结果: PASS_WITH_SKIPS" in report


def test_smoke_report_failures_stay_failing_even_when_skips_are_allowed(
    tmp_path: Path,
):
    result = _run_smoke_report(
        tmp_path,
        'log_step "login" "fail" "无法登录"',
        allow_skips=True,
    )

    assert result.returncode == 1
    report = (tmp_path / "smoke-results" / "report.txt").read_text(encoding="utf-8")
    assert "失败: 1" in report
    assert "结果: FAIL" in report


def test_smoke_run_all_prints_artifact_root_even_when_a_child_fails(tmp_path: Path):
    smoke_dir = tmp_path / "scripts" / "smoke"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "lib").mkdir()
    (smoke_dir / "lib" / "common.sh").write_text(
        COMMON_SH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (smoke_dir / "run-all.sh").write_text(
        SMOKE_RUN_ALL.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for script_name in (
        "00-setup.sh",
        "01-browser-bridge.sh",
        "02-login-smoke.sh",
        "03-projects-list.sh",
        "04-project-detail.sh",
        "05-runs-list.sh",
        "06-run-detail.sh",
        "07-settings.sh",
    ):
        exit_code = 1 if script_name == "04-project-detail.sh" else 0
        (smoke_dir / script_name).write_text(
            f"#!/usr/bin/env bash\nexit {exit_code}\n",
            encoding="utf-8",
        )

    results_dir = tmp_path / "smoke-artifacts"
    result = subprocess.run(
        ["bash", str(smoke_dir / "run-all.sh")],
        check=False,
        env={**os.environ, "RESULTS_DIR": str(results_dir)},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "冒烟测试完成。产物目录:" in result.stdout
    assert f"  {results_dir}" in result.stdout
    assert f"  {results_dir}/<script-name>/" in result.stdout
    report = (results_dir / "report.txt").read_text(encoding="utf-8")
    assert "[FAIL] 04-project-detail.sh" in report
