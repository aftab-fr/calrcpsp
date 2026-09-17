"""calrcpsp: calendar-aware resource-constrained project scheduling.

A small library for scheduling projects whose tasks may only run during
working hours.  It reads the published CA-RCPSP benchmark format, builds
max-plus scheduling matrices, solves them, and reports start times,
makespan, slack, the critical path and calendar compliance.  It also
repairs a schedule after a disruption.

A ten line example::

    from calrcpsp import load_instance, solve, compliance_report

    instance = load_instance("tiny_manufacturing_demo.json")
    schedule = solve(instance)
    print(schedule.makespan)
    print(schedule.start_times()["T001"])
    print(schedule.critical_path())
    print(compliance_report(schedule).working_time)

Every step is also callable on its own: see :func:`assign_resources`,
:func:`build_precedence_matrix`, :func:`build_resource_matrix`,
:func:`closure` and :class:`WorkCalendar`.
"""

from __future__ import annotations

__version__ = "1.0.0"

from .assignment import Assignment, assign_resources
from .calendar import DEFAULT_PROJECT_START, WorkCalendar
from .instance import (
    CalendarSpec,
    DisruptionSpec,
    Instance,
    InstanceError,
    Resource,
    ShiftSpec,
    Task,
    load_instance,
    load_instances,
)
from .maxplus import (
    NEG_INF,
    build_precedence_matrix,
    build_resource_matrix,
    closure,
    combine_matrices,
    earliest_start_times,
    latest_start_times,
    topological_order,
)
from .metrics import (
    ComplianceReport,
    compliance_report,
    precedence_violations,
    resource_conflicts,
    resource_utilization,
    validate_schedule,
)
from .reschedule import (
    Disruption,
    RescheduleResult,
    disruption_from_spec,
    reschedule,
)
from .schedule import Schedule, TaskSchedule
from .scheduler import solve, to_calendar_schedule

__all__ = [
    "__version__",
    # instances
    "Instance",
    "InstanceError",
    "Task",
    "Resource",
    "ShiftSpec",
    "CalendarSpec",
    "DisruptionSpec",
    "load_instance",
    "load_instances",
    # calendar
    "WorkCalendar",
    "DEFAULT_PROJECT_START",
    # assignment
    "Assignment",
    "assign_resources",
    # max-plus
    "NEG_INF",
    "build_precedence_matrix",
    "build_resource_matrix",
    "combine_matrices",
    "closure",
    "topological_order",
    "earliest_start_times",
    "latest_start_times",
    # solving
    "solve",
    "to_calendar_schedule",
    "Schedule",
    "TaskSchedule",
    # disruption
    "Disruption",
    "RescheduleResult",
    "disruption_from_spec",
    "reschedule",
    # metrics
    "ComplianceReport",
    "compliance_report",
    "precedence_violations",
    "resource_conflicts",
    "resource_utilization",
    "validate_schedule",
]
