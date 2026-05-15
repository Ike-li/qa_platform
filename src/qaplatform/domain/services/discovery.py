from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qaplatform.domain.models.project import TestSelector


class DiscoveryService:
    """Domain service for discovering test files."""

    def discover_tests(
        self,
        selector: TestSelector,
        project_dir: Path | str,
    ) -> list[str]:
        """Discover test files matching the selector rules.

        Applies include_paths (glob), exclude_paths, and regex filter.
        Returns a list of relative paths from project_dir.
        """
        base = Path(project_dir)
        if not base.is_dir():
            return []

        collected: list[str] = []

        for root, dirs, files in os.walk(base):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for filename in files:
                rel_path = os.path.relpath(os.path.join(root, filename), base)

                # Apply include globs
                if selector.include_paths:
                    if not any(
                        fnmatch.fnmatch(rel_path, pattern)
                        for pattern in selector.include_paths
                    ):
                        continue

                # Apply exclude globs
                if selector.exclude_paths:
                    if any(
                        fnmatch.fnmatch(rel_path, pattern)
                        for pattern in selector.exclude_paths
                    ):
                        continue

                # Apply regex filter
                if selector.regex:
                    import re

                    if not re.search(selector.regex, filename):
                        continue

                collected.append(rel_path)

        collected.sort()
        return collected
