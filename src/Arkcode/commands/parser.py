"""Slash Command 输入识别。"""


def parse(input_text: str) -> tuple[str, str, bool]:
    value = input_text.strip()
    if not value.startswith("/"):
        return "", "", False
    body = value[1:]
    if not body:
        return "", "", True
    if body[0].isspace():
        return "", body.strip(), True
    parts = body.split(maxsplit=1)
    args = parts[1].strip() if len(parts) == 2 else ""
    return parts[0].lower(), args, True
