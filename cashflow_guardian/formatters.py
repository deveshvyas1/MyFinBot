"""Formatting utilities for bot responses."""
from __future__ import annotations

from datetime import date

from .models import CycleState


def _format_money(amount: int) -> str:
    return f"INR {amount:,}" if amount >= 0 else f"- INR {abs(amount):,}"


def _format_date(target: date) -> str:
    return target.strftime("%d-%b-%y").upper()


def format_cycle_intro(cycle: CycleState) -> str:
    sinking = cycle.sinking_breakdown
    lines = [
        "New cycle started",
        f"Window: {_format_date(cycle.start)} → {_format_date(cycle.end)}",
        f"Sinking fund target (due {_format_date(cycle.due_date)}): {_format_money(sinking.total)}",
        f"  • Rent: {_format_money(sinking.rent)}",
        f"  • Tiffin pre-pay: {_format_money(sinking.tiffin)}",
        f"  • Electricity: {_format_money(sinking.electricity)}",
        f"  • Survival cushion: {_format_money(sinking.survival)}",
        f"Daily wallet allowance: {_format_money(cycle.daily_wallet.goal)}",
        f"Expected default spend this cycle: {_format_money(cycle.daily_wallet.expected_default_spend)}",
        f"Planned buffer: {_format_money(cycle.daily_wallet.buffer_allocation)}",
    ]
    if cycle.survival_allocation.dates:
        lines.append("Survival breakdown:")
        for entry in cycle.survival_allocation.dates:
            try:
                entry_date = date.fromisoformat(entry.date)
                display_date = _format_date(entry_date)
            except ValueError:
                display_date = entry.date
            lines.append(
                f"  • {display_date}: {_format_money(entry.default_spend)}"
            )
    return "\n".join(lines)


def format_status(*, due_date: date, required_amount: int) -> str:
    return (
        f"Hold {_format_money(required_amount)} to cover essentials through "
        f"{_format_date(due_date)}."
    )
