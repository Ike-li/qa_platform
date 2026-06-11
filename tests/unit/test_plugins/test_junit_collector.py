from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qaplatform.plugins.builtin.junit_collector import JUnitCollector
from qaplatform.plugins.protocols import ArtifactData, CollectorProtocol, TestResultData


class TestJUnitCollectorProtocol:
    """Verify JUnitCollector satisfies CollectorProtocol."""

    def test_implements_protocol(self):
        collector = JUnitCollector()
        assert isinstance(collector, CollectorProtocol)

    def test_has_name(self):
        collector = JUnitCollector()
        assert collector.name == "junit"


class TestParseJunitXml:
    """Test _parse_junit_xml with various XML structures."""

    def test_normal_xml(self, tmp_path):
        xml = """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="suite1" tests="2">
    <testcase name="test_pass" classname="suite1" time="0.1"/>
    <testcase name="test_fail" classname="suite1" time="0.2">
      <failure message="assertion failed">Traceback...</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml)

        collector = JUnitCollector()
        results = collector._parse_junit_xml(xml_path)

        assert results == [
            TestResultData(
                suite="suite1",
                name="test_pass",
                status="passed",
                duration_ms=100,
            ),
            TestResultData(
                suite="suite1",
                name="test_fail",
                status="failed",
                duration_ms=200,
                error_message="assertion failed",
                stack_trace="Traceback...",
            ),
        ]

    def test_nested_testsuites(self, tmp_path):
        xml = """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="s1" tests="1">
    <testcase name="a" classname="s1" time="0.01"/>
  </testsuite>
  <testsuite name="s2" tests="1">
    <testcase name="b" classname="s2" time="0.02"/>
  </testsuite>
</testsuites>"""
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml)

        collector = JUnitCollector()
        results = collector._parse_junit_xml(xml_path)

        assert results == [
            TestResultData(suite="s1", name="a", status="passed", duration_ms=10),
            TestResultData(suite="s2", name="b", status="passed", duration_ms=20),
        ]

    def test_empty_xml_returns_empty(self, tmp_path):
        """An XML file with no testcases returns an empty list."""
        xml = '<?xml version="1.0" ?><testsuites/>'
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml)

        collector = JUnitCollector()
        results = collector._parse_junit_xml(xml_path)

        assert results == []

    def test_malformed_xml_returns_empty(self, tmp_path):
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text("not xml at all {{{")

        collector = JUnitCollector()
        results = collector._parse_junit_xml(xml_path)

        assert results == []

    def test_chinese_characters(self, tmp_path):
        xml = """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="套件" tests="1">
    <testcase name="测试通过" classname="套件" time="0.5">
      <failure message="断言失败">堆栈信息</failure>
    </testcase>
  </testsuite>
</testsuites>"""
        xml_path = tmp_path / "junit.xml"
        xml_path.write_text(xml, encoding="utf-8")

        collector = JUnitCollector()
        results = collector._parse_junit_xml(xml_path)

        assert results == [
            TestResultData(
                suite="套件",
                name="测试通过",
                status="failed",
                duration_ms=500,
                error_message="断言失败",
                stack_trace="堆栈信息",
            )
        ]


class TestParseTestcase:
    """Test _parse_testcase with various child elements."""

    def _make_collector(self):
        return JUnitCollector()

    def test_with_failure(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="t" classname="c" time="0.1">'
            '<failure message="boom">stack</failure>'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "c")

        assert result == TestResultData(
            suite="c",
            name="t",
            status="failed",
            duration_ms=100,
            error_message="boom",
            stack_trace="stack",
        )

    def test_with_error(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="t" classname="c" time="0">'
            '<error message="runtime error">trace</error>'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "c")

        assert result == TestResultData(
            suite="c",
            name="t",
            status="error",
            error_message="runtime error",
            stack_trace="trace",
        )

    def test_skipped(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="t" classname="c" time="0">'
            '<skipped message="not implemented"/>'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "c")

        assert result == TestResultData(
            suite="c",
            name="t",
            status="skipped",
            error_message="not implemented",
        )

    def test_pytest_xfail_skipped_node_preserves_xfail_status(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="test_expected_failure" classname="test_xfail" time="0">'
            '<skipped type="pytest.xfail" message="known" />'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "pytest")

        assert result == TestResultData(
            suite="test_xfail",
            name="test_expected_failure",
            status="xfail",
            error_message="known",
        )

    def test_no_attributes(self):
        """A bare testcase with no attributes defaults gracefully."""
        import xml.etree.ElementTree as ET

        elem = ET.fromstring("<testcase/>")
        result = self._make_collector()._parse_testcase(elem, "fallback_suite")

        assert result == TestResultData(
            suite="fallback_suite",
            name="unknown",
            status="passed",
        )

    @pytest.mark.parametrize("raw_time", ["not-a-number", "", "nan", "inf", "-0.001"])
    def test_invalid_time_defaults_to_zero_without_dropping_result(self, raw_time):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            f'<testcase name="kept" classname="suite" time="{raw_time}" />'
        )
        result = self._make_collector()._parse_testcase(elem, "fallback_suite")

        assert result == TestResultData(suite="suite", name="kept", status="passed")


class TestCollect:
    """Test the async collect() method."""

    @pytest.mark.asyncio
    async def test_collect_with_xml(self, tmp_path):
        xml = """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="s" tests="1">
    <testcase name="ok" classname="s" time="0.1"/>
  </testsuite>
