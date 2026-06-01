from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import json
import logging
import math
import os
import shlex
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from qaplatform.plugins.builtin._paths import safe_workspace_output_path, safe_workspace_paths
from qaplatform.plugins.protocols import TestRunResult

log = logging.getLogger(__name__)

_DEFAULT_JUNIT_XML = "results/junit.xml"
_DEFAULT_JSON_OUTPUT = "results/go-test.json"
_GO_JUNIT_HELPER_PATH = "/tmp/qaplatform-go-junit.go"
_GO_JUNIT_HELPER_SOURCE = r"""
package main

import (
	"bufio"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type Event struct {
	Action  string  `json:"Action"`
	Package string  `json:"Package"`
	Test    string  `json:"Test"`
	Output  string  `json:"Output"`
	Elapsed any     `json:"Elapsed"`
}

type TestRecord struct {
	Action  string
	Elapsed float64
}

type Case struct {
	Package string
	Name    string
	Status  string
	Elapsed float64
	Output  string
}

type Testsuites struct {
	XMLName  xml.Name    `xml:"testsuites"`
	Tests    int         `xml:"tests,attr"`
	Failures int         `xml:"failures,attr"`
	Errors   int         `xml:"errors,attr"`
	Skipped  int         `xml:"skipped,attr"`
	Suites   []Testsuite `xml:"testsuite"`
}

type Testsuite struct {
	Name     string     `xml:"name,attr"`
	Tests    int        `xml:"tests,attr"`
	Failures int        `xml:"failures,attr"`
	Errors   int        `xml:"errors,attr"`
	Skipped  int        `xml:"skipped,attr"`
	Cases    []Testcase `xml:"testcase"`
}

type Testcase struct {
	Classname string   `xml:"classname,attr"`
	Name      string   `xml:"name,attr"`
	Time      string   `xml:"time,attr"`
	Failure   *Message `xml:"failure,omitempty"`
	Error     *Message `xml:"error,omitempty"`
	Skipped   *Message `xml:"skipped,omitempty"`
}

type Message struct {
	Message string `xml:"message,attr,omitempty"`
	Text    string `xml:",chardata"`
}

func key(pkg string, test string) string {
	return pkg + "\x00" + test
}

func splitKey(value string) (string, string) {
	parts := strings.SplitN(value, "\x00", 2)
	if len(parts) != 2 {
		return "unknown", value
	}
	return parts[0], parts[1]
}

func statusFor(action string) string {
	switch action {
	case "pass":
		return "passed"
	case "fail":
		return "failed"
	case "skip":
		return "skipped"
	default:
		return ""
	}
}

func normalizeElapsed(value float64) float64 {
	if value < 0 || math.IsNaN(value) || math.IsInf(value, 0) {
		return 0
	}
	return value
}

func safeElapsed(value any) float64 {
	switch typed := value.(type) {
	case nil:
		return 0
	case float64:
		return normalizeElapsed(typed)
	case string:
		parsed, err := strconv.ParseFloat(strings.TrimSpace(typed), 64)
		if err != nil {
			return 0
		}
		return normalizeElapsed(parsed)
	default:
		return 0
	}
}

func parseCases(path string) ([]Case, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	records := map[string]TestRecord{}
	testOutput := map[string]string{}
	packageOutput := map[string]string{}
	packageActions := map[string]string{}

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 10*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var event Event
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			continue
		}
		pkg := event.Package
		if pkg == "" {
			pkg = "unknown"
		}
		if event.Action == "output" {
			if event.Test != "" {
				k := key(pkg, event.Test)
				testOutput[k] += event.Output
			} else {
				packageOutput[pkg] += event.Output
			}
			continue
		}
		if event.Test != "" {
			if statusFor(event.Action) != "" {
				records[key(pkg, event.Test)] = TestRecord{
					Action:  event.Action,
					Elapsed: safeElapsed(event.Elapsed),
				}
			}
			continue
		}
		if event.Package != "" && statusFor(event.Action) != "" {
			packageActions[pkg] = event.Action
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}

	keys := make([]string, 0, len(records))
	failedPackages := map[string]bool{}
	for k, record := range records {
		keys = append(keys, k)
		if record.Action == "fail" {
			pkg, _ := splitKey(k)
			failedPackages[pkg] = true
		}
	}
	sort.Strings(keys)

	cases := make([]Case, 0, len(keys))
	for _, k := range keys {
		pkg, test := splitKey(k)
		record := records[k]
		cases = append(cases, Case{
			Package: pkg,
			Name:    test,
			Status:  statusFor(record.Action),
			Elapsed: record.Elapsed,
			Output:  strings.TrimSpace(testOutput[k]),
		})
	}

	packages := make([]string, 0, len(packageActions))
	for pkg := range packageActions {
		packages = append(packages, pkg)
	}
	sort.Strings(packages)
	for _, pkg := range packages {
		if packageActions[pkg] != "fail" || failedPackages[pkg] {
			continue
		}
		output := strings.TrimSpace(packageOutput[pkg])
		if output == "" {
			output = "go test package failed"
		}
		cases = append(cases, Case{
			Package: pkg,
			Name:    "package_error",
			Status:  "error",
			Output:  output,
		})
	}

	return cases, nil
}

func buildJUnit(cases []Case) Testsuites {
	byPackage := map[string][]Case{}
	for _, c := range cases {
		byPackage[c.Package] = append(byPackage[c.Package], c)
	}

	packages := make([]string, 0, len(byPackage))
	for pkg := range byPackage {
		packages = append(packages, pkg)
	}
	sort.Strings(packages)

	result := Testsuites{}
	for _, pkg := range packages {
		suite := Testsuite{Name: pkg}
		for _, c := range byPackage[pkg] {
			tc := Testcase{
				Classname: c.Package,
				Name:      c.Name,
				Time:      fmt.Sprintf("%.6f", c.Elapsed),
			}
			switch c.Status {
			case "failed":
				tc.Failure = &Message{Message: "go test failed", Text: c.Output}
				suite.Failures++
				result.Failures++
			case "error":
				tc.Error = &Message{Message: "go test package failed", Text: c.Output}
				suite.Errors++
				result.Errors++
			case "skipped":
				tc.Skipped = &Message{Message: "go test skipped", Text: c.Output}
				suite.Skipped++
				result.Skipped++
			}
			suite.Tests++
			result.Tests++
			suite.Cases = append(suite.Cases, tc)
		}
		result.Suites = append(result.Suites, suite)
	}
	return result
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: qaplatform-go-junit <go-test-json> <junit-xml>")
		os.Exit(2)
	}
	cases, err := parseCases(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := os.MkdirAll(filepath.Dir(os.Args[2]), 0755); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	file, err := os.Create(os.Args[2])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer file.Close()

	if _, err := file.WriteString(xml.Header); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	encoder := xml.NewEncoder(file)
	encoder.Indent("", "  ")
	if err := encoder.Encode(buildJUnit(cases)); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if _, err := file.WriteString("\n"); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
""".strip()


