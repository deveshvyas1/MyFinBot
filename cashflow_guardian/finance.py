"""Core finance calculations for the Cash-Flow Guardian bot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from zoneinfo import ZoneInfo

from .models import (
    AppConfig,
    DailyDefaultsConfig,
    IncomeEntry,
    IncomeSourceConfig,
    SinkingBreakdown,
    SurvivalAllocation,
    SurvivalDay,
)


@dataclass
class CycleComputation:
    start: date
    end: date
    due_date: date
    incomes: List[IncomeEntry]
    sinking_breakdown: SinkingBreakdown
    survival: SurvivalAllocation
    expected_default_spend: int
    default_totals_by_date: Dict[date, int]


@dataclass
class RequiredFunds:
    start: date
    end: date
    total: int
    rent: int
    tiffin: int
    tiffin_weekday_meals: int
    tiffin_saturday_meals: int
    electricity: int
    electricity_due: date
    daily_spend_total: int
    day_count: int


def _first_day_next_month(anchor: date) -> date:
    next_month = anchor.month + 1
    year = anchor.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    return date(year, month, 1)


def _resolve_income_date(anchor: date, day: int) -> date:
    if day >= anchor.day:
        return anchor.replace(day=day)
    # Move to next month
    next_month = anchor.month + 1
    year = anchor.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    # Handle shorter months safely
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            # Day exceeded month length; step back one day until valid
            day -= 1


def _safe_date(year: int, month: int, day: int) -> date:
    while day > 0:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    raise ValueError("Unable to resolve a valid date for the given month/year")


def _resolve_income_schedule(
    start: date, cycle_end: date, configs: Iterable[IncomeSourceConfig]
) -> List[IncomeEntry]:
    entries: List[IncomeEntry] = []
    for source in configs:
        income_date = _resolve_income_date(start, source.day)
        if income_date < start:
            continue
        if income_date > cycle_end:
            continue
        entries.append(
            IncomeEntry(
                date=income_date,
                description=source.description,
                planned_amount=source.amount,
            )
        )
    # Ensure chronological order
    entries.sort(key=lambda entry: entry.date)
    return entries


def _tiffin_allocation(config: AppConfig) -> int:
    total_days = (
        config.fixed_bills.tiffin_weekday_count
        + config.fixed_bills.tiffin_saturday_count
    )
    return config.fixed_bills.tiffin_daily_cost * total_days


def _electricity_allocation(due_date: date, config: AppConfig) -> int:
    if due_date.month in config.fixed_bills.electricity_due_months:
        return config.fixed_bills.electricity_amount
    return 0


def _default_cost_for_date(target: date, defaults: DailyDefaultsConfig) -> Tuple[int, Dict[str, int]]:
    weekday = target.weekday()  # Monday=0 ... Sunday=6
    if weekday <= 4:
        mapping = defaults.weekday
    elif weekday == 5:
        mapping = defaults.saturday
    else:
        mapping = defaults.sunday
    total = sum(mapping.values())
    return total, dict(mapping)


def daily_default_details(target: date, config: AppConfig) -> Tuple[int, Dict[str, int]]:
    """Public helper to expose default spend details for a given date."""
    return _default_cost_for_date(target, config.daily_defaults)


def _expected_default_totals(
    start: date, days: int, defaults: DailyDefaultsConfig
) -> Tuple[int, Dict[date, int]]:
    totals: Dict[date, int] = {}
    running_total = 0
    for offset in range(days):
        current = start + timedelta(days=offset)
        total, _ = _default_cost_for_date(current, defaults)
        totals[current] = total
        running_total += total
    return running_total, totals


def _survival_allocation(
    due_date: date, incomes: List[IncomeEntry], defaults: DailyDefaultsConfig
) -> SurvivalAllocation:
    next_income = next((income for income in incomes if income.date > due_date), None)
    if not next_income:
        return SurvivalAllocation(total=0, dates=[])
    total = 0
    details: List[SurvivalDay] = []
    current = due_date
    while current < next_income.date:
        default_total, breakdown = _default_cost_for_date(current, defaults)
        total += default_total
        details.append(
            SurvivalDay(
                date=current.isoformat(),
                default_spend=default_total,
                breakdown=", ".join(
                    f"{key}: ₹{value}" for key, value in breakdown.items()
                ),
            )
        )
        current += timedelta(days=1)
    return SurvivalAllocation(total=total, dates=details)


def build_cycle_computation(start: date, config: AppConfig) -> CycleComputation:
    cycle_length = config.cycle.length_days
    cycle_end = start + timedelta(days=cycle_length - 1)
    due_date = _first_day_next_month(start)
    incomes = _resolve_income_schedule(start, cycle_end, config.income_sources)

    rent = config.fixed_bills.rent
    tiffin = _tiffin_allocation(config)
    electricity = _electricity_allocation(due_date, config)

    survival = _survival_allocation(due_date, incomes, config.daily_defaults)

    sinking_breakdown = SinkingBreakdown(
        rent=rent,
        tiffin=tiffin,
        electricity=electricity,
        survival=survival.total,
    )

    expected_default_spend, totals_by_date = _expected_default_totals(
        start, cycle_length, config.daily_defaults
    )

    return CycleComputation(
        start=start,
        end=cycle_end,
        due_date=due_date,
        incomes=incomes,
        sinking_breakdown=sinking_breakdown,
        survival=survival,
        expected_default_spend=expected_default_spend,
        default_totals_by_date=totals_by_date,
    )


def _daily_spend_between(
    start: date, end: date, defaults: DailyDefaultsConfig
) -> Tuple[int, Dict[date, int]]:
    if end < start:
        return 0, {}
    days = (end - start).days + 1
    total, totals_by_date = _expected_default_totals(start, days, defaults)
    return total, totals_by_date


def compute_required_windows(
    today: date, config: AppConfig
) -> Tuple[RequiredFunds, RequiredFunds]:
    due_date = _first_day_next_month(today)
    tenth_date = _safe_date(due_date.year, due_date.month, 10)

    rent = config.fixed_bills.rent
    tiffin = _tiffin_allocation(config)
    weekday_meals = config.fixed_bills.tiffin_weekday_count
    saturday_meals = config.fixed_bills.tiffin_saturday_count
    electricity = _electricity_allocation(due_date, config)

    primary_daily_total, _ = _daily_spend_between(
        today, due_date, config.daily_defaults
    )
    primary_days = (due_date - today).days + 1

    tenth_daily_total, _ = _daily_spend_between(
        today, tenth_date, config.daily_defaults
    )
    tenth_days = (tenth_date - today).days + 1

    primary = RequiredFunds(
        start=today,
        end=due_date,
        total=rent + tiffin + electricity + primary_daily_total,
        rent=rent,
        tiffin=tiffin,
        tiffin_weekday_meals=weekday_meals,
        tiffin_saturday_meals=saturday_meals,
        electricity=electricity,
        electricity_due=due_date,
        daily_spend_total=primary_daily_total,
        day_count=primary_days,
    )

    tenth = RequiredFunds(
        start=today,
        end=tenth_date,
        total=rent + tiffin + electricity + tenth_daily_total,
        rent=rent,
        tiffin=tiffin,
        tiffin_weekday_meals=weekday_meals,
        tiffin_saturday_meals=saturday_meals,
        electricity=electricity,
        electricity_due=due_date,
        daily_spend_total=tenth_daily_total,
        day_count=tenth_days,
    )

    return primary, tenth


def parse_checkin_time(config: AppConfig) -> time:
    hour, minute = map(int, config.cycle.checkin_time.split(":"))
    return time(hour=hour, minute=minute, tzinfo=ZoneInfo(config.cycle.timezone))


def resolve_cycle_start(today: date, config: AppConfig) -> date:
    anchor_day = max(source.day for source in config.income_sources)
    if today.day >= anchor_day:
        return _safe_date(today.year, today.month, anchor_day)
    prev_month = today.month - 1 or 12
    prev_year = today.year - 1 if today.month == 1 else today.year
    return _safe_date(prev_year, prev_month, anchor_day)
