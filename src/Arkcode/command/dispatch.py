"""Slash Command 输入识别。"""


def parse(input_text: str) -> tuple[str, bool]:
    value = input_text.strip()
    if not value.startswith("/"):
        return "", False
    body = value[1:]
    if not body:
        return "", True
    if body[0].isspace():
        return "", True
    parts = body.split(maxsplit=1)
    if len(parts) != 1:
        return "", True
    return parts[0].lower(), True