@dataclass(frozen=True)
class _GoTestCase:
    package: str
    name: str
    status: str
    elapsed: float = 0.0
    output: str = ""


class GoTestRunner:
    """Built-in Go test runner plugin implementing RunnerProtocol.

    Runs ``go test -v -json``, parses the NDJSON output for per-test results,
    and returns a structured TestRunResult.
    """

    name = "go_test"

    def build_command(self, config: dict[str, Any]) -> str:
        """Return the shell command to execute this runner inside a container."""
        cmd = self._build_command(config)
        junit_xml = self._junit_xml_path(config)
        json_output = self._json_output_path(config)
        stderr_output = self._stderr_output_path(json_output)
        pipe_output = self._pipe_output_path(json_output)
        parents = self._mkdir_parents(junit_xml, json_output, stderr_output, pipe_output)
        test_command = " ".join(shlex.quote(part) for part in cmd)

        return "\n".join(
            [
                "cd /workspace && "
                f"mkdir -p {parents} && "
                f"cat > {shlex.quote(_GO_JUNIT_HELPER_PATH)} <<'QAP_GO_JUNIT'",
                _GO_JUNIT_HELPER_SOURCE,
                "QAP_GO_JUNIT",
                f"rm -f {shlex.quote(pipe_output)}",
                f"mkfifo {shlex.quote(pipe_output)}",
                f"tee {shlex.quote(json_output)} < {shlex.quote(pipe_output)} &",
                "tee_pid=$!",
                f"{test_command} > {shlex.quote(pipe_output)} "
                f"2> {shlex.quote(stderr_output)}",
                "status=$?",
                'wait "$tee_pid" || true',
                f"rm -f {shlex.quote(pipe_output)}",
                f"if [ -s {shlex.quote(stderr_output)} ]; "
                f"then cat {shlex.quote(stderr_output)} >&2; fi",
                "GO111MODULE=off GOTOOLCHAIN=local "
                f"go run {shlex.quote(_GO_JUNIT_HELPER_PATH)} "
                f"{shlex.quote(json_output)} {shlex.quote(junit_xml)} || true",
                "exit $status",
            ]
        )

    async def run_tests(
        self,
        working_dir: Path,
        config: dict[str, Any],
        env_vars: dict[str, str] | None = None,
    ) -> TestRunResult:
        cmd = self._build_command(config)
        log.info("running go test: %s (cwd=%s)", " ".join(cmd), working_dir)

        env_override = None
        if env_vars:
            env_override = os.environ.copy()
            env_override.update(env_vars)

        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(working_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_override,
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

        json_path = working_dir / self._json_output_path(config)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(stdout, encoding="utf-8")
        self._write_junit_xml(working_dir / self._junit_xml_path(config), stdout)

        counts = self._parse_ndjson(stdout)

        return TestRunResult(
            passed=counts["passed"],
            failed=counts["failed"],
            skipped=counts["skipped"],
            error=counts["error"],
            duration_ms=elapsed_ms,
            exit_code=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
        )

    # --------------------------------------------------------------------- #
    # private helpers
    # --------------------------------------------------------------------- #

    def _build_command(self, config: dict[str, Any]) -> list[str]:
        """Build the go test CLI command from plugin config."""
        cmd = ["go", "test", "-v", "-json"]

        extra_args = config.get("args", [])
        if isinstance(extra_args, str):
            extra_args = shlex.split(extra_args)
        cmd.extend(extra_args)

        test_paths = safe_workspace_paths(
            config.get("test_paths"),
            ["./..."],
            field="test_paths",
        )
        cmd.extend(test_paths)

        return cmd

    @staticmethod
    def _parse_ndjson(stdout: str) -> dict[str, int]:
        """Parse ``go test -json`` NDJSON output to extract per-test counts.

        Each line is a JSON object with ``Action`` and ``Test`` fields.
        We track final results (pass/fail/skip) per unique ``(Package, Test)``
        pair so that sub-test duplicates do not inflate counts.
        """
        passed = failed = skipped = error = 0

        for case in GoTestRunner._parse_cases(stdout):
            if case.status == "passed":
                passed += 1
            elif case.status == "failed":
                failed += 1
            elif case.status == "skipped":
                skipped += 1
            elif case.status == "error":
                error += 1

        return {"passed": passed, "failed": failed, "skipped": skipped, "error": error}

    @staticmethod
    def _junit_xml_path(config: dict[str, Any]) -> str:
        return safe_workspace_output_path(
            config.get("junit_xml"),
            _DEFAULT_JUNIT_XML,
            field="junit_xml",
        )

    @staticmethod
    def _json_output_path(config: dict[str, Any]) -> str:
        return safe_workspace_output_path(
            config.get("json_output"),
            _DEFAULT_JSON_OUTPUT,
            field="json_output",
        )

    @staticmethod
    def _stderr_output_path(json_output: str) -> str:
        return f"{json_output}.stderr"

    @staticmethod
    def _pipe_output_path(json_output: str) -> str:
        return f"{json_output}.pipe"

    @staticmethod
    def _mkdir_parents(*paths: str) -> str:
        parents = []
        for path in paths:
            parent = PurePosixPath(path).parent.as_posix()
            if parent not in parents:
                parents.append(parent)
        return " ".join(shlex.quote(parent) for parent in parents)

    @staticmethod
    def _status_for_action(action: str) -> str:
        if action == "pass":
            return "passed"
        if action == "fail":
            return "failed"
        if action == "skip":
            return "skipped"
        return ""

    @staticmethod
    def _parse_cases(stdout: str) -> list[_GoTestCase]:
        records: dict[tuple[str, str], dict[str, Any]] = {}
        test_output: defaultdict[tuple[str, str], str] = defaultdict(str)
        package_output: defaultdict[str, str] = defaultdict(str)
        package_actions: dict[str, str] = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            action = str(event.get("Action", ""))
            package = str(event.get("Package") or "unknown")
            test = str(event.get("Test") or "")

            if action == "output":
                output = str(event.get("Output") or "")
                if test:
                    test_output[(package, test)] += output
                else:
                    package_output[package] += output
                continue

            status = GoTestRunner._status_for_action(action)
            if not status:
                continue

            if test:
                records[(package, test)] = {
                    "status": status,
                    "elapsed": GoTestRunner._safe_elapsed(event.get("Elapsed")),
                }
                continue

            if event.get("Package"):
                package_actions[package] = action

        cases = [
            _GoTestCase(
                package=package,
                name=test,
                status=str(record["status"]),
                elapsed=float(record["elapsed"]),
                output=test_output[(package, test)].strip(),
            )
            for (package, test), record in sorted(records.items())
        ]

        failed_packages = {
            package
            for (package, _), record in records.items()
            if record["status"] == "failed"
        }
        for package, action in sorted(package_actions.items()):
            if action != "fail" or package in failed_packages:
                continue
            output = package_output[package].strip() or "go test package failed"
            cases.append(
                _GoTestCase(
                    package=package,
                    name="package_error",
                    status="error",
                    output=output,
                )
            )

        return cases

    @staticmethod
    def _safe_elapsed(value: object) -> float:
        try:
            elapsed = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(elapsed) or elapsed < 0:
            return 0.0
        return elapsed

    @staticmethod
    def _write_junit_xml(junit_path: Path, stdout: str) -> None:
        cases = GoTestRunner._parse_cases(stdout)
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element(
            "testsuites",
            {
                "tests": str(len(cases)),
                "failures": str(sum(1 for case in cases if case.status == "failed")),
                "errors": str(sum(1 for case in cases if case.status == "error")),
                "skipped": str(sum(1 for case in cases if case.status == "skipped")),
            },
        )

        by_package: dict[str, list[_GoTestCase]] = defaultdict(list)
        for case in cases:
            by_package[case.package].append(case)

        for package, package_cases in sorted(by_package.items()):
            suite = ET.SubElement(
                root,
                "testsuite",
                {
                    "name": package,
                    "tests": str(len(package_cases)),
                    "failures": str(
                        sum(1 for case in package_cases if case.status == "failed")
                    ),
                    "errors": str(
                        sum(1 for case in package_cases if case.status == "error")
                    ),
                    "skipped": str(
                        sum(1 for case in package_cases if case.status == "skipped")
                    ),
                },
            )
            for case in package_cases:
                testcase = ET.SubElement(
                    suite,
                    "testcase",
                    {
                        "classname": case.package,
                        "name": case.name,
                        "time": f"{case.elapsed:.6f}",
                    },
                )
                if case.status == "failed":
                    failure = ET.SubElement(
                        testcase,
                        "failure",
                        {"message": "go test failed"},
                    )
                    failure.text = case.output
                elif case.status == "error":
                    error = ET.SubElement(
                        testcase,
                        "error",
                        {"message": "go test package failed"},
                    )
                    error.text = case.output
                elif case.status == "skipped":
                    skipped = ET.SubElement(
                        testcase,
                        "skipped",
                        {"message": "go test skipped"},
                    )
                    skipped.text = case.output

        tree = ET.ElementTree(root)
        tree.write(junit_path, encoding="utf-8", xml_declaration=True)
