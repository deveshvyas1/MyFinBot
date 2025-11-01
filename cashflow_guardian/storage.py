"""State persistence utilities."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .models import AppState


class StateStorage:
    """Simple JSON-backed storage for the bot state."""

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppState:
        if not self._state_path.exists():
            return AppState()
        with self._state_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return AppState.model_validate(raw)

    def save(self, state: AppState) -> None:
        payload = state.model_dump(mode="json")
        temp_path = self._state_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        temp_path.replace(self._state_path)

    def with_state(self, mutator: Callable[[AppState], AppState]) -> AppState:
        """Apply a mutation callback and persist the result."""
        current = self.load()
        updated = mutator(current)
        self.save(updated)
        return updated

    def update_in_place(self, mutator: Callable[[AppState], None]) -> AppState:
        """Mutate the loaded state object in place and persist."""
        current = self.load()
        mutator(current)
        self.save(current)
        return current