</testsuites>"""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "junit.xml").write_text(xml)

        collector = JUnitCollector()
        run_id = uuid4()
        results = await collector.collect(run_id, tmp_path)

        assert results == [
            TestResultData(suite="s", name="ok", status="passed", duration_ms=100)
        ]

    @pytest.mark.asyncio
    async def test_collect_uses_configured_relative_path(self, tmp_path):
        xml = """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="custom" tests="1">
    <testcase name="from-custom-path" classname="custom" time="0.1"/>
  </testsuite>
</testsuites>"""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "junit.xml").write_text(xml)

        collector = JUnitCollector()
        run_id = uuid4()
        results = await collector.collect(
            run_id,
            tmp_path,
            {"path": "custom/junit.xml"},
        )

        assert results == [
            TestResultData(
                suite="custom",
                name="from-custom-path",
                status="passed",
                duration_ms=100,
            )
        ]

    @pytest.mark.asyncio
    async def test_collect_rejects_configured_path_outside_working_dir(self, tmp_path):
        outside_report = tmp_path.parent / "junit.xml"
        outside_report.write_text(
            """\
<?xml version="1.0" ?>
<testsuites>
  <testsuite name="outside" tests="1">
    <testcase name="must-not-be-read" classname="outside" time="0.1"/>
  </testsuite>
