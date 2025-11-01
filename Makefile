.PHONY: install run clean

PYTHON?=python3
VENVDIR=.venv

install:
	@if [ ! -d "$(VENVDIR)" ]; then \
		$(PYTHON) -m venv $(VENVDIR); \
	fi
	$(VENVDIR)/bin/pip install --upgrade pip
	$(VENVDIR)/bin/pip install -r requirements.txt

run:
	@if [ ! -d "$(VENVDIR)" ]; then \
		echo "Virtual environment not found. Run 'make install' first."; \
		exit 1; \
	fi
	@if [ ! -f "config/bot_token.txt" ]; then \
		echo "config/bot_token.txt is missing; add your Telegram bot token."; \
		exit 1; \
	fi
	@if grep -q "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE" config/bot_token.txt; then \
		echo "Update config/bot_token.txt with your actual Telegram bot token."; \
		exit 1; \
	fi
	$(VENVDIR)/bin/python bot.py

clean:
	rm -rf $(VENVDIR)
