"""High-level cycle management logic."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from zoneinfo import ZoneInfo

from .finance import build_cycle_computation, daily_default_details
from .models import (
    AppConfig,
    AppState,
    CycleState,
    DailyRecord,
    DailyWalletState,
    ExtraSpendEntry,
    IncomeEntry,
)
from .storage import StateStorage


class CycleManager:
    """Encapsulates business logic around cycle state transitions."""

    def __init__(self, config: AppConfig, storage: StateStorage) -> None:
        self._config = config
        self._storage = storage
        self._tz = ZoneInfo(self._config.cycle.timezone)
        self._apply_overrides()

    @property
    def config(self) -> AppConfig:
        return self._config

    def load_state(self) -> AppState:
        return self._storage.load()

    def save_state(self, state: AppState) -> None:
        self._storage.save(state)

    def _apply_overrides(self) -> None:
        state = self._storage.load()
        overrides = state.overrides.get("daily_defaults") if state.overrides else None
        if not overrides:
            return
        for key, value in overrides.items():
            if "." not in key:
                continue
            category, item = key.split(".", maxsplit=1)
            self._set_default_value(category, item, int(value))

    def _set_default_value(self, category: str, item: str, amount: int) -> None:
        if category not in {"weekday", "saturday", "sunday"}:
            raise ValueError("Invalid default category")
        mapping = getattr(self._config.daily_defaults, category)
        mapping[item] = amount

    # ---------------------------------------------------------------------
    # Cycle lifecycle helpers
    # ---------------------------------------------------------------------
    def start_cycle(
        self, *, amount: int, start_date: date, user_id: Optional[int] = None
    ) -> CycleState:
        computation = build_cycle_computation(start_date, self._config)
        cycle_end = computation.end

        incomes: Dict[str, IncomeEntry] = {}
        matched_start = False
        for income in computation.incomes:
            planned = income.planned_amount
            received = income.received_amount
            if income.date == start_date:
                planned = amount
                received = amount
                matched_start = True
            incomes[income.date.isoformat()] = IncomeEntry(
                date=income.date,
                description=income.description,
                planned_amount=planned,
                received_amount=received,
            )

        if not matched_start:
            # No configured income on the start date; register a manual entry.
            manual_income = IncomeEntry(
                date=start_date,
                description="Cycle opening balance",
                planned_amount=amount,
                received_amount=amount,
            )
            incomes[start_date.isoformat()] = manual_income

        ordered_incomes = [incomes[key] for key in sorted(incomes.keys())]

        total_income_expected = sum(entry.effective_amount for entry in ordered_incomes)

        sinking_total = computation.sinking_breakdown.total
        daily_goal = total_income_expected - sinking_total
        expected_default_spend = computation.expected_default_spend
        buffer_allocation = daily_goal - expected_default_spend

        daily_wallet = DailyWalletState(
            goal=daily_goal,
            balance=daily_goal,
            spent=0,
            expected_default_spend=expected_default_spend,
            buffer_allocation=buffer_allocation,
        )

        cycle_state = CycleState(
            start=start_date,
            end=cycle_end,
            due_date=computation.due_date,
            sinking_breakdown=computation.sinking_breakdown,
            daily_wallet=daily_wallet,
            incomes=ordered_incomes,
            survival_allocation=computation.survival,
            default_totals_by_date={
                key.isoformat(): value
                for key, value in computation.default_totals_by_date.items()
            },
            timezone=self._config.cycle.timezone,
        )

        state = self.load_state()
        state.cycle = cycle_state
        if user_id is not None:
            state.user_id = user_id
        state.overrides = state.overrides or {}
        self.save_state(state)
        return cycle_state

    # ------------------------------------------------------------------
    # Information helpers
    # ------------------------------------------------------------------
    def get_cycle(self) -> Optional[CycleState]:
        return self.load_state().cycle

    def get_status_snapshot(self, today: date) -> Dict[str, object]:
        state = self.load_state()
        if not state.cycle:
            raise RuntimeError("No active cycle. Use /start_cycle to begin.")
        cycle = state.cycle
        days_left = (cycle.end - today).days + 1
        days_left = max(days_left, 0)
        average = 0 if days_left == 0 else cycle.daily_wallet.balance / days_left
        default_total, breakdown = daily_default_details(today, self._config)
        wiggle = max(0, average - default_total)
        return {
            "cycle": cycle,
            "days_left": days_left,
            "today_default": {
                "total": default_total,
                "breakdown": breakdown,
                "wiggle": wiggle,
            },
        }

    # ------------------------------------------------------------------
    # Spend logging helpers
    # ------------------------------------------------------------------
    def log_extra_spend(
        self, *, amount: int, note: Optional[str], timestamp: datetime
    ) -> CycleState:
        state = self.load_state()
        if not state.cycle:
            raise RuntimeError("No active cycle to log spending against.")
        cycle = state.cycle
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=self._tz)
        else:
            timestamp = timestamp.astimezone(self._tz)
        date_key = timestamp.date().isoformat()
        record = cycle.records.get(date_key)
        if not record:
            record = DailyRecord(date=timestamp.date())
        record.extras.append(
            ExtraSpendEntry(amount=amount, note=note, timestamp=timestamp)
        )
        cycle.records[date_key] = record
        cycle.daily_wallet.balance -= amount
        cycle.daily_wallet.spent += amount
        self.save_state(state)
        return cycle

    def apply_daily_defaults(
        self,
        *,
        target_date: date,
        extra_amount: int = 0,
        note: Optional[str] = None,
        auto_closed: bool = False,
    ) -> CycleState:
        state = self.load_state()
        if not state.cycle:
            raise RuntimeError("No active cycle found.")
        cycle = state.cycle
        date_key = target_date.isoformat()
        default_amount = cycle.default_totals_by_date.get(date_key, 0)
        record = cycle.records.get(date_key)
        if not record:
            record = DailyRecord(date=target_date)
        previous_defaults = record.defaults_applied
        record.defaults_applied = default_amount
        record.auto_closed = auto_closed
        if note:
            record.note = note
        if extra_amount:
            record.extras.append(
                ExtraSpendEntry(
                    amount=extra_amount,
                    note="Auto extra" if auto_closed and not note else note,
                    timestamp=datetime.now(self._tz),
                )
            )
            cycle.daily_wallet.balance -= extra_amount
            cycle.daily_wallet.spent += extra_amount
        # Apply defaults if not already accounted for
        self._apply_default_spend_to_wallet(cycle, default_amount, previous_defaults)
        cycle.records[date_key] = record
        cycle.pending_default_amount = 0
        cycle.pending_default_date = None
        cycle.pending_default_job_name = None
        self.save_state(state)
        return cycle

    def _apply_default_spend_to_wallet(
        self, cycle: CycleState, default_amount: int, recorded_amount: int
    ) -> None:
        delta = default_amount - recorded_amount
        if delta <= 0:
            return
        cycle.daily_wallet.balance -= delta
        cycle.daily_wallet.spent += delta

    # ------------------------------------------------------------------
    # Income helpers
    # ------------------------------------------------------------------
    def register_income(self, *, amount: int, income_date: date) -> CycleState:
        state = self.load_state()
        if not state.cycle:
            raise RuntimeError("No active cycle.")
        cycle = state.cycle
        income_key = income_date.isoformat()
        target_entry = None
        for entry in cycle.incomes:
            if entry.date == income_date:
                target_entry = entry
                break
        if target_entry is None:
            target_entry = IncomeEntry(
                date=income_date,
                description="Additional income",
                planned_amount=amount,
                received_amount=amount,
            )
            cycle.incomes.append(target_entry)
            cycle.incomes.sort(key=lambda item: item.date)
            cycle.daily_wallet.goal += amount
            cycle.daily_wallet.balance += amount
        else:
            previous_effective = target_entry.effective_amount
            target_entry.received_amount = amount
            target_entry.planned_amount = amount
            delta = amount - previous_effective
            cycle.daily_wallet.goal += delta
            cycle.daily_wallet.balance += delta
        cycle.daily_wallet.buffer_allocation = (
            cycle.daily_wallet.goal - cycle.daily_wallet.expected_default_spend
        )
        self.save_state(state)
        return cycle

    def mark_pending_default(self, *, target_date: date, job_name: str) -> CycleState:
        state = self.load_state()
        if not state.cycle:
            raise RuntimeError("No active cycle.")
        cycle = state.cycle
        date_key = target_date.isoformat()
        cycle.pending_default_date = target_date
        cycle.pending_default_amount = cycle.default_totals_by_date.get(date_key, 0)
        cycle.pending_default_job_name = job_name
        self.save_state(state)
        return cycle

    def clear_pending_default(self) -> None:
        state = self.load_state()
        if not state.cycle:
            return
        cycle = state.cycle
        cycle.pending_default_amount = 0
        cycle.pending_default_date = None
        cycle.pending_default_job_name = None
        self.save_state(state)

    # ------------------------------------------------------------------
    # Configuration overrides
    # ------------------------------------------------------------------
    def update_daily_default(self, *, category: str, item: str, amount: int) -> None:
        state = self.load_state()
        self._set_default_value(category, item, amount)
        overrides = state.overrides.setdefault("daily_defaults", {})
        overrides[f"{category}.{item}"] = amount
        self.save_state(state)
