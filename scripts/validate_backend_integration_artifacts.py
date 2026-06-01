#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ALLOWED_NIGHTLY_OOM_SKIP_NAMES = {
    "test_oom_kill_sets_oom_killed_true",
    "test_normal_exit_oom_killed_false",
    "test_executor_maps_real_oom_to_timeout_summary_and_redis",
}


def _collect_nodeids(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    nodeids = {
        line.strip()
        for line in text.splitlines()
        if line.startswith("tests/") and "::" in line
    }
    total_match = re.search(r"(\d+)(?:/\d+)? tests? collected", text)
    if total_match is not None and int(total_match.group(1)) != len(nodeids):
        raise ValueError(
            f"collect_report_mismatch={path} reported={total_match.group(1)} "
            f"nodeids={len(nodeids)}"
        )
    if not nodeids:
        raise ValueError(f"collect_no_nodeids={path}")
    return nodeids


def _junit_outcome_errors(
    path: Path,
    root: ET.Element,
    *,
    strict_skips: bool,
    allow_nightly_oom_skips: bool,
) -> list[str]:
    testcases = root.findall(".//testcase")
    failures = root.findall(".//failure")
    junit_errors = root.findall(".//error")
    skipped_cases = [case for case in testcases if case.find("skipped") is not None]

    errors: list[str] = []
    if not testcases:
        errors.append(f"junit_no_testcases={path}")
    if len(testcases) == len(skipped_cases):
        errors.append(f"junit_all_skipped={path}")
    if failures:
        errors.append(f"junit_failures={path} count={len(failures)}")
    if junit_errors:
        errors.append(f"junit_errors={path} count={len(junit_errors)}")
    for case in skipped_cases:
        name = case.attrib.get("name")
        classname = case.attrib.get("classname")
        allowed_nightly_oom_skip = (
            allow_nightly_oom_skips
            and path.name == "heavy-docker-integration.xml"
            and classname == "tests.integration.test_oom_e2e"
            and name in _ALLOWED_NIGHTLY_OOM_SKIP_NAMES
        )
        if strict_skips or not allowed_nightly_oom_skip:
            errors.append(
                f"junit_skipped={path} classname={classname} name={name}"
            )
    return errors


def _junit_nodeids(path: Path, root: ET.Element) -> set[str]:
    nodeids: list[str] = []
    missing: list[str] = []
    multiple: list[str] = []
    for case in root.findall(".//testcase"):
        case_nodeids = [
            prop.attrib.get("value")
            for prop in case.findall("./properties/property")
            if prop.attrib.get("name") == "nodeid"
        ]
        case_nodeids = [value for value in case_nodeids if value]
        if not case_nodeids:
            classname = case.attrib.get("classname", "<missing-classname>")
            name = case.attrib.get("name", "<missing-name>")
            missing.append(f"{classname}::{name}")
            continue
        if len(case_nodeids) > 1:
            classname = case.attrib.get("classname", "<missing-classname>")
            name = case.attrib.get("name", "<missing-name>")
            multiple.append(f"{classname}::{name}")
        nodeids.extend(case_nodeids)
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(
            f"junit_missing_nodeid_properties={path} count={len(missing)} preview={preview}"
        )
    if multiple:
        preview = ", ".join(multiple[:5])
        raise ValueError(
            f"junit_multiple_nodeid_properties={path} "
            f"count={len(multiple)} preview={preview}"
        )
    if not nodeids:
        raise ValueError(f"junit_no_nodeids={path}")

    duplicates = sorted(
        {nodeid for index, nodeid in enumerate(nodeids) if nodeid in nodeids[:index]}
    )
    if duplicates:
        raise ValueError(
            f"junit_duplicate_nodeids={path} "
            f"count={len(duplicates)} preview={duplicates[:5]!r}"
        )

    testcases = root.findall(".//testcase")
    if len(nodeids) != len(testcases):
        raise ValueError(
            f"junit_nodeid_count_mismatch={path} "
            f"testcases={len(testcases)} nodeids={len(nodeids)}"
        )
    return set(nodeids)


def _junit_path_for_collect(collect_path: Path) -> Path:
    name = collect_path.name
    if not name.endswith("-collect.txt"):
        raise ValueError(f"unexpected_collect_filename={collect_path}")
    return collect_path.with_name(name.removesuffix("-collect.txt") + ".xml")


def validate_pairs(
    collect_paths: list[Path],
    *,
    strict_skips: bool = False,
    allow_nightly_oom_skips: bool = False,
) -> list[str]:
    errors: list[str] = []
    for collect_path in collect_paths:
        junit_path = _junit_path_for_collect(collect_path)
        try:
            collected = _collect_nodeids(collect_path)
            root = ET.parse(junit_path).getroot()
            executed = _junit_nodeids(junit_path, root)
        except (OSError, ET.ParseError, ValueError) as exc:
            errors.append(str(exc))
            continue

        errors.extend(
            _junit_outcome_errors(
                junit_path,
                root,
                strict_skips=strict_skips,
                allow_nightly_oom_skips=allow_nightly_oom_skips,
            )
        )

        missing = sorted(collected - executed)
        unexpected = sorted(executed - collected)
        if missing:
            errors.append(
                f"junit_missing_collected_nodeids={junit_path} "
                f"count={len(missing)} preview={missing[:5]!r}"
            )
        if unexpected:
            errors.append(
                f"junit_unexpected_nodeids={junit_path} "
                f"count={len(unexpected)} preview={unexpected[:5]!r}"
            )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: validate_backend_integration_artifacts.py "
            "<manifest.txt> <collect.txt> [<collect.txt> ...]",
            file=sys.stderr,
        )
        return 2

    manifest_path = Path(argv[1])
    collect_paths = [Path(path) for path in argv[2:]]
    errors = validate_pairs(
        collect_paths,
        strict_skips=os.environ.get("STRICT_JUNIT_SKIPS") == "1",
        allow_nightly_oom_skips=os.environ.get("ALLOW_NIGHTLY_OOM_SKIPS") == "1",
    )
    with manifest_path.open("a", encoding="utf-8") as manifest:
        if errors:
            for error in errors:
                print(error)
                manifest.write(f"{error}\n")
            return 1
        for collect_path in collect_paths:
            junit_path = _junit_path_for_collect(collect_path)
            manifest.write(
                f"nodeid_counts collect={collect_path} junit={junit_path} "
                f"nodeids={len(_collect_nodeids(collect_path))}\n"
            )
        print(f"nodeid_validation=passed files={len(collect_paths)}")
        manifest.write(f"nodeid_validation=passed files={len(collect_paths)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
