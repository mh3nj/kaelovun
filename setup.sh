#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────
# Kaelovun — Setup and Launch
# ─────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "   Kaelovun — Setup and Launch"
echo "========================================"
echo ""

# ── Check Python ──────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    if ! command -v python &>/dev/null; then
        echo -e "${RED}[ERROR] Python is not installed.${NC}"
        echo "Install Python 3.11+ from https://python.org"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

PYVER=$($PYTHON --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PYVER" | cut -d. -f1)
MINOR=$(echo "$PYVER" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    echo -e "${RED}[ERROR] Python 3.11+ is required. Detected: $PYVER${NC}"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} Python $PYVER"

# ── Virtual environment ───────────────────────────────
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}[SETUP]${NC} Creating virtual environment..."
    $PYTHON -m venv .venv
    echo -e "${GREEN}[OK]${NC} Virtual environment created."
else
    echo -e "${GREEN}[OK]${NC} Virtual environment found."
fi

echo -e "${YELLOW}[SETUP]${NC} Activating virtual environment..."
# shellcheck disable=SC1091
source .venv/bin/activate

# ── Dependencies ──────────────────────────────────────
if [ ! -f requirements.txt ]; then
    echo -e "${RED}[ERROR] requirements.txt not found.${NC}"
    exit 1
fi

echo -e "${YELLOW}[SETUP]${NC} Installing dependencies..."
$PYTHON -m pip install --upgrade pip >/dev/null 2>&1
pip install -r requirements.txt
echo -e "${GREEN}[OK]${NC} All dependencies installed."

# ── Launch ────────────────────────────────────────────
echo ""
echo "========================================"
echo "   Starting Kaelovun"
echo "========================================"
echo ""
$PYTHON main.py

echo ""
echo "Kaelovun has exited."
echo "Run this script again to launch the app."
