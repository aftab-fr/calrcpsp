"""The schedule object returned by the solver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .assignment import Assignment
from .calendar import WorkCalendar
from .instance import Instance

__all__ = ["TaskSchedule", "Schedule"]


@dataclass(frozen=True)
class TaskSchedule:
    """Where one task landed.

    ``start_work`` and ``end_work`` are work-hours measured from the
    project start.  ``start`` and ``end`` are calendar moments.
    ``segments`` lists the working periods the task actually occupies; a
    task interrupted by a break, a night or a weekend has more than one.
    """

    task_id: str
    resource_id: str
    duration: float
    start_work: float
    end_work: float
    start: datetime
    end: datetime
    slack: float
    critical: bool
    segments: tuple[tuple[datetime, datetime], ...] = ()

    @property
    def interrupted(self) -> bool:
        return len(self.segments) > 1

    @property
    def elapsed_hours(self) -> float:
        """Calendar hours between start and end, including non-working time."""
        return (self.end - self.start).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "resource_id": self.resource_id,
            "duration_work_hours": round(self.duration, 6),
            "start_work_hours": round(self.start_work, 6),
            "end_work_hours": round(self.end_work, 6),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "elapsed_hours": round(self.elapsed_hours, 6),
            "slack_work_hours": round(self.slack, 6),
            "critical": self.critical,
            "segments": len(self.segments),
        }


@dataclass(frozen=True)
class Schedule:
    """A complete schedule for one instance."""

    instance: Instance
    calendar: WorkCalendar
    assignment: Assignment
    project_start: datetime
    tasks: tuple[TaskSchedule, ...]
    solve_seconds: float = 0.0
    calendar_seconds: float = 0.0
    method: str = "topological"

    # -- the four headline outputs --------------------------------------

    def start_times(self) -> dict[str, datetime]:
        """Calendar start moment of every task."""
        return {t.task_id: t.start for t in self.tasks}

    @property
    def makespan(self) -> float:
        """Project makespan in work-hours."""
        return max((t.end_work for t in self.tasks), default=0.0)

    def slack(self) -> dict[str, float]:
        """Total float of every task, in work-hours."""
        return {t.task_id: t.slack for t in self.tasks}

    def critical_path(self) -> tuple[str, ...]:
        """Tasks with no float, ordered by start.

        Delaying any of these delays the project.
        """
        critical = sorted(
            (t for t in self.tasks if t.critical), key=lambda t: (t.start_work, t.task_id)
        )
        return tuple(t.task_id for t in critical)

    # -- derived ---------------------------------------------------------

    @property
    def end(self) -> datetime:
        """Calendar moment the last task finishes."""
        return max((t.end for t in self.tasks), default=self.project_start)

    @property
    def elapsed_hours(self) -> float:
        """Calendar hours from project start to last finish."""
        return (self.end - self.project_start).total_seconds() / 3600.0

    @property
    def start_work_times(self) -> dict[str, float]:
        return {t.task_id: t.start_work for t in self.tasks}

    def task(self, task_id: str) -> TaskSchedule:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        raise KeyError(task_id)

    def by_resource(self) -> dict[str, list[TaskSchedule]]:
        out: dict[str, list[TaskSchedule]] = {}
        for t in sorted(self.tasks, key=lambda t: t.start_work):
            out.setdefault(t.resource_id, []).append(t)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.instance.scenario_id,
            "n_tasks": self.instance.n_tasks,
            "n_resources": self.instance.n_resources,
            "calendar": self.calendar.name,
            "method": self.method,
            "project_start": self.project_start.isoformat(),
            "project_end": self.end.isoformat(),
            "makespan_work_hours": round(self.makespan, 6),
            "elapsed_calendar_hours": round(self.elapsed_hours, 6),
            "solve_seconds": round(self.solve_seconds, 6),
            "calendar_seconds": round(self.calendar_seconds, 6),
            "critical_path_length": len(self.critical_path()),
            "tasks": [t.to_dict() for t in self.tasks],
        }

    def to_json(self, path: str | None = None, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent)
        if path is not None:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return text

    def summary(self) -> str:
        """One human readable block, used by the command line interface."""
        from .metrics import compliance_report, resource_utilization

        compliance = compliance_report(self)
        utilisation = resource_utilization(self)
        lines = [
            f"instance        : {self.instance.scenario_id} "
            f"({self.instance.n_tasks} tasks, {self.instance.n_resources} resources)",
            f"calendar        : {self.calendar.name}",
            f"project start   : {self.project_start:%Y-%m-%d %H:%M}",
            f"project end     : {self.end:%Y-%m-%d %H:%M}",
            f"makespan        : {self.makespan:.3f} work-hours "
            f"({self.elapsed_hours:.1f} calendar hours elapsed)",
            f"critical path   : {len(self.critical_path())} of {self.instance.n_tasks} tasks",
            f"mean utilisation: {utilisation['mean']:.3f}",
            f"compliance      : working-time {compliance.working_time:.4f}, "
            f"uninterrupted {compliance.uninterrupted:.4f}",
            f"solve time      : {self.solve_seconds * 1000:.2f} ms ({self.method})",
        ]
        return "\n".join(lines)
