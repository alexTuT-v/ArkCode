"""工具实现共享的无状态辅助函数。"""


def truncate(value: str, max_lines: int, max_chars: int) -> str:
    """按行数和字符数截断，并显式标注结果不完整。"""

    lines = value.splitlines()
    truncated = len(lines) > max_lines or len(value) > max_chars
    value = "\n".join(lines[:max_lines])
    if len(value) > max_chars:
        value = value[:max_chars]
    if truncated:
        value = value.rstrip() + "\n[truncated]"
    return value
