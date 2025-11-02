# Cash-Flow Guardian Telegram Bot

A purpose-built Telegram bot that enforces a 30-day virtual wallet routine tailored to the "Cash-Flow Guardian" blueprint. The bot tracks two virtual wallets - a **Sinking Fund** for non-negotiable first-of-month bills (rent, tiffin post-pay on the 1st, bi-monthly electricity) and a **Daily Wallet** for everyday spending. It also performs a 21:30 check-in that deducts default daily costs and nudges you to log extra expenses.

## Features

- 30-day cycle aligned with the 10th salary inflow and 5th home support.
- Automatic cycle detection — `/status` works without any manual setup.
- Automatic Sinking Fund goal calculation (rent, tiffin post-pay, bi-monthly electricity) including a survival cushion until the next income arrives.
- Daily Wallet allowance with rolling average guidance and wiggle-room hints.
- 21:30 reminder with automatic default deductions if you do not respond within an hour.
- 21:30 spend prompt with auto-filled defaults after 2 hours if you forget to reply.
- 17:00 reminder (Mon–Sat) to pick the day's tiffin sabji on WhatsApp.
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
   bot_token.txt
  defaults.yaml
data/
  state.json (created on first run)
requirements.txt
README.md
```

## Getting Started

1. **One-command install (recommended)**

   ```sh
   ./install.sh
   ```

   The script creates `.venv`, upgrades `pip`, and installs the requirements. Run it once per machine.

2. **Token configuration**

   Open `config/bot_token.txt`, paste your Telegram bot token, and save the file. Keep the token on one line with no extra spaces.

3. **Run the bot in seconds**

   ```sh
   ./start.sh
   ```

   `start.sh` activates the virtual environment, validates `config/bot_token.txt`, and launches `bot.py` via polling.

4. **Alternative manual setup**

   If you prefer the traditional steps:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python bot.py
   ```

   Ensure `config/bot_token.txt` contains your token before running.

## Core Commands

- `/start` - introduction and an immediate status snapshot.
- `/start_cycle <amount>` - optional manual cycle with a custom opening balance (useful if incomes differ from the defaults).
- `/set_balance <amount>` - optional override for an income that deviates from the plan.
- `/status` - shows how much cash to hold today (with a breakdown of rent, electricity, tiffin post-pay, and daily defaults including breakfast/lunch/library totals) to cover essentials through the first of next month, plus the total required through the upcoming 10th.
- `/log_extra <amount> [note]` - logs additional spending outside of the default day plan.
- `/log_spend [YYYY-MM-DD] <breakfast> <lunch> <dinner> <other>` - records the day's food/other spends; omit the optional date to log for today. Defaults (35/50/90 or 120 on Sundays) auto-fill if you do not respond within two hours of the 21:30 prompt.
- `/daily_confirm [extra] [note]` - responds to the 21:30 check-in. If you fail to reply within an hour, defaults are auto-applied with zero extras.
- `/set_defaults` - interactive update of breakfast/lunch/study defaults. Changes persist to the next cycle.

## Configuration

The default budget parameters live in `config/defaults.yaml`. If costs shift (e.g., breakfast price increases), either edit the file or use `/set_defaults` to override values. Electricity months default to the even-numbered months; adjust `electricity_due_months` if your billing cadence differs.

Key values:

- `fixed_bills` - rent, tiffin, and electricity amounts.
- `income_sources` - day-of-month and expected amounts for the 10th/5th inflows.
- `daily_defaults` - per-day spending templates for weekdays, Saturdays, and Sundays.
- `cycle` - length (30 days), timezone (Asia/Kolkata), check-in time (21:30), and default auto-close window (60 minutes).
- `sheets` - toggle and describe the Google Sheets bridge (spreadsheet name, optional worksheet, optional credentials path pointing to `config/service_account.json` by default).

### Google Sheets integration

Daily spend logs are synchronised to Google Sheets so the history survives redeploys. Because the service-account key should never be committed, place it locally and on the server manually:

1. Download the JSON key from Google Cloud and copy it to `config/service_account.json` (the path matches the default in `config/defaults.yaml`). Keep the file out of Git; it is ignored automatically.
2. Share the target spreadsheet with `expense-bot-service-account@gen-lang-client-0300775578.iam.gserviceaccount.com` as an Editor so it can append rows.
3. Ensure row 1 of the worksheet contains these headers exactly:
   `Date, Breakfast, Lunch, Dinner, Other, AutoFilled, RecordedAt`.

Once the file is in place and the sheet shared, `/log_spend` writes directly to the sheet and `/status` reads monthly totals from there. If the integration cannot connect (e.g., sheet renamed, credentials missing, or access revoked) the bot falls back to JSON persistence and prints a warning in the console.

## Notes

- The bot assumes a single-user private chat. User ID and chat ID are treated interchangeably; if you move to a group chat, adapt `handlers.py` accordingly.
- State is stored in plain JSON alongside the optional Google Sheet. Back up `data/state.json` if you switch hosts and keep the sheet shared with the bot account.
- The blueprint's "Monthly Buffer" is reported as the difference between the Daily Wallet allowance and the expected default spend for the cycle.

## Testing

At the moment the project does not ship automated tests. Consider adding unit tests for `finance.build_cycle_computation` and `cycle_manager` flows as the bot evolves.

## Deployment

For production use you may:

1. Containerize the bot or run it under a process manager such as `systemd`, `pm2`, or `supervisord`.
2. Configure logging rotation and persistence.
3. Secure the host (firewall, limited user permissions) and rotate the bot token if you regenerate it.

### VPS setup (one time)

```sh
git clone https://github.com/deveshvyas1/MyFinBot.git ~/bots/MyFinBot
cd ~/bots/MyFinBot
chmod +x install.sh start.sh
./install.sh
nano config/bot_token.txt  # paste your Telegram bot token on a single line
```

Start the bot manually with:

```sh
./start.sh
```

### Keep it running 24/7 (systemd)

```sh
sudo tee /etc/systemd/system/myfinbot.service <<'EOF'
[Unit]
Description=MyFinBot Telegram bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/youruser/bots/MyFinBot
ExecStart=/bin/bash /home/youruser/bots/MyFinBot/start.sh
Restart=always
RestartSec=5
User=youruser
Environment=PATH=/home/youruser/bots/MyFinBot/.venv/bin:/usr/bin

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now myfinbot.service
```

Check the service anytime:

```sh
systemctl status myfinbot.service   # press q to exit
journalctl -u myfinbot.service -f   # follow logs
```

### Deploy future updates

```sh
cd ~/bots/MyFinBot
git pull
sudo systemctl restart myfinbot.service
```

Enjoy keeping your cash flow on track!
