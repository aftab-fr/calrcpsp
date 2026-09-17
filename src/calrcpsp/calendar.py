"""Work calendars and the cumulative work-time transformation.

A work calendar splits calendar time into working and non-working periods.
Two functions do the real work:

``W(t)``
    cumulative work-hours elapsed between a reference moment and ``t``.

``W_inverse(w)``
    the earliest calendar moment at which ``w`` work-hours have elapsed.

Both are exact.  The calendar is represented as a piecewise linear
breakpoint table built once per reference moment and extended on demand,
so both functions cost a binary search rather than a scan over the
horizon.  There is no time quantisation: a shift boundary at 08:00 is
08:00, and a task of 0.37 work-hours takes 0.37 work-hours.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .instance import CalendarSpec, ShiftSpec

__all__ = ["WorkCalendar", "DEFAULT_PROJECT_START"]

#: Monday 00:00.  Schedules start at the first working moment at or after this.
DEFAULT_PROJECT_START = datetime(2025, 1, 6, 0, 0)

_CHUNK_DAYS = 120
_MAX_HORIZON_DAYS = 20_000


def _parse_time(value: str) -> time:
    text = value.strip()
    if text in ("24:00", "2400"):
        return time(0, 0)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"cannot parse time of day {value!r}")


def _merge(intervals: Sequence[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping or touching intervals."""
    out: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def _subtract(
    intervals: Sequence[tuple[datetime, datetime]],
    holes: Sequence[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Remove every hole from every interval."""
    holes = _merge(holes)
    out: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        pieces = [(start, end)]
        for h_start, h_end in holes:
            if h_end <= start or h_start >= end:
                continue
            nxt: list[tuple[datetime, datetime]] = []
            for p_start, p_end in pieces:
                if h_end <= p_start or h_start >= p_end:
                    nxt.append((p_start, p_end))
                    continue
                if p_start < h_start:
                    nxt.append((p_start, h_start))
                if h_end < p_end:
                    nxt.append((h_end, p_end))
            pieces = nxt
        out.extend(p for p in pieces if p[1] > p[0])
    return out


@dataclass
class _Table:
    """Piecewise linear breakpoint table anchored at one reference moment."""

    times: list[datetime]
    work: list[float]
    next_date: date
    exhausted: bool = False


class WorkCalendar:
    """A work calendar built from shifts, an optional break and holidays.

    Shifts may run past midnight: an end time at or before the start time
    means the shift finishes on the following calendar day.  Holidays
    remove whole calendar dates.  The break, where present, is removed from
    every date it touches.
    """

    def __init__(
        self,
        shifts: Iterable[ShiftSpec],
        lunch_break: tuple[str, str] | None = None,
        holidays: Iterable[date] = (),
        name: str = "custom",
    ) -> None:
        self.name = name
        self.shifts = tuple(shifts)
        if not self.shifts:
            raise ValueError("a work calendar needs at least one shift")
        self._shift_times = tuple(
            (_parse_time(s.start), _parse_time(s.end), frozenset(s.days)) for s in self.shifts
        )
        self.lunch_break = lunch_break
        self._lunch_times = (
            (_parse_time(lunch_break[0]), _parse_time(lunch_break[1])) if lunch_break else None
        )
        self.holidays = frozenset(holidays)
        self._tables: dict[datetime, _Table] = {}

    # -- construction ----------------------------------------------------

    @classmethod
    def from_spec(cls, spec: CalendarSpec) -> WorkCalendar:
        """Build a calendar from an instance's ``calendar_requirements``."""
        return cls(
            shifts=spec.shifts,
            lunch_break=spec.lunch_break,
            holidays=spec.holidays,
            name=spec.shift_type,
        )

    @classmethod
    def standard_day(cls, holidays: Iterable[date] = ()) -> WorkCalendar:
        """08:00 to 17:00 Monday to Friday with a 12:00 to 13:00 break."""
        return cls(
            shifts=[ShiftSpec("day", "08:00", "17:00", (0, 1, 2, 3, 4))],
            lunch_break=("12:00", "13:00"),
            holidays=holidays,
            name="standard_day",
        )

    @classmethod
    def continuous(cls, holidays: Iterable[date] = ()) -> WorkCalendar:
        """Round the clock, every day, apart from holidays."""
        return cls(
            shifts=[ShiftSpec("all", "00:00", "24:00", (0, 1, 2, 3, 4, 5, 6))],
            lunch_break=None,
            holidays=holidays,
            name="continuous",
        )

    # -- raw windows -----------------------------------------------------

    def _windows_starting_between(self, first: date, last: date) -> list[tuple[datetime, datetime]]:
        """Working intervals for shifts starting on a date in ``[first, last)``."""
        raw: list[tuple[datetime, datetime]] = []
        day = first
        while day < last:
            weekday = day.weekday()
            for start_t, end_t, days in self._shift_times:
                if weekday not in days:
                    continue
                start = datetime.combine(day, start_t)
                end = datetime.combine(day, end_t)
                if end <= start:
                    end += timedelta(days=1)
                raw.append((start, end))
            day += timedelta(days=1)

        merged = _merge(raw)
        if not merged:
            return []

        holes: list[tuple[datetime, datetime]] = []
        span_start = merged[0][0].date()
        span_end = merged[-1][1].date()
        day = span_start
        while day <= span_end:
            if day in self.holidays:
                holes.append((datetime.combine(day, time(0, 0)),
                              datetime.combine(day + timedelta(days=1), time(0, 0))))
            if self._lunch_times is not None:
                l_start, l_end = self._lunch_times
                start = datetime.combine(day, l_start)
                end = datetime.combine(day, l_end)
                if end <= start:
                    end += timedelta(days=1)
                holes.append((start, end))
            day += timedelta(days=1)

        return sorted(_subtract(merged, holes))

    # -- point queries ---------------------------------------------------

    def is_working_time(self, moment: datetime) -> bool:
        """True when ``moment`` falls inside a working period."""
        day = moment.date()
        windows = self._windows_starting_between(day - timedelta(days=1), day + timedelta(days=1))
        return any(start <= moment < end for start, end in windows)

    def next_working_time(self, moment: datetime) -> datetime:
        """``moment`` itself when it is working time, otherwise the next start."""
        day = moment.date()
        for _ in range(_MAX_HORIZON_DAYS // _CHUNK_DAYS):
            windows = self._windows_starting_between(day - timedelta(days=1),
                                                     day + timedelta(days=_CHUNK_DAYS))
            for start, end in windows:
                if start <= moment < end:
                    return moment
                if start > moment:
                    return start
            day += timedelta(days=_CHUNK_DAYS)
        raise RuntimeError("no working time found within the search horizon")

    # -- breakpoint table ------------------------------------------------

    def _table(self, reference: datetime) -> _Table:
        table = self._tables.get(reference)
        if table is None:
            # Start one day early so that a shift which began on the
            # previous date and runs past midnight is not lost.
            table = _Table(times=[], work=[],
                           next_date=reference.date() - timedelta(days=1))
            self._tables[reference] = table
            self._extend(table, reference)
        return table

    def _extend(self, table: _Table, reference: datetime) -> None:
        """Append one more chunk of working intervals to the table."""
        if table.exhausted:
            return
        if (table.next_date - reference.date()).days > _MAX_HORIZON_DAYS:
            table.exhausted = True
            return

        first = table.next_date
        last = first + timedelta(days=_CHUNK_DAYS)
        table.next_date = last

        accumulated = table.work[-1] if table.work else 0.0
        for start, end in self._windows_starting_between(first, last):
            if end <= reference:
                continue
            if start < reference:
                start = reference
            if end <= start:
                continue
            if table.times and start <= table.times[-1]:
                # Continues the previous interval: stretch it instead of
                # opening a new one.
                grown = (end - table.times[-1]).total_seconds() / 3600.0
                if grown <= 0:
                    continue
                table.times[-1] = end
                accumulated += grown
                table.work[-1] = accumulated
                continue
            if not table.times:
                table.times.append(start)
                table.work.append(0.0)
            else:
                table.times.append(start)
                table.work.append(accumulated)
            accumulated += (end - start).total_seconds() / 3600.0
            table.times.append(end)
            table.work.append(accumulated)

    def _ensure_work(self, reference: datetime, target: float) -> _Table:
        table = self._table(reference)
        while not table.exhausted and (not table.work or table.work[-1] < target):
            self._extend(table, reference)
        return table

    def _ensure_time(self, reference: datetime, target: datetime) -> _Table:
        table = self._table(reference)
        while not table.exhausted and (not table.times or table.times[-1] < target):
            self._extend(table, reference)
        return table

    # -- W and its inverse -----------------------------------------------

    def W(self, moment: datetime, reference: datetime) -> float:
        """Work-hours elapsed between ``reference`` and ``moment``."""
        if moment <= reference:
            return 0.0
        table = self._ensure_time(reference, moment)
        if not table.times or moment <= table.times[0]:
            return 0.0
        idx = bisect_right(table.times, moment) - 1
        if idx >= len(table.times) - 1:
            return table.work[-1]
        w_lo, w_hi = table.work[idx], table.work[idx + 1]
        if w_hi <= w_lo:
            return w_lo
        elapsed = (moment - table.times[idx]).total_seconds() / 3600.0
        return w_lo + min(elapsed, w_hi - w_lo)

    def W_inverse(self, work_hours: float, reference: datetime) -> datetime:
        """Earliest moment at which ``work_hours`` have elapsed since ``reference``."""
        if work_hours <= 0:
            return self.next_working_time(reference)
        table = self._ensure_work(reference, work_hours)
        if not table.times:
            raise RuntimeError("calendar has no working time after the reference moment")
        if work_hours > table.work[-1]:
            raise ValueError(
                f"{work_hours:.3f} work-hours exceed the {table.work[-1]:.3f} hours "
                f"available within the search horizon"
            )
        idx = bisect_left(table.work, work_hours)
        if idx == 0:
            return table.times[0]
        w_lo, w_hi = table.work[idx - 1], table.work[idx]
        if w_hi <= w_lo:
            return table.times[idx - 1]
        fraction = (work_hours - w_lo) / (w_hi - w_lo)
        span = (table.times[idx] - table.times[idx - 1]).total_seconds()
        return table.times[idx - 1] + timedelta(seconds=fraction * span)

    # -- convenience -----------------------------------------------------

    def work_hours_between(self, start: datetime, end: datetime) -> float:
        """Work-hours between two calendar moments."""
        return self.W(end, start)

    def add_work_time(self, start: datetime, work_hours: float,
                      reference: datetime | None = None) -> datetime:
        """Calendar moment reached after ``work_hours`` of work from ``start``."""
        reference = reference if reference is not None else start
        return self.W_inverse(self.W(start, reference) + work_hours, reference)

    def occupied_intervals(
        self, start: datetime, end: datetime, reference: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Working periods actually occupied between ``start`` and ``end``.

        A task that spans a break, a night or a weekend produces several
        intervals.  Every returned interval lies inside working time.
        """
        if end <= start:
            return []
        table = self._ensure_time(reference, end)
        out: list[tuple[datetime, datetime]] = []
        lo = max(bisect_right(table.times, start) - 1, 0)
        for idx in range(lo, len(table.times) - 1):
            seg_start, seg_end = table.times[idx], table.times[idx + 1]
            if seg_start >= end:
                break
            if table.work[idx + 1] <= table.work[idx]:
                continue  # non-working gap
            piece_start = max(seg_start, start)
            piece_end = min(seg_end, end)
            if piece_end > piece_start:
                out.append((piece_start, piece_end))
        return out

    def daily_work_hours(self, day: date) -> float:
        """Total working hours contributed by shifts starting on ``day``."""
        windows = self._windows_starting_between(day, day + timedelta(days=1))
        return sum((e - s).total_seconds() / 3600.0 for s, e in windows)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"WorkCalendar(name={self.name!r}, shifts={len(self.shifts)}, "
            f"lunch_break={self.lunch_break!r}, holidays={len(self.holidays)})"
        )
