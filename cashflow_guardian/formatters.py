"""Formatting utilities for bot responses."""
from __future__ import annotations

from datetime import date
from typing import Mapping

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


def _format_tiffin_details(component: Mapping[str, object]) -> str:
    amount = int(component.get("amount", 0))
    weekday_meals = int(component.get("weekday_meals", 0))
    saturday_meals = int(component.get("saturday_meals", 0))
    total_meals = weekday_meals + saturday_meals
    if total_meals == 0:
        return f"Tiffin pre-pay: {_format_money(amount)}"
    detail = f"Tiffin pre-pay ({total_meals} meals"
    if weekday_meals:
        detail += f", {weekday_meals} weekday"
    if saturday_meals:
        detail += f", {saturday_meals} Saturday"
    detail += f"): {_format_money(amount)}"
    return detail


def format_status(
    *,
    today: date,
    due_date: date,
    required_amount: int,
    components: Mapping[str, Mapping[str, object]],
) -> str:
    lines = [
        (
            f"{_format_date(today)}: Hold {_format_money(required_amount)} to cover "
            f"essentials through {_format_date(due_date)}."
        ),
        "Breakdown:",
    ]

    rent = components.get("rent", {})
    rent_amount = int(rent.get("amount", 0))
    rent_due = rent.get("due_date", due_date)  # type: ignore[arg-type]
    rent_due_date = rent_due if isinstance(rent_due, date) else due_date
    lines.append(
        f"- Rent due {_format_date(rent_due_date)}: {_format_money(rent_amount)}"
    )

    electricity = components.get("electricity", {})
    electricity_amount = int(electricity.get("amount", 0))
    if electricity_amount > 0:
        electricity_due = electricity.get("due_date", due_date)  # type: ignore[arg-type]
        electricity_due_date = (
            electricity_due if isinstance(electricity_due, date) else due_date
        )
        lines.append(
            "- Electricity due "
            f"{_format_date(electricity_due_date)}: "
            f"{_format_money(electricity_amount)}"
        )
    else:
        lines.append(
            f"- Electricity: {_format_money(0)} (no bill due this cycle)"
        )

    tiffin = components.get("tiffin", {})
    lines.append(f"- {_format_tiffin_details(tiffin)}")

    daily = components.get("daily", {})
    daily_amount = int(daily.get("amount", 0))
    start = daily.get("start", today)  # type: ignore[arg-type]
    start_date = start if isinstance(start, date) else today
    end = daily.get("end", due_date)  # type: ignore[arg-type]
    end_date = end if isinstance(end, date) else due_date
    days = int(daily.get("days", 0))
    range_text = f"{_format_date(start_date)} → {_format_date(end_date)}"
    if days > 0:
        range_text += f" ({days} days)"
    lines.append(
        f"- Food & daily defaults {range_text}: {_format_money(daily_amount)}"
    )

    return "\n".join(lines)
