"""不可配置的、启发式的危险命令黑名单。"""

import re

_BLACKLIST = [
    re.compile(r"\brm\s+(?:-[a-z]*[rf][a-z]*\s+)+(?:/|~|\$HOME)(?:\s|$)"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"),
    re.compile(r"\bdd\b.*\bof=/dev/"),
    re.compile(r"\bmkfs(?:\.[\w-]+)?\b"),
    re.compile(r">\s*/dev/(?:sd|nvme|disk)"),
    re.compile(r"\bchmod\s+-R\s+777\s+/(?:\s|$)"),
]


def hits_blacklist(command: str) -> bool:
    return any(pattern.search(command) for pattern in _BLACKLIST)
