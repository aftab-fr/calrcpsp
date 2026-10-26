"""Calendar edge cases: boundaries, overnight shifts, holidays and long gaps.

These tests cover the cases where calendar arithmetic is easiest to get wrong:
an instant that falls exactly on a shift boundary, a run of consecutive
non-working days, a holiday that lands inside a shift which already crossed
midnight, and a task long enough to span several days or a whole week.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from calrcpsp import ShiftSpec, WorkCalendar

pytestmark = pytest.mark.unit

MONDAY = datetime(2025, 1, 6, 0, 0)


@pytest.fixture
def day():
    return WorkCalendar.standard_day()


@pytest.fixture
def ref(day):
    return day.next_working_time(MONDAY)


# -- exact boundary instants ---------------------------------------------

@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2025, 1, 6, 8, 0), 0.0),      # the reference itself
        (datetime(2025, 1, 6, 11, 59), 3.9833),  # just before the break
        (datetime(2025, 1, 6, 12, 0), 4.0),     # the instant the break opens
        (datetime(2025, 1, 6, 12, 59), 4.0),    # inside the break
        (datetime(2025, 1, 6, 13, 0), 4.0),     # the instant the break closes
        (datetime(2025, 1, 6, 17, 0), 8.0),     # the instant the shift closes
        (datetime(2025, 1, 7, 0, 0), 8.0),      # midnight, nothing added
        (datetime(2025, 1, 7, 8, 0), 8.0),      # the next shift has not run yet
    ],
)
def test_W_on_exact_boundary_instants(day, ref, moment, expected):
    assert day.W(moment, ref) == pytest.approx(expected, abs=1e-3)


def test_W_inverse_at_a_shift_end_returns_the_earliest_such_moment(day, ref):
    """Eight work-hours are complete at 17:00, not at 08:00 the next day."""
    assert day.W_inverse(8.0, ref) == datetime(2025, 1, 6, 17, 0)


def test_W_inverse_just_past_a_shift_end_crosses_to_the_next_day(day, ref):
    moment = day.W_inverse(8.01, ref)
    assert moment.date() == date(2025, 1, 7)
    assert moment.hour == 8


def test_zero_work_from_a_non_working_reference_moves_to_the_next_opening(day):
    """A reference inside the weekend yields the next working instant."""
    saturday = datetime(2025, 1, 11, 10, 0)
    assert day.W_inverse(0.0, saturday) == datetime(2025, 1, 13, 8, 0)


# -- consecutive non-working days ----------------------------------------

def test_weekend_plus_a_monday_holiday_is_three_days_off():
    calendar = WorkCalendar.standard_day(holidays=[date(2025, 1, 13)])
    ref = calendar.next_working_time(MONDAY)
    assert calendar.W_inverse(40.0, ref) == datetime(2025, 1, 10, 17, 0)
    assert calendar.W_inverse(40.5, ref) == datetime(2025, 1, 14, 8, 30)


def test_friday_holiday_plus_weekend_is_four_days_off():
    calendar = WorkCalendar.standard_day(holidays=[date(2025, 1, 10)])
    ref = calendar.next_working_time(MONDAY)
    assert calendar.W_inverse(32.0, ref) == datetime(2025, 1, 9, 17, 0)
    assert calendar.W_inverse(32.5, ref) == datetime(2025, 1, 13, 8, 30)


def test_a_block_of_holidays_spanning_a_week():
    calendar = WorkCalendar.standard_day(
        holidays=[date(2025, 12, 24), date(2025, 12, 25), date(2025, 12, 26)]
    )
    start = datetime(2025, 12, 22, 0, 0)          # Monday
    ref = calendar.next_working_time(start)
    assert calendar.W_inverse(16.0, ref) == datetime(2025, 12, 23, 17, 0)
    # Wed to Fri are holidays and the weekend follows: seven days with no work.
    assert calendar.W_inverse(16.5, ref) == datetime(2025, 12, 29, 8, 30)


def test_next_working_time_steps_over_a_long_closure():
    calendar = WorkCalendar.standard_day(
        holidays=[date(2025, 7, 14) + timedelta(days=k) for k in range(10)]
    )
    assert calendar.next_working_time(datetime(2025, 7, 14, 9, 0)) == datetime(2025, 7, 24, 8, 0)


# -- overnight shifts meeting holidays -----------------------------------

@pytest.fixture
def night():
    return WorkCalendar(shifts=[ShiftSpec("night", "22:00", "06:00", tuple(range(7)))])


def test_overnight_shift_is_cut_by_a_holiday_on_the_following_date(night):
    """A Friday night shift keeps only its Friday part when Saturday is off."""
    plain = night.daily_work_hours(date(2025, 1, 10))
    assert plain == pytest.approx(8.0)
    cut = WorkCalendar(
        shifts=[ShiftSpec("night", "22:00", "06:00", tuple(range(7)))],
        holidays=[date(2025, 1, 11)],
    )
    assert cut.daily_work_hours(date(2025, 1, 10)) == pytest.approx(2.0)


def test_overnight_shift_removed_entirely_when_its_start_date_is_a_holiday():
    cut = WorkCalendar(
        shifts=[ShiftSpec("night", "22:00", "06:00", tuple(range(7)))],
        holidays=[date(2025, 1, 10), date(2025, 1, 11)],
    )
    assert cut.daily_work_hours(date(2025, 1, 10)) == pytest.approx(0.0)


def test_two_shift_day_with_an_evening_that_crosses_midnight():
    calendar = WorkCalendar(
        shifts=[
            ShiftSpec("day", "08:00", "17:00", (0, 1, 2, 3, 4)),
            ShiftSpec("evening", "17:00", "01:00", (0, 1, 2, 3, 4)),
        ],
        lunch_break=("12:00", "13:00"),
    )
    ref = calendar.next_working_time(MONDAY)
    assert calendar.daily_work_hours(date(2025, 1, 6)) == pytest.approx(16.0)
    assert calendar.W_inverse(16.0, ref) == datetime(2025, 1, 7, 1, 0)
    # The Friday evening shift runs into Saturday, then work stops until Monday.
    assert calendar.W_inverse(80.0, ref) == datetime(2025, 1, 11, 1, 0)
    assert calendar.W_inverse(80.5, ref) == datetime(2025, 1, 13, 8, 30)


def test_continuous_calendar_loses_exactly_one_day_to_a_holiday():
    calendar = WorkCalendar.continuous(holidays=[date(2025, 5, 1)])
    ref = datetime(2025, 4, 30, 0, 0)
    assert calendar.W(datetime(2025, 5, 2, 0, 0), ref) == pytest.approx(24.0)


# -- work spanning several days or weeks ---------------------------------

def test_a_task_longer_than_one_working_day_splits_into_daily_pieces(day, ref):
    start = datetime(2025, 1, 6, 8, 0)
    end = day.add_work_time(start, 20.0, ref)
    assert end == datetime(2025, 1, 8, 12, 0)
    pieces = day.occupied_intervals(start, end, ref)
    assert len(pieces) == 5                      # two per full day, one on the third
    total = sum((b - a).total_seconds() / 3600.0 for a, b in pieces)
    assert total == pytest.approx(20.0)
    for begin, finish in pieces:
        assert day.is_working_time(begin)
        assert day.is_working_time(finish - timedelta(seconds=1))


def test_a_task_longer_than_a_working_week_crosses_the_weekend(day, ref):
    start = datetime(2025, 1, 6, 8, 0)
    end = day.add_work_time(start, 50.0, ref)
    assert end == datetime(2025, 1, 14, 10, 0)   # Tuesday of the following week
    pieces = day.occupied_intervals(start, end, ref)
    total = sum((b - a).total_seconds() / 3600.0 for a, b in pieces)
    assert total == pytest.approx(50.0)
    # No piece may fall on the Saturday or the Sunday.
    assert not any(a.weekday() >= 5 for a, _ in pieces)


def test_work_spanning_a_holiday_skips_it_but_keeps_the_total(day):
    calendar = WorkCalendar.standard_day(holidays=[date(2025, 1, 8)])
    ref = calendar.next_working_time(MONDAY)
    start = datetime(2025, 1, 6, 8, 0)
    end = calendar.add_work_time(start, 20.0, ref)
    assert end == datetime(2025, 1, 9, 12, 0)    # Wednesday skipped
    pieces = calendar.occupied_intervals(start, end, ref)
    total = sum((b - a).total_seconds() / 3600.0 for a, b in pieces)
    assert total == pytest.approx(20.0)
    assert not any(a.date() == date(2025, 1, 8) for a, _ in pieces)


# -- break placement -----------------------------------------------------

def test_a_break_at_the_start_of_a_shift_shortens_the_day():
    calendar = WorkCalendar(
        shifts=[ShiftSpec("day", "08:00", "17:00", (0, 1, 2, 3, 4))],
        lunch_break=("08:00", "09:00"),
    )
    assert calendar.daily_work_hours(date(2025, 1, 6)) == pytest.approx(8.0)
    assert calendar.next_working_time(MONDAY) == datetime(2025, 1, 6, 9, 0)


def test_a_calendar_with_no_break_keeps_the_whole_shift():
    calendar = WorkCalendar(shifts=[ShiftSpec("day", "08:00", "17:00", (0, 1, 2, 3, 4))])
    assert calendar.daily_work_hours(date(2025, 1, 6)) == pytest.approx(9.0)
