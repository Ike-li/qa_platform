from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from uuid import UUID

from qaplatform.plugins.protocols import ArtifactData, TestResultData

log = logging.getLogger(__name__)

_STATUS_MAP = {
    "passed": "passed",
    "failure": "failed",
    "error": "error",
    "skipped": "skipped",
}


class JUnitParseError(ValueError):
    """Raised when JUnit XML content is not well-formed XML."""


def parse_junit_xml_content(content: bytes | str) -> list[TestResultData]:
    """Parse in-memory JUnit XML content into TestResultData objects.

    Accepts ``<testsuites>`` roots, bare ``<testsuite>`` roots, and nested
    ``<testsuite>`` elements (some CI tools emit suites inside suites).
    Raises :class:`JUnitParseError` when the document cannot be parsed at all;
    individual missing attributes are tolerated (name/classname fall back,
    missing ``time`` counts as 0).
    """
    try:
        root = ET.fromstring(content)  # noqa: S314
    except ET.ParseError as exc:
        raise JUnitParseError(str(exc)) from exc

    results: list[TestResultData] = []
    for suite_elem in root.iter("testsuite"):
        suite_name = suite_elem.get("name", "unknown")
        for tc_elem in suite_elem.findall("testcase"):
            results.append(parse_junit_testcase(tc_elem, suite_name))
    return results


def parse_junit_testcase(elem: ET.Element, suite_name: str) -> TestResultData:
    """Parse a single ``<testcase>`` element."""
    name = elem.get("name", "unknown")
    classname = elem.get("classname", suite_name)

    # Duration: JUnit XML uses "time" attribute (seconds).
    duration_ms = _parse_duration_ms(elem.get("time", "0"))

    # Status determination
    status = "passed"
    error_message: str | None = None
    stack_trace: str | None = None

    failure = elem.find("failure")
    error = elem.find("error")
    skipped = elem.find("skipped")

    if failure is not None:
        status = "failed"
        error_message = failure.get("message", "")
        stack_trace = failure.text or ""
    elif error is not None:
        status = "error"
        error_message = error.get("message", "")
        stack_trace = error.text or ""
    elif skipped is not None:
        status = "xfail" if skipped.get("type") == "pytest.xfail" else "skipped"
        error_message = skipped.get("message")

    return TestResultData(
        suite=classname,
        name=name,
        status=status,
        duration_ms=duration_ms,
        error_message=error_message,
        stack_trace=stack_trace.strip() if stack_trace else None,
    )


def _parse_duration_ms(raw_time: str | None) -> int:
    try:
        time_sec = float(raw_time or "0")
    except ValueError:
        return 0
    if not math.isfinite(time_sec) or time_sec < 0:
        return 0
    return int(time_sec * 1000)


class JUnitCollector:
    """Built-in JUnit XML collector plugin implementing CollectorProtocol.

    Parses JUnit XML files produced by pytest (or other runners) and converts
    them into TestResultData objects.
    """

    name = "junit"

    async def collect(
        self,
        run_id: UUID,
        working_dir: Path,
        config: dict[str, Any] | None = None,
    ) -> list[TestResultData]:
        xml_path = self._resolve_xml_path(working_dir, config or {})
        if xml_path is None:
            return []
        if not xml_path.exists():
            log.warning("JUnit XML not found at %s", xml_path)
            return []

        return self._parse_junit_xml(xml_path)

    async def upload_report(
        self,
        run_id: UUID,
        working_dir: Path,
        s3_client: Any,
        bucket: str,
    ) -> ArtifactData | None:
        """Upload the JUnit XML report to S3 and return artifact metadata."""
        xml_path = working_dir / "results" / "junit.xml"
        if not xml_path.exists():
            return None

        s3_key = f"reports/{run_id}/junit.xml"
        content = xml_path.read_bytes()

        await s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=content,
            ContentType="application/xml",
        )

        return ArtifactData(
            name="junit.xml",
            type="report",
            local_path=xml_path,
            mime_type="application/xml",
        )

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    def _resolve_xml_path(
        self,
        working_dir: Path,
        config: dict[str, Any],
    ) -> Path | None:
        raw_path = config.get("path") or config.get("junit_xml") or "results/junit.xml"
        path = Path(str(raw_path))
        if path.is_absolute():
            log.warning("Ignoring absolute JUnit XML path: %s", path)
            return None

        root = working_dir.resolve()
        candidate = (working_dir / path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            log.warning("Ignoring JUnit XML path outside working dir: %s", path)
            return None
        return candidate

    def _parse_junit_xml(self, xml_path: Path) -> list[TestResultData]:
        """Parse a JUnit XML file into a list of TestResultData."""
        try:
            return parse_junit_xml_content(xml_path.read_bytes())
        except JUnitParseError:
            log.exception("failed to parse JUnit XML: %s", xml_path)
            return []

    def _parse_testcase(self, elem: ET.Element, suite_name: str) -> TestResultData:
        """Parse a single <testcase> element."""
        return parse_junit_testcase(elem, suite_name)
