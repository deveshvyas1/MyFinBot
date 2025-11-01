"""Entry point for the Cash-Flow Guardian Telegram bot."""
from __future__ import annotations

import logging
from pathlib import Path

from telegram.ext import ApplicationBuilder

from cashflow_guardian.config_loader import load_config
from cashflow_guardian.cycle_manager import CycleManager
from cashflow_guardian.handlers import BotHandlers, register_handlers
from cashflow_guardian.storage import StateStorage


BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "defaults.yaml"
STATE_PATH = BASE_DIR / "data" / "state.json"
TOKEN_PATH = BASE_DIR / "config" / "bot_token.txt"


async def _post_init(application, handlers: BotHandlers) -> None:
    handlers.reschedule_jobs(application)


def _load_token() -> str:
    try:
        raw = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "config/bot_token.txt is missing. Create it with your Telegram bot token."
        ) from exc
    if not raw or raw == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Update config/bot_token.txt with your actual Telegram bot token before running."
        )
    return raw


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    token = _load_token()

    config = load_config(CONFIG_PATH)
    storage = StateStorage(STATE_PATH)
    cycle_manager = CycleManager(config, storage)
    handlers = BotHandlers(cycle_manager)

    application = (
        ApplicationBuilder()
        .token(token)
        .post_init(lambda app: _post_init(app, handlers))
        .build()
    )

    register_handlers(application, handlers)

    logging.info("Starting Cash-Flow Guardian bot")
    application.run_polling()


if __name__ == "__main__":
    main()
