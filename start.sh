#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Virtual environment not found. Run ./install.sh first." >&2
  exit 1
fi

if [ ! -f "config/bot_token.txt" ]; then
  echo "config/bot_token.txt is missing. Add your Telegram bot token to it." >&2
  exit 1
fi

if grep -q "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE" config/bot_token.txt; then
  echo "Update config/bot_token.txt with your actual Telegram bot token." >&2
  exit 1
fi

. .venv/bin/activate
python bot.py
