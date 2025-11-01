# Cash-Flow Guardian Telegram Bot

A purpose-built Telegram bot that enforces a 30-day virtual wallet routine tailored to the "Cash-Flow Guardian" blueprint. The bot tracks two virtual wallets - a **Sinking Fund** for non-negotiable first-of-month bills (rent, tiffin prepayment, bi-monthly electricity) and a **Daily Wallet** for everyday spending. It also performs a 21:30 check-in that deducts default daily costs and nudges you to log extra expenses.

## Features

- 30-day cycle aligned with the 10th salary inflow and 5th home support.
- Automatic Sinking Fund goal calculation (rent, tiffin, and electricity months), including a survival cushion until the next income arrives.
- Daily Wallet allowance with rolling average guidance and wiggle-room hints.
- 21:30 reminder with automatic default deductions if you do not respond within an hour.
- Commands to log extra spends, record incomes, and tweak default meal/transport prices.
- JSON-backed state so the bot survives restarts.

## Project Structure

```
bot.py
cashflow_guardian/
  __init__.py
  config_loader.py
  cycle_manager.py
  finance.py
  formatters.py
  handlers.py
  models.py
  storage.py
config/
  defaults.yaml
data/
  state.json (created on first run)
requirements.txt
.env.example
README.md
```

## Getting Started

1. **Create a virtual environment and install dependencies**

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure the bot token**

   Copy `.env.example` to `.env` (or export the variable in your shell) and insert your Telegram Bot token.

   ```sh
   cp .env.example .env
   echo 'BOT_TOKEN=your-telegram-bot-token' >> .env
   ```

   When running the bot, ensure `BOT_TOKEN` is exported into the environment. Avoid committing your real token.

3. **Bootstrap data directory (first run only)** - the code creates `data/state.json` automatically, but you can pre-create it if you prefer:

   ```sh
   mkdir -p data
   echo '{}' > data/state.json
   ```

4. **Run the bot**

   ```sh
   python bot.py
   ```

   The bot uses polling by default. Deploy it on a long-running host or process manager to keep it alive.

## Core Commands

- `/start` - introduction and current status (if a cycle exists).
- `/start_cycle <amount>` - begins a new 30-day cycle using the provided amount as the opening balance (usually the 10th salary).
- `/set_balance <amount>` - records an income during an active cycle (5th home inflow or any top-up).
- `/status` - shows Sinking Fund goals, Daily Wallet balance, daily averages, and wiggle room.
- `/log_extra <amount> [note]` - logs additional spending outside of the default day plan.
- `/daily_confirm [extra] [note]` - responds to the 21:30 check-in. If you fail to reply within an hour, defaults are auto-applied with zero extras.
- `/set_defaults` - interactive update of breakfast/lunch/study defaults. Changes persist to the next cycle.

## Configuration

The default budget parameters live in `config/defaults.yaml`. If costs shift (e.g., breakfast price increases), either edit the file or use `/set_defaults` to override values. Electricity months default to the even-numbered months; adjust `electricity_due_months` if your billing cadence differs.

Key values:

- `fixed_bills` - rent, tiffin, and electricity amounts.
- `income_sources` - day-of-month and expected amounts for the 10th/5th inflows.
- `daily_defaults` - per-day spending templates for weekdays, Saturdays, and Sundays.
- `cycle` - length (30 days), timezone (Asia/Kolkata), check-in time (21:30), and default auto-close window (60 minutes).

## Notes

- The bot assumes a single-user private chat. User ID and chat ID are treated interchangeably; if you move to a group chat, adapt `handlers.py` accordingly.
- State is stored in plain JSON. Back it up if you switch hosts to preserve your running totals.
- The blueprint's "Monthly Buffer" is reported as the difference between the Daily Wallet allowance and the expected default spend for the cycle.

## Testing

At the moment the project does not ship automated tests. Consider adding unit tests for `finance.build_cycle_computation` and `cycle_manager` flows as the bot evolves.

## Deployment

For production use you may:

1. Containerize the bot or run it under a process manager such as `systemd`, `pm2`, or `supervisord`.
2. Configure logging rotation and persistence.
3. Secure the host (firewall, limited user permissions) and keep the bot token secret.

Enjoy keeping your cash flow on track!
