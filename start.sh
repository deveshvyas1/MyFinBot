#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Virtual environment not found. Run ./install.sh first." >&2
  exit 1
fi

export BOT_TOKEN="${BOT_TOKEN:-$(grep ^BOT_TOKEN= .env | cut -d'=' -f2-)}"
if [ -z "$BOT_TOKEN" ]; then
  echo "BOT_TOKEN not set. Please add it to .env or export it." >&2
  exit 1
fi

. .venv/bin/activate
python bot.py
