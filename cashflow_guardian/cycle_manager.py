"""High-level cycle management logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from zoneinfo import ZoneInfo

from .finance import (
    build_cycle_computation,
    compute_required_windows,
    daily_default_details,
    resolve_cycle_start,
)
from .models import (
    AppConfig,
    AppState,
    CycleState,
    DailyRecord,
    DailySpendLog,
    DailyWalletState,
    ExtraSpendEntry,
    IncomeEntry,
)
from .sheets_store import GoogleSheetsSpendStore
from .storage import StateStorage


class CycleManager:
    """Encapsulates business logic around cycle state transitions."""

    def __init__(self, config: AppConfig, storage: StateStorage) -> None:
        self._config = config
        self._storage = storage
        self._tz = ZoneInfo(self._config.cycle.timezone)
        self._apply_overrides()
        self._sheets_store: Optional[GoogleSheetsSpendStore] = None
        if self._config.sheets and self._config.sheets.enabled:
            self._sheets_store = GoogleSheetsSpendStore(self._config.sheets, self._tz)
            self._refresh_spend_cache()

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

    def _refresh_spend_cache(self) -> None:
        if not self._sheets_store or not self._sheets_store.is_ready:
            return
        logs = self._sheets_store.fetch_all()
        if logs is None:
            return
        log_map = {entry.date.isoformat(): entry for entry in logs}
        state = self.load_state()
        if state.spend_logs != log_map:
            state.spend_logs = log_map
            self.save_state(state)

    def _persist_spend_entry(self, entry: DailySpendLog) -> None:
        if self._sheets_store and self._sheets_store.is_ready:
            self._sheets_store.upsert(entry)

    def _spend_defaults_for_date(self, target_date: date) -> Dict[str, int]:
        weekday = target_date.weekday()
        if weekday <= 4:
            mapping = self._config.daily_defaults.weekday
        elif weekday == 5:
            mapping = self._config.daily_defaults.saturday
        else:
            mapping = self._config.daily_defaults.sunday
        return {
            "breakfast": int(mapping.get("breakfast", 0)),
            "lunch": int(mapping.get("lunch", 0)),
            "dinner": int(mapping.get("dinner", 0)),
        }

    # ---------------------------------------------------------------------
    # Cycle lifecycle helpers
    # ---------------------------------------------------------------------
    def start_cycle(
        self, *, amount: int, start_date: date, user_id: Optional[int] = None
    ) -> CycleState:
        cycle_state = self._create_cycle_state(start_date, override_start_income=amount)
        state = self.load_state()
        state.cycle = cycle_state
        if user_id is not None:
            state.user_id = user_id
        state.overrides = state.overrides or {}
        self.save_state(state)
        return cycle_state

    def _create_cycle_state(
        self, start_date: date, override_start_income: Optional[int] = None
    ) -> CycleState:
        computation = build_cycle_computation(start_date, self._config)
        cycle_end = computation.end

        incomes: Dict[str, IncomeEntry] = {}
        matched_start = False
        for income in computation.incomes:
            planned = income.planned_amount
            received = income.received_amount
            if income.date == start_date:
                if override_start_income is not None:
                    planned = override_start_income
                    received = override_start_income
                else:
                    received = planned
                matched_start = True
            else:
                received = planned
            incomes[income.date.isoformat()] = IncomeEntry(
                date=income.date,
                description=income.description,
                planned_amount=planned,
                received_amount=received,
            )

        if override_start_income is not None and not matched_start:
            manual_income = IncomeEntry(
                date=start_date,
                description="Cycle opening balance",
                planned_amount=override_start_income,
                received_amount=override_start_income,
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
        return cycle_state

    def ensure_cycle_for_date(
        self, today: date, user_id: Optional[int] = None
    ) -> CycleState:
        expected_start = resolve_cycle_start(today, self._config)
        state = self.load_state()
        cycle = state.cycle
        if cycle and cycle.start == expected_start:
            if user_id is not None and state.user_id is None:
                state.user_id = user_id
                self.save_state(state)
            return cycle

        cycle_state = self._create_cycle_state(expected_start)
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

    def get_status_snapshot(
        self, today: date, user_id: Optional[int] = None
    ) -> Dict[str, object]:
        self._refresh_spend_cache()
        cycle = self.ensure_cycle_for_date(today, user_id=user_id)
        primary, tenth = compute_required_windows(today, self._config)
        default_total, breakdown = daily_default_details(today, self._config)
        components = {
            "rent": {"amount": primary.rent, "due_date": primary.end},
            "electricity": {
                "amount": primary.electricity,
                "due_date": primary.electricity_due,
            },
            "tiffin": {
                "amount": primary.tiffin,
                "weekday_meals": primary.tiffin_weekday_meals,
                "saturday_meals": primary.tiffin_saturday_meals,
                "due_date": primary.end,
            },
            "daily": {
                "amount": primary.daily_spend_total,
                "start": primary.start,
                "end": primary.end,
                "days": primary.day_count,
                "breakdown": primary.daily_breakdown,
            },
        }
        extra_days = max(tenth.day_count - primary.day_count, 0)
        extra_daily_amount = max(
            tenth.daily_spend_total - primary.daily_spend_total, 0
        )
        extra_start = primary.end + timedelta(days=1) if extra_days > 0 else None
        spend_summary = self._build_spend_summary(today)
        return {
            "cycle": cycle,
            "today": today,
            "primary": {
                "total": primary.total,
                "end": primary.end,
                "days": primary.day_count,
                "daily_amount": primary.daily_spend_total,
                "daily_breakdown": primary.daily_breakdown,
            },
            "components": components,
            "tenth_summary": {
                "total": tenth.total,
                "end": tenth.end,
                "days": tenth.day_count,
                "daily_amount": tenth.daily_spend_total,
                "extra_days": extra_days,
                "extra_daily_amount": extra_daily_amount,
                "extra_start": extra_start,
            },
            "today_default": {
                "total": default_total,
                "breakdown": breakdown,
            },
            "spending_summary": spend_summary,
        }

    # ------------------------------------------------------------------
    # Spend logging helpers
    # ------------------------------------------------------------------
    def log_daily_spend(
        self,
        *,
        entry_date: date,
        breakfast: int,
        lunch: int,
        dinner: int,
        other: int,
        auto_filled: bool = False,
    ) -> DailySpendLog:
        self._refresh_spend_cache()
        state = self.load_state()
        recorded_at = datetime.now(self._tz)
        entry = DailySpendLog(
            date=entry_date,
            breakfast=breakfast,
            lunch=lunch,
            dinner=dinner,
            other=other,
            auto_filled=auto_filled,
            recorded_at=recorded_at,
        )
        state.spend_logs[entry_date.isoformat()] = entry
        self._persist_spend_entry(entry)
        if (
            state.pending_spend_log_date == entry_date
            and state.pending_spend_log_job_name
        ):
            state.pending_spend_log_date = None
            state.pending_spend_log_job_name = None
        self.save_state(state)
        return entry

    def get_daily_spend(self, entry_date: date) -> Optional[DailySpendLog]:
        self._refresh_spend_cache()
        state = self.load_state()
        return state.spend_logs.get(entry_date.isoformat())

    def ensure_default_spend_log(self, entry_date: date) -> Optional[DailySpendLog]:
        self._refresh_spend_cache()
        state = self.load_state()
        if entry_date.isoformat() in state.spend_logs:
            return None
        defaults = self._spend_defaults_for_date(entry_date)
        dinner_default = defaults.get("dinner", 90)
        entry = DailySpendLog(
            date=entry_date,
            breakfast=defaults.get("breakfast", 35),
            lunch=defaults.get("lunch", 50),
            dinner=dinner_default,
            other=0,
            auto_filled=True,
            recorded_at=datetime.now(self._tz),
        )
        state.spend_logs[entry_date.isoformat()] = entry
        self._persist_spend_entry(entry)
        if (
            state.pending_spend_log_date == entry_date
            and state.pending_spend_log_job_name
        ):
            state.pending_spend_log_date = None
            state.pending_spend_log_job_name = None
        self.save_state(state)
        return entry

    def mark_pending_spend(self, *, target_date: date, job_name: str) -> None:
        state = self.load_state()
        state.pending_spend_log_date = target_date
        state.pending_spend_log_job_name = job_name
        self.save_state(state)

    def clear_pending_spend(self, target_date: Optional[date] = None) -> None:
        state = self.load_state()
        if state.pending_spend_log_date is None:
            return
        if target_date and state.pending_spend_log_date != target_date:
            return
        state.pending_spend_log_date = None
        state.pending_spend_log_job_name = None
        self.save_state(state)

    def _build_spend_summary(self, today: date) -> Optional[Dict[str, object]]:
        state = self.load_state()
        if not state.spend_logs:
            return None
        logs = sorted(
            (log for log in state.spend_logs.values()),
            key=lambda item: item.date,
        )
        current_month_start = today.replace(day=1)
        previous_months: Dict[date, List[DailySpendLog]] = {}
        current_month_logs: List[DailySpendLog] = []
        for log in logs:
            month_start = log.date.replace(day=1)
            if month_start < current_month_start:
                previous_months.setdefault(month_start, []).append(log)
            elif month_start == current_month_start:
                current_month_logs.append(log)
        history = []
        for month_start in sorted(previous_months.keys()):
            total = sum(entry.total for entry in previous_months[month_start])
            history.append(
                {
                    "label": month_start.strftime("%b %Y").upper(),
                    "total": total,
                }
            )
        cutoff = today - timedelta(days=1)
        current_total = sum(
            entry.total for entry in current_month_logs if entry.date <= cutoff
        )
        current_label = f"{today.strftime('%b').upper()} 1 → ongoing"
        return {
            "history": history,
            "current_label": current_label,
            "current_total": current_total,
            "has_data": bool(history or current_month_logs),
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
