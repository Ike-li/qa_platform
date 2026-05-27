from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qaplatform.plugins.builtin.junit_collector import JUnitCollector
from qaplatform.plugins.protocols import CollectorProtocol


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

        assert len(results) == 2
        assert results[0].name == "test_pass"
        assert results[0].status == "passed"
        assert results[0].duration_ms == 100
        assert results[1].name == "test_fail"
        assert results[1].status == "failed"
        assert results[1].error_message == "assertion failed"
        assert results[1].stack_trace == "Traceback..."

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

        assert len(results) == 2
        assert results[0].suite == "s1"
        assert results[1].suite == "s2"

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

        assert len(results) == 1
        assert results[0].name == "测试通过"
        assert results[0].suite == "套件"
        assert results[0].error_message == "断言失败"


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

        assert result.status == "failed"
        assert result.error_message == "boom"
        assert result.stack_trace == "stack"

    def test_with_error(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="t" classname="c" time="0">'
            '<error message="runtime error">trace</error>'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "c")

        assert result.status == "error"
        assert result.error_message == "runtime error"
        assert result.stack_trace == "trace"

    def test_skipped(self):
        import xml.etree.ElementTree as ET

        elem = ET.fromstring(
            '<testcase name="t" classname="c" time="0">'
            '<skipped message="not implemented"/>'
            "</testcase>"
        )
        result = self._make_collector()._parse_testcase(elem, "c")

        assert result.status == "skipped"
        assert result.error_message == "not implemented"

    def test_no_attributes(self):
        """A bare testcase with no attributes defaults gracefully."""
        import xml.etree.ElementTree as ET

        elem = ET.fromstring("<testcase/>")
        result = self._make_collector()._parse_testcase(elem, "fallback_suite")

        assert result.name == "unknown"
        assert result.suite == "fallback_suite"
        assert result.status == "passed"
        assert result.duration_ms == 0


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

        assert len(results) == 1
        assert results[0].name == "ok"

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

        assert artifact is not None
        assert artifact.name == "junit.xml"
        mock_s3.put_object.assert_awaited_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-bucket"
        assert call_kwargs["Key"] == f"reports/{run_id}/junit.xml"

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
