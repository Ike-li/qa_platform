#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


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


def _junit_nodeids(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    nodeids: set[str] = set()
    missing: list[str] = []
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
        nodeids.update(case_nodeids)
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(
            f"junit_missing_nodeid_properties={path} count={len(missing)} preview={preview}"
        )
    if not nodeids:
        raise ValueError(f"junit_no_nodeids={path}")
    return nodeids


def _junit_path_for_collect(collect_path: Path) -> Path:
    name = collect_path.name
    if not name.endswith("-collect.txt"):
        raise ValueError(f"unexpected_collect_filename={collect_path}")
    return collect_path.with_name(name.removesuffix("-collect.txt") + ".xml")


def validate_pairs(collect_paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for collect_path in collect_paths:
        junit_path = _junit_path_for_collect(collect_path)
        try:
            collected = _collect_nodeids(collect_path)
            executed = _junit_nodeids(junit_path)
        except (OSError, ET.ParseError, ValueError) as exc:
            errors.append(str(exc))
            continue

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
    errors = validate_pairs(collect_paths)
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
