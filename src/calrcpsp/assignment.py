"""Assigning one resource to each task by skill matching.

The published instance format lists the skills each task requires and the
skills each resource holds, but it does not say which resource performs
which task.  That assignment has to be computed before any resource
constraint can be written down, so it is a separate, callable step.

Two facts about the data shape this module, and neither is hidden.

First, a task may require a set of skills that no single resource holds.
In the twelve deposited instances this happens for between 3 and 179
tasks per instance, and the model assigns exactly one resource per task,
so those tasks cannot be covered in full by any assignment at all.  The
coverage achieved is measured and reported rather than assumed.

Second, the two obvious rules pull against each other.  Always giving a
task to the resource with the best skill match piles work onto whichever
resource happens to hold a rare skill pair: on
``large_industrial_scale_500`` that one choice pushes the makespan from
46.9 to 252.9 work-hours.  Spreading the load instead costs roughly ten
points of mean skill coverage.  Both rules are provided, the load-aware
one is the default, and both numbers appear in the output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .instance import Instance, InstanceError, Resource

__all__ = ["Assignment", "assign_resources", "STRATEGIES"]

#: Available assignment strategies.
STRATEGIES = ("balanced", "coverage")


@dataclass(frozen=True)
class Assignment:
    """Which resource performs which task."""

    task_to_resource: Mapping[str, str]
    coverage: Mapping[str, float]
    load: Mapping[str, float]
    strategy: str = "balanced"

    def resource_of(self, task_id: str) -> str:
        try:
            return self.task_to_resource[task_id]
        except KeyError as exc:
            raise InstanceError(f"task {task_id!r} has no assigned resource") from exc

    def tasks_of(self, resource_id: str) -> tuple[str, ...]:
        return tuple(t for t, r in self.task_to_resource.items() if r == resource_id)

    def groups(self) -> dict[str, list[str]]:
        """Resource id mapped to the tasks it performs, in instance order."""
        out: dict[str, list[str]] = {}
        for task_id, resource_id in self.task_to_resource.items():
            out.setdefault(resource_id, []).append(task_id)
        return out

    @property
    def fully_covered(self) -> int:
        """Number of tasks whose resource holds every skill they require."""
        return sum(1 for value in self.coverage.values() if value >= 1.0)

    @property
    def uncovered(self) -> int:
        """Number of tasks whose resource holds none of the skills they require."""
        return sum(1 for value in self.coverage.values() if value <= 0.0)

    @property
    def mean_coverage(self) -> float:
        if not self.coverage:
            return 1.0
        return sum(self.coverage.values()) / len(self.coverage)

    @property
    def max_load(self) -> float:
        """Work-hours carried by the busiest resource, a lower bound on makespan."""
        return max(self.load.values(), default=0.0)

    @property
    def resources_used(self) -> int:
        return sum(1 for value in self.load.values() if value > 0)


def _score(resource: Resource, required: Sequence[str]) -> tuple[float, float]:
    """Return the covered fraction and the mean proficiency over covered skills."""
    if not required:
        return 1.0, 1.0
    levels = [resource.skills[s] for s in required if s in resource.skills]
    if not levels:
        return 0.0, 0.0
    return len(levels) / len(required), sum(levels) / len(levels)


def assign_resources(instance: Instance, strategy: str = "balanced") -> Assignment:
    """Assign exactly one resource to every task.

    Parameters
    ----------
    instance:
        the problem to assign.
    strategy:
        ``"balanced"`` (the default) considers every resource holding at
        least one required skill and picks the one carrying the least work
        so far, breaking ties on coverage, then proficiency, then
        identifier.  This keeps the busiest resource small, which is a
        lower bound on the makespan.

        ``"coverage"`` picks the highest skill coverage first, then the
        highest proficiency, then the least loaded.  Use it when skill
        match matters more than completion time.  It can leave one
        resource carrying most of the project.

    Both walk the tasks in instance order and break every tie on the
    resource identifier, so both are fully reproducible.
    """
    if strategy not in STRATEGIES:
        raise ValueError(
            f"unknown assignment strategy {strategy!r}, expected one of {STRATEGIES}"
        )
    if not instance.resources:
        raise InstanceError("instance has no resources to assign")

    load: dict[str, float] = {r.resource_id: 0.0 for r in instance.resources}
    task_to_resource: dict[str, str] = {}
    coverage: dict[str, float] = {}

    for task in instance.tasks:
        required = task.required_skills
        scored = [(resource,) + _score(resource, required) for resource in instance.resources]

        if strategy == "balanced":
            # Only resources holding at least one required skill are eligible.
            # Where none qualifies the whole pool is eligible, so every task
            # still gets a resource.
            pool = [entry for entry in scored if entry[1] > 0.0] or scored
            chosen = min(
                pool,
                key=lambda entry: (
                    load[entry[0].resource_id],
                    -entry[1],
                    -entry[2],
                    entry[0].resource_id,
                ),
            )
        else:  # "coverage"
            chosen = min(
                scored,
                key=lambda entry: (
                    -entry[1],
                    -entry[2],
                    load[entry[0].resource_id],
                    entry[0].resource_id,
                ),
            )

        resource, covered, _ = chosen
        task_to_resource[task.task_id] = resource.resource_id
        coverage[task.task_id] = covered
        load[resource.resource_id] += task.duration

    return Assignment(
        task_to_resource=task_to_resource,
        coverage=coverage,
        load=load,
        strategy=strategy,
    )
