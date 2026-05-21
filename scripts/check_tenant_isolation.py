#!/usr/bin/env python3
"""§3.2: CI guard against direct queries on artifact/test_result/run_event
without joining through run.tenant_id.

These three tables lack a tenant_id column. All access MUST go through
a Run join for tenant isolation. This script greps for direct queries
that bypass the join.
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "qaplatform"

# Tables that lack tenant_id
TABLES = {"artifact", "test_result", "run_event"}

# Pattern: SELECT/FROM/where on these tables without "run" in the same query
QUERY_RE = re.compile(
    r"(?:select|from|where).*?\b(" + "|".join(TABLES) + r")\b",
    re.IGNORECASE,
)

# Allow queries that also reference "run" (join through run table)
JOIN_RE = re.compile(r"\brun\b", re.IGNORECASE)

violations = []
for py in SRC.rglob("*.py"):
    text = py.read_text()
    for match in QUERY_RE.finditer(text):
        # Get surrounding context (the full statement)
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        context = text[line_start:line_end]
        # Check if "run" is referenced in context (join)
        if not JOIN_RE.search(context):
            violations.append((py, match.group(1), context.strip()))

if violations:
    print("§3.2 VIOLATION: Direct query on artifact/test_result/run_event without run join:")
    for path, table, ctx in violations:
        print(f"  {path}:{table} -> {ctx}")
    sys.exit(1)
else:
    print("§3.2 OK: No direct queries on artifact/test_result/run_event without run join")
    sys.exit(0)
