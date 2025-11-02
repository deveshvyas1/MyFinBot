"""Google Sheets persistence helpers for daily spend logs."""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import List, Optional

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
from zoneinfo import ZoneInfo

from .models import DailySpendLog, SheetsConfig


class GoogleSheetsSpendStore:
    """Wrapper around gspread for storing daily spend entries."""

    SCOPES = (
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    )
    HEADERS = [
        "Date",
        "Breakfast",
        "Lunch",
        "Dinner",
        "Other",
        "AutoFilled",
        "RecordedAt",
    ]

    def __init__(self, config: Optional[SheetsConfig], timezone: ZoneInfo) -> None:
        self._config = config
        self._tz = timezone
        self._enabled = bool(config and config.enabled)
        self._worksheet: Optional[gspread.Worksheet] = None
        self._client: Optional[gspread.Client] = None
        self._ready = False
        if self._enabled:
            self._ready = self._connect()

    @property
    def is_ready(self) -> bool:
        return self._ready and self._worksheet is not None

    def fetch_all(self) -> Optional[List[DailySpendLog]]:
        if not self._ensure_connection():
            return None
        assert self._worksheet is not None
        try:
            records = self._worksheet.get_all_records()
        except APIError as exc:
            print("Failed to fetch spends from Google Sheets:", exc)
            return None
        entries: List[DailySpendLog] = []
        for record in records:
            date_str = str(record.get("Date", "")).strip()
            if not date_str:
                continue
            try:
                entry_date = date.fromisoformat(date_str)
            except ValueError:
                continue
            breakfast = self._as_int(record.get("Breakfast"))
            lunch = self._as_int(record.get("Lunch"))
            dinner = self._as_int(record.get("Dinner"))
            other = self._as_int(record.get("Other"))
            auto_raw = record.get("AutoFilled")
            recorded_raw = record.get("RecordedAt")
            entry = DailySpendLog(
                date=entry_date,
                breakfast=breakfast,
                lunch=lunch,
                dinner=dinner,
                other=other,
                auto_filled=self._as_bool(auto_raw),
                recorded_at=self._parse_datetime(recorded_raw),
            )
            entries.append(entry)
        return entries

    def upsert(self, entry: DailySpendLog) -> None:
        if not self._ensure_connection():
            return
        assert self._worksheet is not None
        row_values = self._serialize(entry)
        try:
            existing_dates = self._worksheet.col_values(1)
        except APIError as exc:
            print("Failed to read spend rows from Google Sheets:", exc)
            return
        target_row: Optional[int] = None
        for index, value in enumerate(existing_dates, start=1):
            if index == 1:
                continue  # header row
            if value.strip() == entry.date.isoformat():
                target_row = index
                break
        try:
            if target_row is not None:
                self._worksheet.update(
                    f"A{target_row}:G{target_row}",
                    [row_values],
                    value_input_option="USER_ENTERED",
                )
            else:
                self._worksheet.append_row(
                    row_values,
                    value_input_option="USER_ENTERED",
                )
        except APIError as exc:
            print("Failed to upsert spend row in Google Sheets:", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_connection(self) -> bool:
        if not self._enabled:
            return False
        if self.is_ready:
            return True
        self._ready = self._connect()
        if not self._ready:
            self._enabled = False
        return self._ready

    def _connect(self) -> bool:
        credentials_path = self._resolve_credentials_path()
        spreadsheet_name = self._resolve_spreadsheet_name()
        worksheet_name = self._resolve_worksheet_name()
        if not credentials_path or not spreadsheet_name:
            print("Google Sheets integration disabled: missing credentials or spreadsheet name.")
            return False
        try:
            credentials = Credentials.from_service_account_file(
                credentials_path, scopes=self.SCOPES
            )
        except Exception as exc:  # pragma: no cover - credential parsing errors
            print("Failed to load Google Sheets credentials:", exc)
            return False
        try:
            client = gspread.authorize(credentials)
        except Exception as exc:  # pragma: no cover - authorization errors
            print("Failed to authorise Google Sheets client:", exc)
            return False
        try:
            spreadsheet = client.open(spreadsheet_name)
        except SpreadsheetNotFound:
            print(f"Spreadsheet '{spreadsheet_name}' not found. Check the share permissions.")
            return False
        try:
            if worksheet_name:
                worksheet = spreadsheet.worksheet(worksheet_name)
            else:
                worksheet = spreadsheet.sheet1
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=worksheet_name or "Sheet1",
                rows=1000,
                cols=len(self.HEADERS),
            )
            self._initialize_headers(worksheet)
        else:
            self._ensure_headers(worksheet)
        self._client = client
        self._worksheet = worksheet
        return True

    def _initialize_headers(self, worksheet: gspread.Worksheet) -> None:
        worksheet.update("A1:G1", [self.HEADERS])

    def _ensure_headers(self, worksheet: gspread.Worksheet) -> None:
        try:
            current_headers = worksheet.row_values(1)
        except APIError:
            current_headers = []
        if current_headers == self.HEADERS:
            return
        worksheet.update("A1:G1", [self.HEADERS])

    def _resolve_credentials_path(self) -> Optional[str]:
        if self._config and self._config.credentials_path:
            return self._config.credentials_path
        return os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    def _resolve_spreadsheet_name(self) -> Optional[str]:
        if self._config and self._config.spreadsheet_name:
            return self._config.spreadsheet_name
        return os.environ.get("GOOGLE_SHEETS_SPREADSHEET")

    def _resolve_worksheet_name(self) -> Optional[str]:
        if self._config and self._config.worksheet_name:
            return self._config.worksheet_name
        return os.environ.get("GOOGLE_SHEETS_WORKSHEET")

    def _serialize(self, entry: DailySpendLog) -> List[object]:
        return [
            entry.date.isoformat(),
            entry.breakfast,
            entry.lunch,
            entry.dinner,
            entry.other,
            entry.auto_filled,
            entry.recorded_at.astimezone(self._tz).isoformat(),
        ]

    def _as_int(self, raw: object) -> int:
        if raw is None:
            return 0
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float):
            return int(raw)
        raw_str = str(raw).strip()
        if not raw_str:
            return 0
        try:
            return int(float(raw_str))
        except ValueError:
            return 0

    def _as_bool(self, raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return False
        return str(raw).strip().lower() in {"true", "1", "yes"}

    def _parse_datetime(self, raw: object) -> datetime:
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                return raw.replace(tzinfo=self._tz)
            return raw.astimezone(self._tz)
        if raw is None:
            return datetime.now(self._tz)
        raw_str = str(raw).strip()
        if not raw_str:
            return datetime.now(self._tz)
        try:
            value = datetime.fromisoformat(raw_str)
        except ValueError:
            return datetime.now(self._tz)
        if value.tzinfo is None:
            return value.replace(tzinfo=self._tz)
        return value.astimezone(self._tz)