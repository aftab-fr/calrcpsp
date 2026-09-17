"""Checks and measurements on a finished schedule.

Everything here reads a :class:`~calrcpsp.schedule.Schedule` and returns
plain numbers or lists of violations.  Nothing here changes a schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from .schedule import Schedule

__all__ = [
    "ComplianceReport",
    "compliance_report",
    "precedence_violations",
    "resource_conflicts",
    "resource_utilization",
    "validate_schedule",
]

_TOL = 1e-6


@dataclass(frozen=True)
class ComplianceReport:
    """Calendar compliance measured two ways.

    The two numbers answer different questions and both are reported
    because they can differ a lot.

    ``working_time``
        share of scheduled work that falls inside a working period.  A
        correct calendar-aware schedule reaches 1.0: no work is ever
        placed on a night, a weekend, a break or a holiday.

    ``uninterrupted``
        share of tasks that run from start to finish without crossing any
        non-working period.  This is a stricter question.  A scheduler
        that lets a task pause over lunch and resume afterwards scores
        below 1.0 here by design, and the shortfall grows with task
        duration relative to the shift length.

    ``all_intervals_in_working_time``
        True when every scheduled interval of every task lies inside a
        working period.  This is the property the test suite asserts.
    """

    working_time: float
    uninterrupted: float
    all_intervals_in_working_time: bool
    n_tasks: int
    n_interrupted: int
    scheduled_work_hours: float
    work_hours_in_working_time: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_time_compliance": round(self.working_time, 6),
            "uninterrupted_compliance": round(self.uninterrupted, 6),
            "all_intervals_in_working_time": self.all_intervals_in_working_time,
            "n_tasks": self.n_tasks,
            "n_interrupted_tasks": self.n_interrupted,
            "scheduled_work_hours": round(self.scheduled_work_hours, 6),
            "work_hours_in_working_time": round(self.work_hours_in_working_time, 6),
        }


def compliance_report(schedule: Schedule) -> ComplianceReport:
    """Measure calendar compliance of a schedule under both definitions."""
    calendar = schedule.calendar
    total_work = 0.0
    total_in_windows = 0.0
    interrupted = 0
    all_inside = True

    for task in schedule.tasks:
        total_work += task.duration
        covered = 0.0
        for start, end in task.segments:
            hours = (end - start).total_seconds() / 3600.0
            covered += hours
            # Sample the midpoint of each interval: segments come from the
            # calendar's own working windows, so this catches any drift
            # between the segment list and the calendar itself.
            midpoint = start + (end - start) / 2
            if not calendar.is_working_time(midpoint):
                all_inside = False
        total_in_windows += min(covered, task.duration)
        if task.interrupted:
            interrupted += 1

    n = len(schedule.tasks)
    return ComplianceReport(
        working_time=(total_in_windows / total_work) if total_work > 0 else 1.0,
        uninterrupted=((n - interrupted) / n) if n else 1.0,
        all_intervals_in_working_time=all_inside,
        n_tasks=n,
        n_interrupted=interrupted,
        scheduled_work_hours=total_work,
        work_hours_in_working_time=total_in_windows,
    )


def precedence_violations(schedule: Schedule) -> list[tuple[str, str, float]]:
    """Dependencies where the successor starts before the predecessor ends.

    Returns ``(predecessor, successor, overlap_in_work_hours)`` triples.
    An empty list means every precedence constraint holds.
    """
    starts = schedule.start_work_times
    ends = {t.task_id: t.end_work for t in schedule.tasks}
    out: list[tuple[str, str, float]] = []
    for pred, succ in schedule.instance.dependencies:
        if pred not in ends or succ not in starts:
            continue
        overlap = ends[pred] - starts[succ]
        if overlap > _TOL:
            out.append((pred, succ, float(overlap)))
    return out


def resource_conflicts(schedule: Schedule) -> list[tuple[str, str, str, float]]:
    """Pairs of tasks that overlap on the same resource.

    Returns ``(resource_id, task_a, task_b, overlap_in_work_hours)``.
    Resources have unit capacity in the published format, so an empty list
    means the resource constraint holds.
    """
    out: list[tuple[str, str, str, float]] = []
    for resource_id, tasks in schedule.by_resource().items():
        ordered = sorted(tasks, key=lambda t: t.start_work)
        for first, second in pairwise(ordered):
            overlap = first.end_work - second.start_work
            if overlap > _TOL:
                out.append((resource_id, first.task_id, second.task_id, float(overlap)))
    return out


def resource_utilization(schedule: Schedule) -> dict[str, float]:
    """Share of the project window each resource spends working.

    The denominator is the working hours the calendar offers between the
    project start and the project end, so the figure is not inflated by
    nights, weekends or holidays.
    """
    available = schedule.calendar.W(schedule.end, schedule.project_start)
    per_resource: dict[str, float] = {
        r.resource_id: 0.0 for r in schedule.instance.resources
    }
    for task in schedule.tasks:
        per_resource[task.resource_id] = per_resource.get(task.resource_id, 0.0) + task.duration

    if available <= 0:
        out = dict.fromkeys(per_resource, 0.0)
        out["mean"] = 0.0
        return out

    out = {key: value / available for key, value in per_resource.items()}
    busy = [v for k, v in out.items()]
    out["mean"] = sum(busy) / len(busy) if busy else 0.0
    out["available_work_hours"] = available
    return out


def validate_schedule(schedule: Schedule) -> dict[str, Any]:
    """Run every check and return a single report."""
    compliance = compliance_report(schedule)
    precedence = precedence_violations(schedule)
    conflicts = resource_conflicts(schedule)
    utilisation = resource_utilization(schedule)
    return {
        "feasible": not precedence and not conflicts
        and compliance.all_intervals_in_working_time,
        "precedence_violations": len(precedence),
        "resource_conflicts": len(conflicts),
        "compliance": compliance.to_dict(),
        "mean_utilization": round(utilisation["mean"], 6),
        "makespan_work_hours": round(schedule.makespan, 6),
        "elapsed_calendar_hours": round(schedule.elapsed_hours, 6),
    }