</testsuites>"""
        )

        collector = JUnitCollector()
        run_id = uuid4()

        assert await collector.collect(run_id, tmp_path, {"path": "../junit.xml"}) == []
        assert await collector.collect(run_id, tmp_path, {"path": str(outside_report)}) == []

    @pytest.mark.asyncio
    async def test_collect_no_report_returns_empty(self, tmp_path):
        """When results/junit.xml does not exist, returns empty list."""
        collector = JUnitCollector()
        run_id = uuid4()
        results = await collector.collect(run_id, tmp_path)

        assert results == []

    @pytest.mark.asyncio
    async def test_upload_report(self, tmp_path):
        xml = b'<testsuites/>'
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "junit.xml").write_bytes(xml)

        mock_s3 = AsyncMock()
        collector = JUnitCollector()
        run_id = uuid4()

        artifact = await collector.upload_report(run_id, tmp_path, mock_s3, "my-bucket")

        assert artifact == ArtifactData(
            name="junit.xml",
            type="report",
            local_path=results_dir / "junit.xml",
            mime_type="application/xml",
        )
        mock_s3.put_object.assert_awaited_once()
        assert mock_s3.put_object.await_args.kwargs == {
            "Bucket": "my-bucket",
            "Key": f"reports/{run_id}/junit.xml",
            "Body": xml,
            "ContentType": "application/xml",
        }

    @pytest.mark.asyncio
    async def test_upload_report_no_file(self, tmp_path):
        mock_s3 = AsyncMock()
        collector = JUnitCollector()
        run_id = uuid4()

        artifact = await collector.upload_report(run_id, tmp_path, mock_s3, "bucket")

        assert artifact is None
        mock_s3.put_object.assert_not_awaited()


class TestRegistration:
    """Test that JUnitCollector is registered in builtins."""

    def test_register_builtins_includes_junit(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "junit" in registry.collector_names


class TestParseJunitXmlContent:
    """In-memory 纯函数 parse_junit_xml_content 的解析边界。"""

    def _parse(self, xml: str | bytes):
        from qaplatform.plugins.builtin.junit_collector import parse_junit_xml_content

        return parse_junit_xml_content(xml)

    def test_accepts_bytes_and_str_equally(self):
        xml = '<testsuite name="s"><testcase classname="c" name="t" time="0.1"/></testsuite>'
        assert self._parse(xml) == self._parse(xml.encode())

    def test_multiple_testsuites_under_testsuites_root(self):
        xml = """<testsuites>
          <testsuite name="s1"><testcase classname="c1" name="a"/></testsuite>
          <testsuite name="s2"><testcase classname="c2" name="b"/></testsuite>
        </testsuites>"""
        results = self._parse(xml)
        assert [(r.suite, r.name) for r in results] == [("c1", "a"), ("c2", "b")]

    def test_nested_testsuite_elements_are_parsed(self):
        xml = """<testsuites>
          <testsuite name="outer">
            <testcase classname="c" name="top"/>
            <testsuite name="inner">
              <testcase classname="c" name="nested"/>
            </testsuite>
          </testsuite>
        </testsuites>"""
        results = self._parse(xml)
        assert [r.name for r in results] == ["top", "nested"]

    def test_bare_testsuite_root(self):
        xml = '<testsuite name="s"><testcase classname="c" name="t"/></testsuite>'
        assert [r.name for r in self._parse(xml)] == ["t"]

    def test_parametrized_case_names_preserved_verbatim(self):
        name = "test_calc[3+5-8,negative -1]"
        xml = f'<testsuite name="s"><testcase classname="c" name="{name}"/></testsuite>'
        assert self._parse(xml)[0].name == name

    def test_missing_classname_falls_back_to_testsuite_name(self):
        xml = '<testsuite name="fallback-suite"><testcase name="t"/></testsuite>'
        assert self._parse(xml)[0].suite == "fallback-suite"

    def test_missing_name_and_time_default(self):
        xml = '<testsuite name="s"><testcase classname="c"/></testsuite>'
        result = self._parse(xml)[0]
        assert result.name == "unknown"
        assert result.duration_ms == 0

    def test_invalid_and_negative_time_count_as_zero(self):
        xml = """<testsuite name="s">
          <testcase classname="c" name="bad" time="abc"/>
          <testcase classname="c" name="neg" time="-1"/>
        </testsuite>"""
        assert [r.duration_ms for r in self._parse(xml)] == [0, 0]

    def test_failure_error_skipped_xfail_statuses(self):
        xml = """<testsuite name="s">
          <testcase classname="c" name="f"><failure message="m">tb</failure></testcase>
          <testcase classname="c" name="e"><error message="m">tb</error></testcase>
          <testcase classname="c" name="s1"><skipped message="m"/></testcase>
          <testcase classname="c" name="x"><skipped type="pytest.xfail" message="m"/></testcase>
        </testsuite>"""
        assert [r.status for r in self._parse(xml)] == [
            "failed",
            "error",
            "skipped",
            "xfail",
        ]

    def test_unparseable_content_raises_junit_parse_error(self):
        from qaplatform.plugins.builtin.junit_collector import JUnitParseError

        with pytest.raises(JUnitParseError):
            self._parse("<testsuite><unclosed")

    def test_non_junit_root_yields_no_results(self):
        assert self._parse("<report><item/></report>") == []

    def test_file_path_wrapper_delegates_and_keeps_parse_error_contract(self, tmp_path):
        bad = tmp_path / "junit.xml"
        bad.write_text("not xml at all <")
        collector = JUnitCollector()
        assert collector._parse_junit_xml(bad) == []
