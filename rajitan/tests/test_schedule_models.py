"""Tests for rajitan.scheduler.schedule_models module."""

import pytest
from datetime import datetime, timedelta
from rajitan.scheduler.schedule_models import (
    ExecutionTime,
    ExecutionPattern,
    ScheduleInfo,
    ScheduleSummary,
    ScheduleType,
    FunctionType,
    FunctionConfig,
)


# ---------------------------------------------------------------------------
# ExecutionTime creation
# ---------------------------------------------------------------------------

class TestExecutionTimeCreation:
    def test_hourly_pattern(self):
        et = ExecutionTime(pattern=ExecutionPattern.HOURLY, minute=30)
        assert et.pattern == ExecutionPattern.HOURLY
        assert et.minute == 30

    def test_daily_pattern(self):
        et = ExecutionTime(pattern=ExecutionPattern.DAILY, hour=19, minute=0)
        assert et.pattern == ExecutionPattern.DAILY
        assert et.hour == 19

    def test_weekly_pattern(self):
        et = ExecutionTime(pattern=ExecutionPattern.WEEKLY, hour=10, minute=0, day_of_week=0)
        assert et.pattern == ExecutionPattern.WEEKLY
        assert et.day_of_week == 0  # Monday

    def test_monthly_pattern(self):
        et = ExecutionTime(pattern=ExecutionPattern.MONTHLY, hour=9, minute=0, day_of_month=15)
        assert et.pattern == ExecutionPattern.MONTHLY
        assert et.day_of_month == 15

    def test_once_pattern_with_specific_datetime(self):
        target = datetime(2026, 6, 1, 12, 0)
        et = ExecutionTime(pattern=ExecutionPattern.ONCE, specific_datetime=target)
        assert et.pattern == ExecutionPattern.ONCE
        assert et.specific_datetime == target


# ---------------------------------------------------------------------------
# ExecutionTime.to_next_execution_time (calculate_next_execution)
# ---------------------------------------------------------------------------

