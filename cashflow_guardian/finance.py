"""Core finance calculations for the Cash-Flow Guardian bot."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Dict, Iterable, List, Tuple

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
    daily_breakdown: Dict[str, Dict[str, int]]


_ITEM_LABEL_OVERRIDES = {"study": "Library"}


def resolve_cycle_start(today: date, config: AppConfig) -> date:
    anchor_day = max((source.day for source in config.income_sources), default=1)
    year = today.year
    month = today.month
    candidate = _safe_date(year, month, anchor_day)
    if candidate > today:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        candidate = _safe_date(year, month, anchor_day)

    cycle_length = max(config.cycle.length_days, 1)
    while (today - candidate).days >= cycle_length:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        candidate = _safe_date(year, month, anchor_day)

    return candidate


def parse_checkin_time(config: AppConfig) -> time:
    raw = config.cycle.checkin_time.strip()
    try:
        parsed = time.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"Invalid checkin_time configured: '{raw}'. Expected HH:MM format."
        ) from exc
    return parsed.replace(tzinfo=ZoneInfo(config.cycle.timezone))


def _first_day_next_month(anchor: date) -> date:
    next_month = anchor.month + 1
    year = anchor.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    return date(year, month, 1)


def _resolve_income_date(anchor: date, day: int) -> date:
    if day >= anchor.day:
        return anchor.replace(day=day)
    next_month = anchor.month + 1
    year = anchor.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    while True:
        try:
            return date(year, month, day)
        except ValueError:
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
        if income_date < start or income_date > cycle_end:
            continue
        entries.append(
            IncomeEntry(
                date=income_date,
                description=source.description,
                planned_amount=source.amount,
            )
        )
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


def _default_cost_for_date(
    target: date, defaults: DailyDefaultsConfig
) -> Tuple[int, Dict[str, int]]:
    weekday = target.weekday()
    if weekday <= 4:
        mapping = defaults.weekday
    elif weekday == 5:
        mapping = defaults.saturday
    else:
        mapping = defaults.sunday
    total = sum(mapping.values())
    return total, dict(mapping)


def daily_default_details(target: date, config: AppConfig) -> Tuple[int, Dict[str, int]]:
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


def _daily_spend_between(
    start: date, end: date, defaults: DailyDefaultsConfig
) -> Tuple[int, Dict[date, int], Dict[str, Dict[str, int]]]:
    if end < start:
        return 0, {}, {}
    totals_by_date: Dict[date, int] = OrderedDict()
    per_item: Dict[str, Dict[str, int]] = OrderedDict()
    total = 0
    current = start
    while current <= end:
        day_total, breakdown = _default_cost_for_date(current, defaults)
        totals_by_date[current] = day_total
        total += day_total
        for item, value in breakdown.items():
            item_label = _ITEM_LABEL_OVERRIDES.get(
                item, item.replace("_", " ").title()
            )
            bucket = per_item.setdefault(item_label, {"total": 0, "count": 0})
            bucket["total"] += value
            bucket["count"] += 1
        current += timedelta(days=1)
    return total, totals_by_date, per_item


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
                    f"{key}: \u20b9{value}" for key, value in breakdown.items()
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


def _upcoming_tenth(anchor: date) -> date:
    if anchor.day <= 10:
        return anchor.replace(day=10)
    next_month = anchor.month + 1
    year = anchor.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    return _safe_date(year, month, 10)


def compute_required_windows(
    today: date, config: AppConfig
) -> Tuple[RequiredFunds, RequiredFunds]:
    due_date = _first_day_next_month(today)
    tenth_date = _upcoming_tenth(today)

    rent = config.fixed_bills.rent
    tiffin = _tiffin_allocation(config)
    weekday_meals = config.fixed_bills.tiffin_weekday_count
    saturday_meals = config.fixed_bills.tiffin_saturday_count
    electricity = _electricity_allocation(due_date, config)
    rent_due = due_date
    tiffin_due = due_date
    electricity_due = due_date

    primary_daily_total, _, primary_breakdown = _daily_spend_between(
        today, due_date, config.daily_defaults
    )
    primary_days = (due_date - today).days + 1

    tenth_daily_total, _, tenth_breakdown = _daily_spend_between(
        today, tenth_date, config.daily_defaults
    )
    tenth_days = (tenth_date - today).days + 1

    primary_total = rent + tiffin + electricity + primary_daily_total
    primary = RequiredFunds(
        start=today,
        end=due_date,
        total=primary_total,
        rent=rent,
        tiffin=tiffin,
        tiffin_weekday_meals=weekday_meals,
        tiffin_saturday_meals=saturday_meals,
        electricity=electricity,
        electricity_due=electricity_due,
        daily_spend_total=primary_daily_total,
        day_count=primary_days,
        daily_breakdown={
            key: {"total": value["total"], "count": value["count"]}
            for key, value in primary_breakdown.items()
        },
    )

    rent_within_tenth = rent if rent_due <= tenth_date else 0
    tiffin_within_tenth = tiffin if tiffin_due <= tenth_date else 0
    electricity_within_tenth = electricity if electricity_due <= tenth_date else 0
    tenth_total = (
        rent_within_tenth
        + tiffin_within_tenth
        + electricity_within_tenth
        + tenth_daily_total
    )
    tenth = RequiredFunds(
        start=today,
        end=tenth_date,
        total=tenth_total,
        rent=rent_within_tenth,
        tiffin=tiffin_within_tenth,
        tiffin_weekday_meals=weekday_meals,
        tiffin_saturday_meals=saturday_meals,
        electricity=electricity_within_tenth,
        electricity_due=electricity_due,
        daily_spend_total=tenth_daily_total,
        day_count=tenth_days,
        daily_breakdown={
            key: {"total": value["total"], "count": value["count"]}
            for key, value in tenth_breakdown.items()
        },
    )

    return primary, tenth
