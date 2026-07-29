# ArkCode

ArkCode is a Python project with a `src` layout, a small command-line entry point,
and a test suite.

## Requirements

- Python 3.10 or newer

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Usage

```bash
arkcode
```

You can also run the package directly:

```bash
python -m arkcode
```

## Development

```bash
pytest
ruff check .
ruff format --check .
```
