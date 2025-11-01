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
	@if [ -z "$(BOT_TOKEN)" ]; then \
		echo "BOT_TOKEN environment variable is required"; \
		exit 1; \
	fi
	BOT_TOKEN="$(BOT_TOKEN)" $(VENVDIR)/bin/python bot.py

clean:
	rm -rf $(VENVDIR)