class TestExecutionTimeCalculation:
    def test_hourly_next_execution(self):
        et = ExecutionTime(pattern=ExecutionPattern.HOURLY, minute=0)
        base = datetime(2026, 2, 8, 14, 30, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time is not None
        assert next_time == datetime(2026, 2, 8, 15, 0, 0)

    def test_daily_next_execution_same_day(self):
        et = ExecutionTime(pattern=ExecutionPattern.DAILY, hour=19, minute=0)
        base = datetime(2026, 2, 8, 10, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time == datetime(2026, 2, 8, 19, 0, 0)

    def test_daily_next_execution_next_day(self):
        et = ExecutionTime(pattern=ExecutionPattern.DAILY, hour=8, minute=0)
        base = datetime(2026, 2, 8, 10, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time == datetime(2026, 2, 9, 8, 0, 0)

    def test_weekly_next_execution(self):
        et = ExecutionTime(pattern=ExecutionPattern.WEEKLY, hour=10, minute=0, day_of_week=2)  # Wednesday
        # 2026-02-08 is a Sunday (weekday=6)
        base = datetime(2026, 2, 8, 12, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time is not None
        assert next_time.weekday() == 2  # Wednesday

    def test_monthly_next_execution(self):
        et = ExecutionTime(pattern=ExecutionPattern.MONTHLY, hour=9, minute=0, day_of_month=15)
        base = datetime(2026, 2, 8, 12, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time == datetime(2026, 2, 15, 9, 0, 0)

    def test_once_future_datetime_returns_it(self):
        future = datetime(2026, 12, 31, 23, 59)
        et = ExecutionTime(pattern=ExecutionPattern.ONCE, specific_datetime=future)
        base = datetime(2026, 2, 8, 12, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time == future

    def test_once_past_datetime_returns_none(self):
        past = datetime(2020, 1, 1, 0, 0)
        et = ExecutionTime(pattern=ExecutionPattern.ONCE, specific_datetime=past)
        base = datetime(2026, 2, 8, 12, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time is None

    def test_once_with_relative_minutes(self):
        et = ExecutionTime(pattern=ExecutionPattern.ONCE, relative_minutes=30)
        base = datetime(2026, 2, 8, 12, 0, 0)
        next_time = et.to_next_execution_time(base)
        assert next_time == base + timedelta(minutes=30)


# ---------------------------------------------------------------------------
# ScheduleInfo.should_execute
# ---------------------------------------------------------------------------

class TestScheduleInfoShouldExecute:
    def _make_schedule_info(self, **kwargs):
        defaults = dict(
            channel_id="chan_001",
            guild_id="guild_001",
            schedule_type=ScheduleType.PERIODIC,
            execution_time=ExecutionTime(pattern=ExecutionPattern.DAILY, hour=19, minute=0),
            function_config=FunctionConfig(function_type=FunctionType.SUMMARY),
            is_active=True,
            created_by="user_001",
        )
        defaults.update(kwargs)
        return ScheduleInfo(**defaults)

    def test_should_execute_when_past_next_execution(self):
        si = self._make_schedule_info()
        past = datetime(2026, 2, 7, 19, 0, 0)
        si.next_execution = past
        current = datetime(2026, 2, 8, 20, 0, 0)
        assert si.should_execute(current) is True

    def test_should_not_execute_when_inactive(self):
        si = self._make_schedule_info(is_active=False)
        current = datetime(2026, 2, 8, 20, 0, 0)
        assert si.should_execute(current) is False

    def test_should_not_execute_before_next_execution(self):
        si = self._make_schedule_info()
        future = datetime(2026, 12, 31, 23, 59, 0)
        si.next_execution = future
        current = datetime(2026, 2, 8, 12, 0, 0)
        assert si.should_execute(current) is False


# ---------------------------------------------------------------------------
# ScheduleInfo.mark_executed
# ---------------------------------------------------------------------------

class TestScheduleInfoMarkExecuted:
    def _make_schedule_info(self, **kwargs):
        defaults = dict(
            channel_id="chan_001",
            guild_id="guild_001",
            schedule_type=ScheduleType.PERIODIC,
            execution_time=ExecutionTime(pattern=ExecutionPattern.DAILY, hour=19, minute=0),
            function_config=FunctionConfig(function_type=FunctionType.SUMMARY),
            is_active=True,
            created_by="user_001",
        )
        defaults.update(kwargs)
        return ScheduleInfo(**defaults)

    def test_mark_executed_updates_last_executed(self):
        si = self._make_schedule_info()
        exec_time = datetime(2026, 2, 8, 19, 0, 0)
        si.mark_executed(exec_time, success=True)
        assert si.last_executed == exec_time

    def test_mark_executed_increments_execution_count(self):
        si = self._make_schedule_info()
        assert si.execution_count == 0
        si.mark_executed(datetime.now(), success=True)
        assert si.execution_count == 1
        si.mark_executed(datetime.now(), success=True)
        assert si.execution_count == 2

    def test_mark_executed_resets_failures_on_success(self):
        si = self._make_schedule_info()
        si.consecutive_failures = 2
        si.mark_executed(datetime.now(), success=True)
        assert si.consecutive_failures == 0

    def test_mark_executed_increments_failures_on_failure(self):
        si = self._make_schedule_info()
        si.mark_executed(datetime.now(), success=False)
        assert si.consecutive_failures == 1

    def test_mark_executed_disables_after_max_failures(self):
        si = self._make_schedule_info()
        si.max_failures = 3
        for _ in range(3):
            si.mark_executed(datetime.now(), success=False)
        assert si.is_active is False

    def test_one_time_schedule_disables_after_execution(self):
        si = self._make_schedule_info(
            schedule_type=ScheduleType.ONE_TIME,
            execution_time=ExecutionTime(
                pattern=ExecutionPattern.ONCE,
                specific_datetime=datetime(2026, 12, 31, 23, 59),
            ),
        )
        si.mark_executed(datetime.now(), success=True)
        assert si.is_active is False


# ---------------------------------------------------------------------------
# ScheduleSummary.from_schedule_info
# ---------------------------------------------------------------------------

class TestScheduleSummary:
    def test_from_schedule_info_correct_conversion(self):
        now = datetime.now()
        si = ScheduleInfo(
            id=42,
            channel_id="chan_010",
            guild_id="guild_010",
            schedule_type=ScheduleType.PERIODIC,
            execution_time=ExecutionTime(pattern=ExecutionPattern.DAILY, hour=19, minute=0),
            function_config=FunctionConfig(function_type=FunctionType.MUSIC),
            is_active=True,
            created_by="user_010",
            created_at=now,
            last_executed=None,
            next_execution=None,
            execution_count=5,
            consecutive_failures=1,
        )

        summary = ScheduleSummary.from_schedule_info(si)
        assert summary.id == 42
        assert summary.channel_id == "chan_010"
        assert summary.guild_id == "guild_010"
        assert summary.function_type == FunctionType.MUSIC
        assert summary.pattern == ExecutionPattern.DAILY
        assert summary.is_active is True
        assert summary.execution_count == 5
        assert summary.consecutive_failures == 1
        assert summary.created_by == "user_010"
        assert summary.created_at == now

    def test_from_schedule_info_without_id_defaults_to_zero(self):
        si = ScheduleInfo(
            channel_id="chan_011",
            guild_id="guild_011",
            schedule_type=ScheduleType.ONE_TIME,
            execution_time=ExecutionTime(
                pattern=ExecutionPattern.ONCE,
                specific_datetime=datetime(2026, 6, 1, 12, 0),
            ),
            function_config=FunctionConfig(function_type=FunctionType.QUIZ),
            created_by="user_011",
        )
        summary = ScheduleSummary.from_schedule_info(si)
        assert summary.id == 0
