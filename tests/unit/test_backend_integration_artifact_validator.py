from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_validator_module():
    script_path = ROOT / "scripts" / "validate_backend_integration_artifacts.py"
    spec = importlib.util.spec_from_file_location(
        "validate_backend_integration_artifacts",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_collect(path: Path, nodeids: list[str]) -> None:
    body = "\n".join(nodeids)
    path.write_text(f"{body}\n{len(nodeids)} tests collected in 0.01s\n", encoding="utf-8")


def _write_junit(path: Path, nodeids: list[str]) -> None:
    cases = "\n".join(
        f"""
        <testcase classname="tests.integration.sample" name="test_{index}">
          <properties>
            <property name="nodeid" value="{nodeid}" />
          </properties>
        </testcase>
        """
        for index, nodeid in enumerate(nodeids, 1)
    )
    path.write_text(f"<testsuite>{cases}</testsuite>\n", encoding="utf-8")


def _write_junit_body(path: Path, body: str) -> None:
    path.write_text(f"<testsuite>{body}</testsuite>\n", encoding="utf-8")


def test_validate_backend_integration_artifacts_matches_collect_and_junit_nodeids(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    nodeids = [
        "tests/integration/test_sample.py::test_one",
        "tests/integration/test_sample.py::test_two[param]",
    ]
    _write_collect(collect, nodeids)
    _write_junit(junit, nodeids)

    assert validator.validate_pairs([collect]) == []


def test_validate_backend_integration_artifacts_rejects_missing_junit_nodeid(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    _write_collect(collect, ["tests/integration/test_sample.py::test_one"])
    junit.write_text(
        '<testsuite><testcase classname="tests.integration.sample" name="test_one" /></testsuite>',
        encoding="utf-8",
    )

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_missing_nodeid_properties={junit} "
        "count=1 preview=tests.integration.sample::test_one"
    ]


def test_validate_backend_integration_artifacts_rejects_nodeid_mismatch(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    _write_collect(collect, ["tests/integration/test_sample.py::test_one"])
    _write_junit(junit, ["tests/integration/test_sample.py::test_other"])

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_missing_collected_nodeids={junit} "
        "count=1 preview=['tests/integration/test_sample.py::test_one']",
        f"junit_unexpected_nodeids={junit} "
        "count=1 preview=['tests/integration/test_sample.py::test_other']",
    ]


def test_validate_backend_integration_artifacts_rejects_duplicate_junit_nodeids(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    duplicate = "tests/integration/test_sample.py::test_one"
    _write_collect(collect, [duplicate])
    _write_junit(junit, [duplicate, duplicate])

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_duplicate_nodeids={junit} count=1 preview={[duplicate]!r}"
    ]


def test_validate_backend_integration_artifacts_rejects_multiple_nodeids_per_case(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    _write_collect(
        collect,
        [
            "tests/integration/test_sample.py::test_one",
            "tests/integration/test_sample.py::test_two",
        ],
    )
    _write_junit_body(
        junit,
        """
        <testcase classname="tests.integration.sample" name="test_one">
          <properties>
            <property name="nodeid" value="tests/integration/test_sample.py::test_one" />
            <property name="nodeid" value="tests/integration/test_sample.py::test_two" />
          </properties>
        </testcase>
        """,
    )

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_multiple_nodeid_properties={junit} "
        "count=1 preview=tests.integration.sample::test_one"
    ]


def test_validate_backend_integration_artifacts_rejects_failed_and_error_outcomes(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    _write_collect(
        collect,
        [
            "tests/integration/test_sample.py::test_failed",
            "tests/integration/test_sample.py::test_error",
        ],
    )
    _write_junit_body(
        junit,
        """
        <testcase classname="tests.integration.sample" name="test_failed">
          <properties>
            <property name="nodeid" value="tests/integration/test_sample.py::test_failed" />
          </properties>
          <failure message="failed">boom</failure>
        </testcase>
        <testcase classname="tests.integration.sample" name="test_error">
          <properties>
            <property name="nodeid" value="tests/integration/test_sample.py::test_error" />
          </properties>
          <error message="error">boom</error>
        </testcase>
        """,
    )

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_failures={junit} count=1",
        f"junit_errors={junit} count=1",
    ]


def test_validate_backend_integration_artifacts_rejects_skipped_outcomes_by_default(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "required-integration-collect.txt"
    junit = tmp_path / "required-integration.xml"
    _write_collect(collect, ["tests/integration/test_sample.py::test_skipped"])
    _write_junit_body(
        junit,
        """
        <testcase classname="tests.integration.sample" name="test_skipped">
          <properties>
            <property name="nodeid" value="tests/integration/test_sample.py::test_skipped" />
          </properties>
          <skipped message="external stack unavailable" />
        </testcase>
        """,
    )

    errors = validator.validate_pairs([collect])

    assert errors == [
        f"junit_all_skipped={junit}",
        f"junit_skipped={junit} "
        "classname=tests.integration.sample name=test_skipped",
    ]


def test_validate_backend_integration_artifacts_allows_known_nightly_oom_skip(
    tmp_path: Path,
):
    validator = _load_validator_module()
    collect = tmp_path / "heavy-docker-integration-collect.txt"
    junit = tmp_path / "heavy-docker-integration.xml"
    _write_collect(
        collect,
        [
            "tests/integration/test_sample.py::test_passed",
            "tests/integration/test_oom_e2e.py::test_oom_kill_sets_oom_killed_true",
        ],
    )
    _write_junit_body(
        junit,
        """
        <testcase classname="tests.integration.sample" name="test_passed">
          <properties>
            <property name="nodeid" value="tests/integration/test_sample.py::test_passed" />
          </properties>
        </testcase>
        <testcase classname="tests.integration.test_oom_e2e" name="test_oom_kill_sets_oom_killed_true">
          <properties>
            <property name="nodeid" value="tests/integration/test_oom_e2e.py::test_oom_kill_sets_oom_killed_true" />
          </properties>
          <skipped message="QAP_TEST_OOM=1 opt-in not set" />
        </testcase>
        """,
    )

    assert validator.validate_pairs([collect], allow_nightly_oom_skips=True) == []
    assert validator.validate_pairs(
        [collect],
        strict_skips=True,
        allow_nightly_oom_skips=True,
    ) == [
        f"junit_skipped={junit} "
        "classname=tests.integration.test_oom_e2e "
        "name=test_oom_kill_sets_oom_killed_true"
    ]


def test_integration_conftest_writes_nodeids_to_real_pytest_junit(tmp_path: Path):
    (tmp_path / "conftest.py").write_text(
        "from tests.integration.conftest import pytest_collection_modifyitems\n",
        encoding="utf-8",
    )
    (tmp_path / "test_sample.py").write_text(
        "def test_one():\n    assert True\n",
        encoding="utf-8",
    )
    junit = tmp_path / "junit.xml"
    env = {
        **os.environ,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": f"{ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(junit),
            str(tmp_path / "test_sample.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    values = [
        prop.attrib.get("value")
        for prop in ET.parse(junit).getroot().findall(".//property[@name='nodeid']")
    ]
    assert values == ["test_sample.py::test_one"]
