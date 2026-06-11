"""失败分诊的纯函数：错误签名归一化（T12）。

签名 = ``error_message`` 首行，截断 200 字符，数字/UUID/路径归一为
占位符。同签名的失败在 triage 视图中折叠为一组。纯函数实现，无依赖。
"""

from __future__ import annotations

import re

SIGNATURE_MAX_LENGTH = 200

# 无 error_message 的失败（如 collector 未捕获到 message）共用一个签名组。
EMPTY_SIGNATURE = "<no-message>"

# UUID 先于数字归一，否则会被数字规则撕碎成 "<num>a<num>-..." 残片。
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# 路径：≥2 段的 / 分隔片段（绝对或相对），覆盖 pytest 报错中常见的
# "tests/unit/test_x.py:42" 与 "/tmp/pytest-1234/..." 两种形态。
_PATH_RE = re.compile(r"(?:/?[\w.\-]+(?:/[\w.\-]+)+/?)")
_NUMBER_RE = re.compile(r"\d+")


def failure_signature(error_message: str | None) -> str:
    """归一化错误消息为聚类签名。

    顺序固定：取首行 → UUID → 路径 → 数字 → 截断。顺序变更会把
    UUID/路径里的数字先替换掉，破坏占位符的稳定性。
    """
    if error_message is None:
        return EMPTY_SIGNATURE
    first_line = error_message.strip().splitlines()[0].strip() if error_message.strip() else ""
    if not first_line:
        return EMPTY_SIGNATURE
    normalized = _UUID_RE.sub("<uuid>", first_line)
    normalized = _PATH_RE.sub("<path>", normalized)
    normalized = _NUMBER_RE.sub("<num>", normalized)
    return normalized[:SIGNATURE_MAX_LENGTH]
