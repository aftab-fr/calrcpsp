"""Putting the pieces together into a schedule.

Every step here is also available on its own, so a user who only wants the
matrices, or only the calendar mapping, does not have to call
:func:`solve`.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np

from .assignment import Assignment, assign_resources
from .calendar import DEFAULT_PROJECT_START, WorkCalendar
from .instance import Instance
from .maxplus import (
    build_precedence_matrix,
    build_resource_matrix,
    combine_matrices,
    closure,
    earliest_start_times,
    latest_start_times,
    topological_order,
)
from .schedule import Schedule, TaskSchedule

__all__ = ["solve", "to_calendar_schedule"]

_CRITICAL_TOL = 1e-9


def _starts_from_closure(matrix: np.ndarray) -> np.ndarray:
    """Earliest starts read off the Kleene closure."""
    star = closure(matrix)
    np.fill_diagonal(star, -np.inf)
    with np.errstate(invalid="ignore"):
        best = np.max(star, axis=0)
    best = np.where(np.isfinite(best), best, 0.0)
    return np.maximum(best, 0.0)


def to_calendar_schedule(
    start_work: np.ndarray,
    durations: np.ndarray,
    calendar: WorkCalendar,
    project_start: datetime,
) -> tuple[list[datetime], list[datetime], list[tuple[tuple[datetime, datetime], ...]]]:
    """Map work-time positions onto the calendar.

    Returns calendar start moments, calendar end moments and, for each
    task, the working periods it occupies.  A task that cannot finish
    before a break pauses and resumes, so its list holds more than one
    period.
    """
    starts: list[datetime] = []
    ends: list[datetime] = []
    segments: list[tuple[tuple[datetime, datetime], ...]] = []
    for begin, duration in zip(start_work, durations):
        start_cal = calendar.W_inverse(float(begin), project_start)
        end_cal = calendar.W_inverse(float(begin) + float(duration), project_start)
        starts.append(start_cal)
        ends.append(end_cal)
        segments.append(tuple(calendar.occupied_intervals(start_cal, end_cal, project_start)))
    return starts, ends, segments


def solve(
    instance: Instance,
    calendar: WorkCalendar | None = None,
    assignment: Assignment | None = None,
    project_start: datetime | None = None,
    method: str = "topological",
) -> Schedule:
    """Schedule an instance.

    Parameters
    ----------
    instance:
        the problem, normally from :func:`calrcpsp.load_instance`.
    calendar:
        defaults to the calendar stored in the instance.
    assignment:
        defaults to :func:`calrcpsp.assign_resources` with the balanced
        strategy.
    project_start:
        defaults to the first working moment on or after Monday
        2025-01-06.
    method:
        ``"topological"`` uses the max-plus state recursion in
        ``O(n + e)``.  ``"closure"`` uses the Kleene closure in
        ``O(n^3)``.  Both give the same start times; the second is there
        for inspection and for checking the first.
    """
    if method not in ("topological", "closure"):
        raise ValueError(f"unknown method {method!r}")

    calendar = calendar if calendar is not None else WorkCalendar.from_spec(instance.calendar)
    assignment = assignment if assignment is not None else assign_resources(instance)
    anchor = project_start if project_start is not None else DEFAULT_PROJECT_START
    project_start = calendar.next_working_time(anchor)

    algebra_start = time.perf_counter()
    order = topological_order(instance)
    precedence = build_precedence_matrix(instance)
    resource = build_resource_matrix(instance, assignment, order=order)
    combined = combine_matrices(precedence, resource)

    if method == "closure":
        start_work = _starts_from_closure(combined)
    else:
        start_work = earliest_start_times(combined, order)

    durations = np.asarray(instance.durations(), dtype=float)
    end_work = start_work + durations
    makespan = float(np.max(end_work)) if len(end_work) else 0.0

    latest = latest_start_times(combined, order, durations, makespan)
    total_float = np.maximum(latest - start_work, 0.0)
    solve_seconds = time.perf_counter() - algebra_start

    calendar_begin = time.perf_counter()
    starts, ends, segments = to_calendar_schedule(
        start_work, durations, calendar, project_start
    )
    calendar_seconds = time.perf_counter() - calendar_begin

    tasks = tuple(
        TaskSchedule(
            task_id=task.task_id,
            resource_id=assignment.resource_of(task.task_id),
            duration=float(durations[i]),
            start_work=float(start_work[i]),
            end_work=float(end_work[i]),
            start=starts[i],
            end=ends[i],
            slack=float(total_float[i]),
            critical=bool(total_float[i] <= _CRITICAL_TOL),
            segments=segments[i],
        )
        for i, task in enumerate(instance.tasks)
    )

    return Schedule(
        instance=instance,
        calendar=calendar,
        assignment=assignment,
        project_start=project_start,
        tasks=tasks,
        solve_seconds=solve_seconds,
        calendar_seconds=calendar_seconds,
        method=method,
    )
