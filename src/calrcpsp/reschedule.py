"""Repairing a schedule after a disruption.

The published instance format records disruptions as a type, a severity
and a duration.  It does not say which task or which resource is hit, so
turning a stored record into something a scheduler can apply needs a
targeting rule.  :func:`disruption_from_spec` supplies one that is fully
deterministic, and :class:`Disruption` lets a caller state a target
directly instead.

Rescheduling re-solves the instance with the updated durations, reusing
the existing resource assignment, calendar and project start.  It is not
an incremental matrix update: the whole schedule is recomputed.  On these
instances that costs milliseconds, so the simpler and more obviously
correct route was kept.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .instance import DisruptionSpec, InstanceError
from .schedule import Schedule
from .scheduler import solve

__all__ = ["Disruption", "RescheduleResult", "disruption_from_spec", "reschedule"]

#: Disruption types that take a machine out of service.
_MACHINE_TYPES = frozenset(
    {
        "machine_failure",
        "resource_unavailable",
        "system_wide_failure",
        "catastrophic_failure",
        "plant_shutdown",
    }
)

#: Disruption types that take a worker out of service.
_WORKER_TYPES = frozenset({"worker_absence", "worker_strike"})


@dataclass(frozen=True)
class Disruption:
    """A disruption with a concrete target.

    ``kind`` is ``"task_delay"`` or ``"resource_outage"``.  A task delay
    lengthens one task.  A resource outage inserts downtime on one
    resource, modelled as extra time on the first task that resource is
    due to perform.
    """

    kind: str
    target: str
    extra_hours: float
    label: str = ""

    @classmethod
    def task_delay(cls, task_id: str, extra_hours: float, label: str = "") -> Disruption:
        return cls("task_delay", task_id, float(extra_hours), label or f"delay on {task_id}")

    @classmethod
    def resource_outage(
        cls, resource_id: str, extra_hours: float, label: str = ""
    ) -> Disruption:
        return cls(
            "resource_outage", resource_id, float(extra_hours), label or f"outage on {resource_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "extra_hours": round(self.extra_hours, 6),
            "label": self.label,
        }


def disruption_from_spec(spec: DisruptionSpec, schedule: Schedule) -> Disruption:
    """Turn a stored disruption record into a targeted disruption.

    The rule, applied to the baseline schedule:

    * machine type records hit the machine carrying the most work;
    * worker type records hit the worker carrying the most work;
    * every other record delays the longest task on the critical path,
      falling back to the longest task overall if the critical path is
      empty.

    Ties break on the identifier, so the choice is reproducible.
    """
    load: dict[str, float] = {}
    for task in schedule.tasks:
        load[task.resource_id] = load.get(task.resource_id, 0.0) + task.duration

    def busiest(resource_type: str) -> str | None:
        candidates = [
            r.resource_id
            for r in schedule.instance.resources
            if r.resource_type.lower() == resource_type and load.get(r.resource_id, 0.0) > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda rid: (load[rid], rid))

    if spec.type in _MACHINE_TYPES:
        target = busiest("machine")
        if target is not None:
            return Disruption.resource_outage(target, spec.duration_hours, spec.type)
    if spec.type in _WORKER_TYPES:
        target = busiest("worker")
        if target is not None:
            return Disruption.resource_outage(target, spec.duration_hours, spec.type)

    critical = set(schedule.critical_path())
    pool = [t for t in schedule.tasks if t.task_id in critical] or list(schedule.tasks)
    worst = max(pool, key=lambda t: (t.duration, t.task_id))
    return Disruption.task_delay(worst.task_id, spec.duration_hours, spec.type)


@dataclass(frozen=True)
class RescheduleResult:
    """Outcome of repairing a schedule."""

    schedule: Schedule
    baseline_makespan: float
    new_makespan: float
    seconds: float
    disruption: Disruption
    affected_tasks: int

    @property
    def delta_hours(self) -> float:
        return self.new_makespan - self.baseline_makespan

    @property
    def delta_percent(self) -> float:
        if self.baseline_makespan <= 0:
            return 0.0
        return 100.0 * self.delta_hours / self.baseline_makespan

    def to_dict(self) -> dict[str, Any]:
        return {
            "disruption": self.disruption.to_dict(),
            "baseline_makespan_work_hours": round(self.baseline_makespan, 6),
            "new_makespan_work_hours": round(self.new_makespan, 6),
            "makespan_increase_work_hours": round(self.delta_hours, 6),
            "makespan_increase_percent": round(self.delta_percent, 4),
            "reschedule_seconds": round(self.seconds, 6),
            "tasks_moved": self.affected_tasks,
        }


def reschedule(schedule: Schedule, disruption: Disruption) -> RescheduleResult:
    """Apply a disruption to a schedule and solve again.

    The repaired schedule keeps the original resource assignment,
    calendar and project start, so the two schedules are comparable task
    by task.
    """
    instance = schedule.instance
    durations = list(instance.durations())

    if disruption.kind == "task_delay":
        index = instance.index_of(disruption.target)
        durations[index] += disruption.extra_hours
    elif disruption.kind == "resource_outage":
        on_resource = [t for t in schedule.tasks if t.resource_id == disruption.target]
        if not on_resource:
            raise InstanceError(
                f"resource {disruption.target!r} performs no task in this schedule"
            )
        first = min(on_resource, key=lambda t: (t.start_work, t.task_id))
        durations[instance.index_of(first.task_id)] += disruption.extra_hours
    else:
        raise ValueError(f"unknown disruption kind {disruption.kind!r}")

    disrupted = instance.with_durations(durations)

    begin = time.perf_counter()
    repaired = solve(
        disrupted,
        calendar=schedule.calendar,
        assignment=schedule.assignment,
        project_start=schedule.project_start,
        method=schedule.method,
    )
    seconds = time.perf_counter() - begin

    before = schedule.start_work_times
    moved = sum(
        1
        for task in repaired.tasks
        if abs(task.start_work - before.get(task.task_id, task.start_work)) > 1e-9
    )

    return RescheduleResult(
        schedule=repaired,
        baseline_makespan=schedule.makespan,
        new_makespan=repaired.makespan,
        seconds=seconds,
        disruption=disruption,
        affected_tasks=moved,
    )
