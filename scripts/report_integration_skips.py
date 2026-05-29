#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


def _skip_reason(skipped: ET.Element) -> str:
    message = skipped.attrib.get("message")
    if message:
        return message.strip()
    if skipped.text and skipped.text.strip():
        return skipped.text.strip()
    return "<missing skip reason>"


def classify_reason(reason: str) -> str:
    text = reason.lower()
    if "run_integration_tests=1" in text:
        return "env_gate.integration_opt_in"
    if "run_performance_tests=1" in text:
        return "env_gate.performance_opt_in"
    if "qap_test_oom=1" in text or "oom" in text and "opt" in text:
        return "env_gate.oom_opt_in"
    if "external stack" in text or "qap_external_stack_required" in text:
        return "infra.external_stack"
    if "docker daemon" in text or "docker is not available" in text:
        return "infra.docker_daemon"
    if "docker image prerequisite" in text or "registry" in text:
        return "infra.docker_image"
    return "unknown"


def gate_policy(category: str) -> str:
    if category == "env_gate.integration_opt_in":
        return "required_in_ci"
    if category == "env_gate.performance_opt_in":
        return "nightly_and_release_candidate"
    if category == "env_gate.oom_opt_in":
        return "release_candidate_required"
    if category.startswith("infra."):
        return "allowed_only_when_prerequisite_unavailable"
    return "investigate_before_release"


def collect_skips(junit_paths: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for junit_path in junit_paths:
        root = ET.parse(junit_path).getroot()
        for case in root.findall(".//testcase"):
            skipped = case.find("skipped")
            if skipped is None:
                continue
            reason = _skip_reason(skipped)
            category = classify_reason(reason)
            entries.append(
                {
                    "junit_path": str(junit_path),
                    "classname": case.attrib.get("classname", ""),
                    "name": case.attrib.get("name", ""),
                    "reason": reason,
                    "category": category,
                    "gate_policy": gate_policy(category),
                }
            )
    return entries


def write_report(*, entries: list[dict[str, Any]], json_path: Path, markdown_path: Path) -> None:
    by_category = Counter(entry["category"] for entry in entries)
    payload = {
        "version": 1,
        "total_skipped": len(entries),
        "categories": dict(sorted(by_category.items())),
        "entries": entries,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Integration Skip Inventory",
        "",
        f"- total skipped: {len(entries)}",
    ]
    for category, count in sorted(by_category.items()):
        lines.append(f"- {category}: {count}")
    if entries:
        lines.extend(["", "| Category | Policy | Test | Reason |", "| --- | --- | --- | --- |"])
        for entry in entries:
            test_id = f"{entry['classname']}::{entry['name']}"
            reason = str(entry["reason"]).replace("|", "\\|")
            lines.append(
                f"| {entry['category']} | {entry['gate_policy']} | {test_id} | {reason} |"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(
            "usage: report_integration_skips.py <output.json> <output.md> <junit.xml> "
            "[<junit.xml> ...]",
            file=sys.stderr,
        )
        return 2

    json_path = Path(argv[1])
    markdown_path = Path(argv[2])
    junit_paths = [Path(path) for path in argv[3:]]
    entries = collect_skips(junit_paths)
    write_report(entries=entries, json_path=json_path, markdown_path=markdown_path)
    print(f"integration_skip_inventory=written skipped={len(entries)}")
    for category, count in sorted(Counter(entry["category"] for entry in entries).items()):
        print(f"integration_skip_category category={category} count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
