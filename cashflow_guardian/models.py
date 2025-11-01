"""Data models for the Cash-Flow Guardian bot."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class FixedBillsConfig(BaseModel):
    rent: int = Field(ge=0)
    tiffin_daily_cost: int = Field(ge=0)
    tiffin_weekday_count: int = Field(ge=0)
    tiffin_saturday_count: int = Field(ge=0)
    electricity_amount: int = Field(ge=0)
    electricity_due_months: List[int] = Field(default_factory=list)


class IncomeSourceConfig(BaseModel):
    day: int = Field(ge=1, le=31)
    amount: int = Field(ge=0)
    description: str


class DailyDefaultsConfig(BaseModel):
    weekday: Dict[str, int]
    saturday: Dict[str, int]
    sunday: Dict[str, int]


class CycleConfig(BaseModel):
    length_days: int = Field(default=30, ge=1)
    timezone: str = "Asia/Kolkata"
    checkin_time: str = "21:30"
    auto_apply_defaults_after_minutes: int = Field(default=60, ge=5)


class BufferConfig(BaseModel):
    track: bool = True


class AppConfig(BaseModel):
    fixed_bills: FixedBillsConfig
    income_sources: List[IncomeSourceConfig]
    daily_defaults: DailyDefaultsConfig
    cycle: CycleConfig
    buffer: BufferConfig = Field(default_factory=BufferConfig)


class IncomeEntry(BaseModel):
    date: date
    description: str
    planned_amount: int
    received_amount: Optional[int] = None

    @property
    def effective_amount(self) -> int:
        return self.received_amount if self.received_amount is not None else self.planned_amount


class ExtraSpendEntry(BaseModel):
    amount: int
    note: Optional[str] = None
    timestamp: datetime


class DailyRecord(BaseModel):
    date: date
    defaults_applied: int = 0
    extras: List[ExtraSpendEntry] = Field(default_factory=list)
    auto_closed: bool = False
    note: Optional[str] = None

    @property
    def total_spent(self) -> int:
        extra_total = sum(entry.amount for entry in self.extras)
        return self.defaults_applied + extra_total


class SurvivalDay(BaseModel):
    date: str
    default_spend: int
    breakdown: str


class SurvivalAllocation(BaseModel):
    total: int
    dates: List[SurvivalDay]


class SinkingBreakdown(BaseModel):
    rent: int
    tiffin: int
    electricity: int
    survival: int

    @property
    def total(self) -> int:
        return self.rent + self.tiffin + self.electricity + self.survival


class DailyWalletState(BaseModel):
    goal: int
    balance: int
    spent: int
    expected_default_spend: int
    buffer_allocation: int


class CycleState(BaseModel):
    start: date
    end: date
    due_date: date
    sinking_breakdown: SinkingBreakdown
    daily_wallet: DailyWalletState
    incomes: List[IncomeEntry]
    survival_allocation: SurvivalAllocation
    records: Dict[str, DailyRecord] = Field(default_factory=dict)
    default_totals_by_date: Dict[str, int] = Field(default_factory=dict)
    pending_default_date: Optional[date] = None
    pending_default_amount: int = 0
    pending_default_job_name: Optional[str] = None
    timezone: str


class AppState(BaseModel):
    user_id: Optional[int] = None
    cycle: Optional[CycleState] = None
    overrides: Dict[str, Dict] = Field(default_factory=dict)

    def copy_with_cycle(self, cycle: CycleState) -> "AppState":
        return AppState(user_id=self.user_id, cycle=cycle, overrides=self.overrides)
