"""Tests for the ArkCode command-line interface."""

import io
import unittest
from contextlib import redirect_stdout

from arkcode.cli import greeting, main


class CliTests(unittest.TestCase):
    def test_greeting(self) -> None:
        self.assertEqual(greeting(), "Hello from ArkCode!")

    def test_main(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "Hello from ArkCode!\n")


if __name__ == "__main__":
    unittest.main()
