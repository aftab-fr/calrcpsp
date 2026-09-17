"""The cumulative work-time function and its inverse."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from calrcpsp import ShiftSpec, WorkCalendar, load_instance


@pytest.fixture
def day():
    return WorkCalendar.standard_day()


@pytest.fixture
def ref(day):
    return day.next_working_time(datetime(2025, 1, 6, 0, 0))


def test_reference_lands_on_the_first_working_moment(day, ref):
    assert ref == datetime(2025, 1, 6, 8, 0)
    assert day.is_working_time(ref)


def test_standard_day_is_eight_hours(day):
    assert day.daily_work_hours(date(2025, 1, 6)) == 8.0
    assert day.daily_work_hours(date(2025, 1, 11)) == 0.0  # Saturday


def test_lunch_break_is_not_working_time(day):
    assert day.is_working_time(datetime(2025, 1, 6, 11, 59))
    assert not day.is_working_time(datetime(2025, 1, 6, 12, 30))
    assert day.is_working_time(datetime(2025, 1, 6, 13, 1))


def test_night_and_weekend_are_not_working_time(day):
    assert not day.is_working_time(datetime(2025, 1, 6, 3, 0))
    assert not day.is_working_time(datetime(2025, 1, 11, 10, 0))


def test_W_skips_the_break(day, ref):
    assert day.W(datetime(2025, 1, 6, 12, 0), ref) == pytest.approx(4.0)
    assert day.W(datetime(2025, 1, 6, 13, 0), ref) == pytest.approx(4.0)
    assert day.W(datetime(2025, 1, 6, 17, 0), ref) == pytest.approx(8.0)
    assert day.W(datetime(2025, 1, 7, 8, 0), ref) == pytest.approx(8.0)


@pytest.mark.parametrize("hours", [0.25, 1.0, 3.99, 4.0, 4.01, 8.0, 12.5, 40.0, 137.75])
def test_W_inverse_round_trips(day, ref, hours):
    moment = day.W_inverse(hours, ref)
    assert day.W(moment, ref) == pytest.approx(hours, abs=1e-6)


def test_W_inverse_is_monotonic(day, ref):
    previous = ref
    for hours in [0.5 * k for k in range(1, 120)]:
        moment = day.W_inverse(hours, ref)
        assert moment >= previous
        previous = moment


def test_holidays_remove_a_whole_day():
    holiday = date(2025, 1, 8)
    calendar = WorkCalendar.standard_day(holidays=[holiday])
    ref = calendar.next_working_time(datetime(2025, 1, 6, 0, 0))
    assert calendar.daily_work_hours(holiday) == 0.0
    # 16 work-hours finish on Tuesday; the next hour must skip Wednesday.
    assert calendar.W_inverse(16.0, ref) == datetime(2025, 1, 7, 17, 0)
    assert calendar.W_inverse(16.5, ref) == datetime(2025, 1, 9, 8, 30)


def test_shift_crossing_midnight():
    calendar = WorkCalendar(
        shifts=[
            ShiftSpec("day", "08:00", "17:00", (0, 1, 2, 3, 4)),
            ShiftSpec("evening", "17:00", "01:00", (0, 1, 2, 3, 4)),
        ],
        lunch_break=("12:00", "13:00"),
    )
    ref = calendar.next_working_time(datetime(2025, 1, 6, 0, 0))
    assert calendar.daily_work_hours(date(2025, 1, 6)) == 16.0
    assert calendar.W_inverse(16.0, ref) == datetime(2025, 1, 7, 1, 0)
    assert calendar.W_inverse(17.0, ref) == datetime(2025, 1, 7, 9, 0)


def test_continuous_calendar_counts_every_hour():
    calendar = WorkCalendar.continuous()
    ref = datetime(2025, 1, 6, 0, 0)
    assert calendar.W(datetime(2025, 1, 13, 0, 0), ref) == pytest.approx(168.0)
    assert calendar.W_inverse(48.0, ref) == datetime(2025, 1, 8, 0, 0)


def test_night_shift_from_the_previous_day_is_counted():
    """A shift beginning before the reference must still be visible."""
    calendar = WorkCalendar(
        shifts=[ShiftSpec("night", "22:00", "06:00", (0, 1, 2, 3, 4, 5, 6))],
    )
    ref = datetime(2025, 1, 6, 0, 0)  # inside the shift that began on Sunday
    assert calendar.is_working_time(ref)
    assert calendar.W_inverse(1.0, ref) == datetime(2025, 1, 6, 1, 0)


def test_occupied_intervals_split_across_the_break(day, ref):
    start = datetime(2025, 1, 6, 11, 0)
    end = day.add_work_time(start, 3.0, ref)
    intervals = day.occupied_intervals(start, end, ref)
    assert len(intervals) == 2
    total = sum((b - a).total_seconds() / 3600.0 for a, b in intervals)
    assert total == pytest.approx(3.0)
    for begin, finish in intervals:
        assert day.is_working_time(begin + (finish - begin) / 2)


def test_occupied_intervals_lie_inside_working_time(day, ref):
    start = datetime(2025, 1, 10, 15, 0)  # Friday afternoon
    end = day.add_work_time(start, 10.0, ref)
    for begin, finish in day.occupied_intervals(start, end, ref):
        assert day.is_working_time(begin)
        assert day.is_working_time(finish - timedelta(seconds=1))


def test_calendar_built_from_instance(instance_path):
    instance = load_instance(instance_path)
    calendar = WorkCalendar.from_spec(instance.calendar)
    ref = calendar.next_working_time(datetime(2025, 1, 6, 0, 0))
    assert calendar.W(calendar.W_inverse(12.0, ref), ref) == pytest.approx(12.0, abs=1e-6)


def test_work_beyond_horizon_raises(day, ref):
    with pytest.raises(ValueError, match="exceed"):
        day.W_inverse(10_000_000.0, ref)
