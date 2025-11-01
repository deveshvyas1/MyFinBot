"""Telegram command and job handlers."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    JobQueue,
    MessageHandler,
    filters,
)
from zoneinfo import ZoneInfo

from .cycle_manager import CycleManager
from .finance import parse_checkin_time
from .formatters import format_cycle_intro, format_status

CHECKIN_JOB_NAME = "cashflow_guardian_daily_checkin"
SET_DEFAULTS_WAIT = 1


class BotHandlers:
    """Container for command callbacks."""

    def __init__(self, cycle_manager: CycleManager) -> None:
        self.cycle_manager = cycle_manager
        self._tz = ZoneInfo(self.cycle_manager.config.cycle.timezone)

    def _current_date(self) -> date:
        return datetime.now(self._tz).date()

    # ------------------------------------------------------------------
    # Command callbacks
    # ------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        assert update.effective_chat
        greeting = (
            "Hello! I am the Cash-Flow Guardian bot.\n"
            "Use /status anytime to see how much cash to hold for the 5th and 10th. "
            "Optional: /set_balance <amount> if you want to override an income."
        )
        await update.message.reply_text(greeting)  # type: ignore[arg-type]
        today = self._current_date()
        user_id = update.effective_user.id if update.effective_user else None
        try:
            snapshot = self.cycle_manager.get_status_snapshot(
                today, user_id=user_id
            )
        except RuntimeError:
            return
        message = format_status(
            due_date=snapshot["due_date"],
            required_amount=snapshot["required_total"],
        )
        await update.message.reply_text(message)  # type: ignore[arg-type]

    async def start_cycle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /start_cycle <amount>")  # type: ignore[arg-type]
            return
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Please provide a valid integer amount.")  # type: ignore[arg-type]
            return
        if amount <= 0:
            await update.message.reply_text("Amount must be positive.")  # type: ignore[arg-type]
            return
        user_id = update.effective_user.id if update.effective_user else None
        today = self._current_date()
        cycle = self.cycle_manager.start_cycle(
            amount=amount,
            start_date=today,
            user_id=user_id,
        )
        await update.message.reply_text(format_cycle_intro(cycle))  # type: ignore[arg-type]
        await self._schedule_checkin_job(update, context)

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        today = self._current_date()
        user_id = update.effective_user.id if update.effective_user else None
        try:
            snapshot = self.cycle_manager.get_status_snapshot(
                today, user_id=user_id
            )
        except RuntimeError as exc:
            await update.message.reply_text(str(exc))  # type: ignore[arg-type]
            return
        message = format_status(
            due_date=snapshot["due_date"],
            required_amount=snapshot["required_total"],
        )
        await update.message.reply_text(message)  # type: ignore[arg-type]

    async def log_extra(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text(
                "Usage: /log_extra <amount> [optional note]"
            )  # type: ignore[arg-type]
            return
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Amount must be an integer.")  # type: ignore[arg-type]
            return
        if amount <= 0:
            await update.message.reply_text("Amount must be positive.")  # type: ignore[arg-type]
            return
        note = " ".join(context.args[1:]) if len(context.args) > 1 else None
        try:
            self.cycle_manager.log_extra_spend(
                amount=amount, note=note, timestamp=datetime.now(self._tz)
            )
        except RuntimeError as exc:
            await update.message.reply_text(str(exc))  # type: ignore[arg-type]
            return
        await update.message.reply_text(
            f"Logged extra spend of {amount}."
        )  # type: ignore[arg-type]

    async def set_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /set_balance <amount>")  # type: ignore[arg-type]
            return
        try:
            amount = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Please provide a whole number amount.")  # type: ignore[arg-type]
            return
        if amount <= 0:
            await update.message.reply_text("Amount must be positive.")  # type: ignore[arg-type]
            return
        state = self.cycle_manager.get_cycle()
        if state is None:
            await self.start_cycle(update, context)
            return
        income_date = self._current_date()
        self.cycle_manager.register_income(amount=amount, income_date=income_date)
        await update.message.reply_text(
            f"Recorded income of {amount} on {income_date.isoformat()}."
        )  # type: ignore[arg-type]

    async def daily_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        extra_amount = 0
        note: Optional[str] = None
        if context.args:
            try:
                extra_amount = int(context.args[0])
            except ValueError:
                await update.message.reply_text(
                    "Extra amount must be an integer."
                )  # type: ignore[arg-type]
                return
            note = " ".join(context.args[1:]) if len(context.args) > 1 else None
        today = self._current_date()
        cycle = self.cycle_manager.get_cycle()
        if cycle is None or cycle.pending_default_date != today:
            await update.message.reply_text(
                "No pending check-in for today."
            )  # type: ignore[arg-type]
            return
        if cycle.pending_default_job_name:
            self._cancel_job(context.job_queue, cycle.pending_default_job_name)
        self.cycle_manager.apply_daily_defaults(
            target_date=today, extra_amount=extra_amount, note=note
        )
        await update.message.reply_text(
            "Check-in recorded. Defaults applied."
        )  # type: ignore[arg-type]

    async def set_defaults_entry(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        allowed = ", ".join(["weekday", "saturday", "sunday"])
        await update.message.reply_text(
            "Send updates in the form '<category> <item> <amount>'.\n"
            f"Categories: {allowed}. Type 'done' to finish."
        )  # type: ignore[arg-type]
        return SET_DEFAULTS_WAIT

    async def set_defaults_update(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        assert update.message
        text = update.message.text.strip()
        if text.lower() in {"done", "cancel"}:
            await update.message.reply_text("Defaults update complete.")  # type: ignore[arg-type]
            return ConversationHandler.END
        parts = text.split()
        if len(parts) != 3:
            await update.message.reply_text(
                "Please send '<category> <item> <amount>'."
            )  # type: ignore[arg-type]
            return SET_DEFAULTS_WAIT
        category, item, amount_str = parts
        try:
            amount = int(amount_str)
        except ValueError:
            await update.message.reply_text("Amount must be a number.")  # type: ignore[arg-type]
            return SET_DEFAULTS_WAIT
        if amount < 0:
            await update.message.reply_text("Amount cannot be negative.")  # type: ignore[arg-type]
            return SET_DEFAULTS_WAIT
        try:
            self.cycle_manager.update_daily_default(
                category=category.lower(), item=item.lower(), amount=amount
            )
        except ValueError as exc:
            await update.message.reply_text(str(exc))  # type: ignore[arg-type]
            return SET_DEFAULTS_WAIT
        await update.message.reply_text(
            f"Updated {category}.{item} to {amount}."
        )  # type: ignore[arg-type]
        return SET_DEFAULTS_WAIT

    async def cancel_defaults(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        await update.message.reply_text("Defaults update cancelled.")  # type: ignore[arg-type]
        return ConversationHandler.END

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------
    async def daily_checkin_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        job = context.job
        if job is None:
            return
        chat_id = job.chat_id
        today = self._current_date()
        try:
            snapshot = self.cycle_manager.get_status_snapshot(today)
        except RuntimeError:
            return
        message_lines = [
            "21:30 check-in",
            format_status(
                due_date=snapshot["due_date"],
                required_amount=snapshot["required_total"],
            ),
            "Reply with /daily_confirm <extra> to log any extras within 60 minutes.",
        ]
        await context.bot.send_message(chat_id=chat_id, text="\n".join(message_lines))
        auto_job_name = f"{CHECKIN_JOB_NAME}_auto_{today.isoformat()}"
        job_queue = context.job_queue
        if job_queue is None:
            return
        self._cancel_job(job_queue, auto_job_name)
        job_queue.run_once(
            self.auto_apply_defaults_job,
            when=timedelta(
                minutes=self.cycle_manager.config.cycle.auto_apply_defaults_after_minutes
            ),
            name=auto_job_name,
            chat_id=chat_id,
            data={"date": today.isoformat()},
        )
        self.cycle_manager.mark_pending_default(target_date=today, job_name=auto_job_name)

    async def auto_apply_defaults_job(
        self, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        job = context.job
        if job is None or not job.data:
            return
        target_date = date.fromisoformat(job.data["date"])
        cycle = self.cycle_manager.get_cycle()
        if not cycle or cycle.pending_default_date != target_date:
            return
        record = cycle.records.get(target_date.isoformat()) if cycle.records else None
        default_amount = cycle.default_totals_by_date.get(target_date.isoformat(), 0)
        if record and record.defaults_applied >= default_amount:
            return
        self.cycle_manager.apply_daily_defaults(
            target_date=target_date, auto_closed=True, note="Auto closed"
        )
        await context.bot.send_message(
            chat_id=job.chat_id,
            text=(
                "Check-in window expired. Default spends applied with zero extras."
            ),
        )

    async def _schedule_checkin_job(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        chat = update.effective_chat
        if chat is None:
            return
        job_queue = context.job_queue
        if job_queue is None:
            return
        self._cancel_job(job_queue, CHECKIN_JOB_NAME)
        job_queue.run_daily(
            self.daily_checkin_job,
            time=parse_checkin_time(self.cycle_manager.config),
            name=CHECKIN_JOB_NAME,
            chat_id=chat.id,
        )

    def _cancel_job(self, job_queue: Optional[JobQueue], name: str) -> None:
        if job_queue is None:
            return
        jobs = job_queue.get_jobs_by_name(name)
        for job in jobs:
            job.schedule_removal()

    def reschedule_jobs(self, application: Application) -> None:
        state = self.cycle_manager.load_state()
        if not state.cycle or state.user_id is None:
            return
        job_queue = application.job_queue
        self._cancel_job(job_queue, CHECKIN_JOB_NAME)
        if job_queue is None:
            return
        job_queue.run_daily(
            self.daily_checkin_job,
            time=parse_checkin_time(self.cycle_manager.config),
            name=CHECKIN_JOB_NAME,
            chat_id=state.user_id,
        )


def register_handlers(application: Application, handlers: BotHandlers) -> None:
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("status", handlers.status))
    application.add_handler(CommandHandler("start_cycle", handlers.start_cycle))
    application.add_handler(CommandHandler("set_balance", handlers.set_balance))
    application.add_handler(CommandHandler("log_extra", handlers.log_extra))
    application.add_handler(CommandHandler("daily_confirm", handlers.daily_confirm))

    defaults_conversation = ConversationHandler(
        entry_points=[CommandHandler("set_defaults", handlers.set_defaults_entry)],
        states={
            SET_DEFAULTS_WAIT: [
                MessageHandler(
                    filters.TEXT & (~filters.COMMAND), handlers.set_defaults_update
                )
            ]
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel_defaults)],
    )
    application.add_handler(defaults_conversation)

    application.add_error_handler(_error_handler)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.error:
        print("Handler error:", context.error)
    if update is None:
        return
    message = "An error occurred. Please try again."
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(message)