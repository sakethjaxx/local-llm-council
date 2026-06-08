#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}   LLM Council — Installer${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── 1. Python 3.11+ ──────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ Python 3 not found.${NC}"
    echo "  Install from https://python.org then re-run this script."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo -e "${RED}✗ Python 3.11+ required. Found: $PY_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $PY_VERSION${NC}"

# ── 2. Ollama ────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo -e "${YELLOW}⚠ Ollama not found. Installing...${NC}"
    curl -fsSL https://ollama.ai/install.sh | sh
    echo -e "${GREEN}✓ Ollama installed${NC}"
else
    echo -e "${GREEN}✓ Ollama found${NC}"
fi

# ── 3. LLM Council ──────────────────────────────
echo ""
echo "Installing LLM Council..."
pip install --quiet --upgrade local-llm-council

echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}   ✓ Done!${NC}"
echo ""
echo -e "   Start:  ${BOLD}local-llm-council start${NC}"
echo -e "   Open:   ${BOLD}http://localhost:8765${NC}"
echo -e "   Note:   First run will offer to pull required models."
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
