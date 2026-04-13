#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN not found. Install Python 3 first." >&2
  exit 1
fi

echo "Using Python: $PYTHON_BIN"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "Virtual environment already exists at $VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo "Upgrading pip tooling"
python -m pip install --upgrade pip setuptools wheel

echo "Installing Python dependencies"
pip install -r requirements.txt

echo
echo "Setup complete."
echo "Activate with: source $VENV_DIR/bin/activate"
echo "If Selenium tests fail, install Chromium/Chrome and a matching WebDriver."
