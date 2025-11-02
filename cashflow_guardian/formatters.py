"""Formatting utilities for bot responses."""
from __future__ import annotations

from datetime import date
from typing import Mapping, Optional

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
        f"  • Tiffin post-pay: {_format_money(sinking.tiffin)}",
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
    due = component.get("due_date")  # type: ignore[arg-type]
    due_date = due if isinstance(due, date) else None
    total_meals = weekday_meals + saturday_meals
    due_text = _format_date(due_date) if due_date else "1st"
    if total_meals == 0:
        return (
            f"Tiffin post-pay (due {due_text}): {_format_money(amount)}"
        )
    detail = f"Tiffin post-pay (due {due_text}, {total_meals} meals"
    if weekday_meals:
        detail += f", {weekday_meals} weekday"
    if saturday_meals:
        detail += f", {saturday_meals} Saturday"
    detail += f"): {_format_money(amount)}"
    return detail


def format_status(
    *,
    today: date,
    primary: Mapping[str, object],
    components: Mapping[str, Mapping[str, object]],
    tenth: Mapping[str, object],
    spending: Optional[Mapping[str, object]] = None,
) -> str:
    due_date = primary.get("end", today)  # type: ignore[arg-type]
    due_date = due_date if isinstance(due_date, date) else today
    required_amount = int(primary.get("total", 0))

    tenth_end = tenth.get("end", due_date)  # type: ignore[arg-type]
    tenth_end = tenth_end if isinstance(tenth_end, date) else due_date
    tenth_total = int(tenth.get("total", 0))

    lines = [f"{_format_date(today)} STATUS", "", "Cash to hold:"]
    lines.append(
        f"- Through {_format_date(due_date)}: {_format_money(required_amount)}"
    )
    lines.append(
        f"- Through {_format_date(tenth_end)}: {_format_money(tenth_total)}"
    )

    lines.append("")
    lines.append(f"Bills due by {_format_date(due_date)}:")

    rent = components.get("rent", {})
    rent_amount = int(rent.get("amount", 0))
    rent_due = rent.get("due_date", due_date)  # type: ignore[arg-type]
    rent_due_date = rent_due if isinstance(rent_due, date) else due_date
    lines.append(
        f"- Rent (due {_format_date(rent_due_date)}): {_format_money(rent_amount)}"
    )

    electricity = components.get("electricity", {})
    electricity_amount = int(electricity.get("amount", 0))
    electric_due = electricity.get("due_date", due_date)  # type: ignore[arg-type]
    electric_due_date = (
        electric_due if isinstance(electric_due, date) else due_date
    )
    if electricity_amount > 0:
        lines.append(
            "- Electricity "
            f"(due {_format_date(electric_due_date)}): {_format_money(electricity_amount)}"
        )
    else:
        lines.append(f"- Electricity: {_format_money(0)} (not expected this month)")

    tiffin = components.get("tiffin", {})
    lines.append(f"- {_format_tiffin_details(tiffin)}")

    lines.append("")
    lines.append("Daily spends:")

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
        f"- Total {_format_money(daily_amount)} for {range_text}"
    )

    breakdown = daily.get("breakdown", {})
    if isinstance(breakdown, Mapping):
        highlight_order = ["Breakfast", "Lunch", "Library"]
        seen = set()
        for label in highlight_order:
            info = breakdown.get(label)
            amount = int(info.get("total", 0)) if isinstance(info, Mapping) else 0
            lines.append(f"    • {label}: {_format_money(amount)}")
            seen.add(label)
        for label, info in breakdown.items():
            if label in seen:
                continue
            if not isinstance(info, Mapping):
                continue
            amount = int(info.get("total", 0))
            lines.append(f"    • {label}: {_format_money(amount)}")

    lines.append("")
    lines.append(f"Upcoming 10th ({_format_date(tenth_end)}):")
    lines.append(
        f"- Total needed: {_format_money(tenth_total)}"
    )
    tenth_days = int(tenth.get("days", 0))
    tenth_daily_amount = int(tenth.get("daily_amount", 0))
    tenth_range = f"{_format_date(today)} → {_format_date(tenth_end)}"
    if tenth_days > 0:
        tenth_range += f" ({tenth_days} days)"
    lines.append(
        f"- Daily spends {tenth_range}: {_format_money(tenth_daily_amount)}"
    )

    if spending and spending.get("has_data"):
        lines.append("")
        lines.append("Monthly spend tracker:")
        history = spending.get("history", [])
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, Mapping):
                    continue
                label = entry.get("label")
                if not isinstance(label, str):
                    continue
                total = int(entry.get("total", 0))
                lines.append(f"- {label}: {_format_money(total)}")
        current_label = spending.get("current_label")
        if isinstance(current_label, str):
            current_total = int(spending.get("current_total", 0))
            lines.append(f"- {current_label}: {_format_money(current_total)}")

    return "\n".join(lines)
