"""Reading and representing CA-RCPSP problem instances.

The JSON schema handled here is the one published with the CA-RCPSP
benchmark dataset (Data in Brief 69 (2026) 113256, Zenodo record
10.5281/zenodo.20553817).  Any file that follows that schema can be read,
not only the twelve deposited instances.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "InstanceError",
    "Task",
    "Resource",
    "ShiftSpec",
    "CalendarSpec",
    "DisruptionSpec",
    "Instance",
    "load_instance",
    "load_instances",
]


class InstanceError(ValueError):
    """Raised when an instance file is missing data or is structurally invalid."""


@dataclass(frozen=True)
class Task:
    """A single activity.

    ``duration`` is expressed in work-hours, that is hours of productive
    work, not elapsed calendar hours.
    """

    task_id: str
    task_type: str
    duration: float
    required_skills: tuple[str, ...] = ()
    priority: int = 1
    earliest_start: str | None = None
    deadline: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Task:
        try:
            task_id = str(raw["task_id"])
            duration = float(raw["duration"])
        except KeyError as exc:
            raise InstanceError(f"task is missing required field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise InstanceError(f"task {raw.get('task_id')!r} has a bad duration") from exc
        if duration <= 0:
            raise InstanceError(f"task {task_id!r} has non-positive duration {duration}")
        return cls(
            task_id=task_id,
            task_type=str(raw.get("task_type", "unknown")),
            duration=duration,
            required_skills=tuple(raw.get("required_skills") or ()),
            priority=int(raw.get("priority", 1)),
            earliest_start=raw.get("earliest_start"),
            deadline=raw.get("deadline"),
        )


@dataclass(frozen=True)
class Resource:
    """A machine or a worker, with a skill proficiency map."""

    resource_id: str
    name: str
    resource_type: str
    skills: Mapping[str, float] = field(default_factory=dict)
    cost_per_hour: float = 0.0
    efficiency: float = 1.0
    machine_type: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Resource:
        try:
            resource_id = str(raw["resource_id"])
        except KeyError as exc:
            raise InstanceError(f"resource is missing required field {exc}") from exc
        skills = {str(k): float(v) for k, v in (raw.get("skills") or {}).items()}
        return cls(
            resource_id=resource_id,
            name=str(raw.get("name", resource_id)),
            resource_type=str(raw.get("resource_type", "Machine")),
            skills=skills,
            cost_per_hour=float(raw.get("cost_per_hour", 0.0)),
            efficiency=float(raw.get("efficiency", 1.0)),
            machine_type=raw.get("machine_type"),
        )

    def has_skill(self, skill: str, min_level: float = 0.0) -> bool:
        return self.skills.get(skill, -1.0) >= min_level


@dataclass(frozen=True)
class ShiftSpec:
    """One named shift.

    ``end`` earlier than or equal to ``start`` means the shift runs past
    midnight and finishes on the following calendar day.  ``days`` holds
    Python weekday numbers, Monday is 0.
    """

    name: str
    start: str
    end: str
    days: tuple[int, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ShiftSpec:
        try:
            return cls(
                name=str(raw.get("name", "shift")),
                start=str(raw["start"]),
                end=str(raw["end"]),
                days=tuple(int(d) for d in raw.get("days", range(5))),
            )
        except KeyError as exc:
            raise InstanceError(f"shift is missing required field {exc}") from exc

    @property
    def wraps_midnight(self) -> bool:
        return self.end <= self.start


@dataclass(frozen=True)
class CalendarSpec:
    """Work calendar as stored in the instance file."""

    shift_type: str
    shifts: tuple[ShiftSpec, ...]
    lunch_break: tuple[str, str] | None = None
    holidays: tuple[date, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CalendarSpec:
        shifts = tuple(ShiftSpec.from_dict(s) for s in raw.get("shifts") or ())
        if not shifts:
            raise InstanceError("calendar_requirements defines no shifts")
        lunch_raw = raw.get("lunch_break")
        lunch = (str(lunch_raw["start"]), str(lunch_raw["end"])) if lunch_raw else None
        holidays = []
        for value in raw.get("holidays") or ():
            try:
                holidays.append(datetime.strptime(str(value), "%Y-%m-%d").date())
            except ValueError as exc:
                raise InstanceError(f"holiday {value!r} is not an ISO date") from exc
        return cls(
            shift_type=str(raw.get("shift_type", "custom")),
            shifts=shifts,
            lunch_break=lunch,
            holidays=tuple(sorted(holidays)),
        )


@dataclass(frozen=True)
class DisruptionSpec:
    """A disruption record as stored in the instance file.

    The published schema records a type, a severity and a duration but no
    target task or resource, so a targeting rule has to be supplied when
    the record is turned into an applicable disruption.  See
    :mod:`calrcpsp.reschedule`.
    """

    type: str
    severity: str
    duration_hours: float
    probability: float = 0.0
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DisruptionSpec:
        try:
            return cls(
                type=str(raw["type"]),
                severity=str(raw.get("severity", "medium")),
                duration_hours=float(raw["duration_hours"]),
                probability=float(raw.get("probability", 0.0)),
                description=str(raw.get("description", "")),
            )
        except KeyError as exc:
            raise InstanceError(f"disruption is missing required field {exc}") from exc


@dataclass(frozen=True)
class Instance:
    """A complete CA-RCPSP problem instance."""

    scenario_id: str
    tasks: tuple[Task, ...]
    dependencies: tuple[tuple[str, str], ...]
    resources: tuple[Resource, ...]
    calendar: CalendarSpec
    disruptions: tuple[DisruptionSpec, ...] = ()
    name: str = ""
    scale: str = ""
    random_seed: int | None = None
    schema_version: str = ""
    expected_performance: Mapping[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    # -- lookups ---------------------------------------------------------

    @property
    def n_tasks(self) -> int:
        return len(self.tasks)

    @property
    def n_resources(self) -> int:
        return len(self.resources)

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(t.task_id for t in self.tasks)

    def index_of(self, task_id: str) -> int:
        try:
            return self._index[task_id]
        except KeyError as exc:
            raise InstanceError(f"unknown task id {task_id!r}") from exc

    def task(self, task_id: str) -> Task:
        return self.tasks[self.index_of(task_id)]

    def resource(self, resource_id: str) -> Resource:
        for r in self.resources:
            if r.resource_id == resource_id:
                return r
        raise InstanceError(f"unknown resource id {resource_id!r}")

    @property
    def _index(self) -> dict[str, int]:
        cached = self.__dict__.get("_index_cache")
        if cached is None:
            cached = {t.task_id: i for i, t in enumerate(self.tasks)}
            object.__setattr__(self, "_index_cache", cached)
        return cached

    def edges(self) -> tuple[tuple[int, int], ...]:
        """Dependencies as index pairs."""
        return tuple((self.index_of(p), self.index_of(s)) for p, s in self.dependencies)

    def durations(self) -> tuple[float, ...]:
        return tuple(t.duration for t in self.tasks)

    def total_work_hours(self) -> float:
        return float(sum(t.duration for t in self.tasks))

    # -- construction ----------------------------------------------------

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], source_path: Path | None = None) -> Instance:
        for key in ("tasks", "resources", "calendar_requirements"):
            if key not in raw:
                raise InstanceError(f"instance is missing required top-level key {key!r}")

        tasks = tuple(Task.from_dict(t) for t in raw["tasks"])
        if not tasks:
            raise InstanceError("instance contains no tasks")

        seen: set[str] = set()
        for t in tasks:
            if t.task_id in seen:
                raise InstanceError(f"duplicate task id {t.task_id!r}")
            seen.add(t.task_id)

        deps: list[tuple[str, str]] = []
        for pair in raw.get("dependencies") or ():
            if len(pair) != 2:
                raise InstanceError(f"dependency {pair!r} is not a pair")
            pred, succ = str(pair[0]), str(pair[1])
            if pred not in seen:
                raise InstanceError(f"dependency references unknown task {pred!r}")
            if succ not in seen:
                raise InstanceError(f"dependency references unknown task {succ!r}")
            if pred == succ:
                raise InstanceError(f"task {pred!r} depends on itself")
            deps.append((pred, succ))

        resources = tuple(Resource.from_dict(r) for r in raw["resources"])
        if not resources:
            raise InstanceError("instance contains no resources")

        inst = cls(
            scenario_id=str(raw.get("scenario_id", "unnamed")),
            tasks=tasks,
            dependencies=tuple(deps),
            resources=resources,
            calendar=CalendarSpec.from_dict(raw["calendar_requirements"]),
            disruptions=tuple(DisruptionSpec.from_dict(d) for d in raw.get("disruptions") or ()),
            name=str(raw.get("name", "")),
            scale=str(raw.get("scale", "")),
            random_seed=raw.get("random_seed"),
            schema_version=str(raw.get("schema_version", "")),
            expected_performance=dict(raw.get("expected_performance") or {}),
            source_path=source_path,
        )
        _assert_acyclic(inst)
        return inst

    def with_durations(self, durations: Sequence[float]) -> Instance:
        """Return a copy with replaced task durations, used by rescheduling."""
        if len(durations) != self.n_tasks:
            raise InstanceError("duration vector length does not match task count")
        tasks = tuple(
            Task(
                task_id=t.task_id,
                task_type=t.task_type,
                duration=float(d),
                required_skills=t.required_skills,
                priority=t.priority,
                earliest_start=t.earliest_start,
                deadline=t.deadline,
            )
            for t, d in zip(self.tasks, durations, strict=True)
        )
        return Instance(
            scenario_id=self.scenario_id,
            tasks=tasks,
            dependencies=self.dependencies,
            resources=self.resources,
            calendar=self.calendar,
            disruptions=self.disruptions,
            name=self.name,
            scale=self.scale,
            random_seed=self.random_seed,
            schema_version=self.schema_version,
            expected_performance=self.expected_performance,
            source_path=self.source_path,
        )


def _assert_acyclic(inst: Instance) -> None:
    """Depth-first cycle check over the dependency graph."""
    n = inst.n_tasks
    succ: list[list[int]] = [[] for _ in range(n)]
    for p, s in inst.edges():
        succ[p].append(s)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = [WHITE] * n
    for root in range(n):
        if colour[root] != WHITE:
            continue
        stack = [(root, iter(succ[root]))]
        colour[root] = GREY
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if colour[child] == GREY:
                    raise InstanceError(
                        f"dependency graph contains a cycle through task "
                        f"{inst.tasks[child].task_id!r}"
                    )
                if colour[child] == WHITE:
                    colour[child] = GREY
                    stack.append((child, iter(succ[child])))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                stack.pop()


def load_instance(path: str | Path) -> Instance:
    """Read one CA-RCPSP JSON instance from disk."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as exc:
        raise InstanceError(f"no such instance file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InstanceError(f"{path} is not valid JSON: {exc}") from exc
    return Instance.from_dict(raw, source_path=path)


def load_instances(directory: str | Path, pattern: str = "**/*.json") -> list[Instance]:
    """Read every instance under ``directory``, sorted by file path."""
    directory = Path(directory)
    if not directory.is_dir():
        raise InstanceError(f"not a directory: {directory}")
    return [load_instance(p) for p in sorted(directory.glob(pattern))]
