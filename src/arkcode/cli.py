"""Command-line interface for ArkCode."""


def greeting() -> str:
    """Return the default ArkCode greeting."""
    return "Hello from ArkCode!"


def main() -> int:
    """Run the ArkCode command-line interface."""
    print(greeting())
    return 0
