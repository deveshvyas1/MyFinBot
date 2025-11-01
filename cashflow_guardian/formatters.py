"""Formatting utilities for bot responses."""
from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, Tuple

from .models import CycleState


def _format_money(amount: int) -> str:
    return f"INR {amount:,}" if amount >= 0 else f"- INR {abs(amount):,}"


def _day_label(target: date) -> str:
    return target.strftime("%A")


def format_cycle_intro(cycle: CycleState) -> str:
    sinking = cycle.sinking_breakdown
    lines = [
        "New cycle started",
        f"Window: {cycle.start.isoformat()} → {cycle.end.isoformat()}",
        f"Sinking fund target (due {cycle.due_date.isoformat()}): {_format_money(sinking.total)}",
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
            lines.append(
                f"  • {entry['date']}: {_format_money(int(entry['default_spend']))}"
            )
    return "\n".join(lines)


def format_status(
    *,
    cycle: CycleState,
    days_left: int,
    today: date,
    today_default: Dict[str, object],
) -> str:
    daily_wallet = cycle.daily_wallet
    average = 0 if days_left == 0 else daily_wallet.balance / max(days_left, 1)
    lines = [
        f"Cycle: {cycle.start.isoformat()} → {cycle.end.isoformat()} ({days_left} days left)",
        f"Sinking fund target: {_format_money(cycle.sinking_breakdown.total)} (due {cycle.due_date.isoformat()})",
        f"Daily wallet: {_format_money(daily_wallet.balance)} remaining of {_format_money(daily_wallet.goal)}",
        f"Total spent this cycle: {_format_money(daily_wallet.spent)}",
        f"Average per remaining day: {_format_money(int(round(average)))}",
    ]
    default_total = int(today_default.get("total", 0))
    breakdown = today_default.get("breakdown", {})
    wiggle = int(round(today_default.get("wiggle", 0)))
    lines.append(
        f"Today ({_day_label(today)}): default spend {_format_money(default_total)}"
    )
    if isinstance(breakdown, dict):
        for name, value in breakdown.items():
            lines.append(f"  • {name}: {_format_money(value)}")
    lines.append(f"Wiggle room today: {_format_money(wiggle)}")
    lines.append(
        f"Planned buffer for cycle: {_format_money(cycle.daily_wallet.buffer_allocation)}"
    )
    return "\n".join(lines)
