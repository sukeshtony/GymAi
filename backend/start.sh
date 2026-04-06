#!/bin/bash
# ── FitnessAI Backend Startup ──────────────────────────────
set -e

cd "$(dirname "$0")"

# Load env
if [ ! -f .env ]; then
  echo "⚠  No .env found. Copying from .env.example ..."
  cp .env.example .env
  echo "📝 Please edit backend/.env and set your ANTHROPIC_API_KEY, then re-run."
  exit 1
fi

# Create virtualenv if needed
if [ ! -d venv ]; then
  echo "🐍 Creating virtualenv..."
  python -m venv venv
fi

# Activate and install
source venv/Scripts/activate 2>/dev/null || source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  🏋️  FitnessAI Multi-Agent Fitness Backend        ║"
echo "║  http://localhost:8000                        ║"
echo "║  Docs: http://localhost:8000/docs             ║"
echo "║  Frontend: open frontend/index.html           ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

python main.py
