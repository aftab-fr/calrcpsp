"""Resource assignment."""

from __future__ import annotations

import pytest

from calrcpsp import Instance, assign_resources, load_instance, solve
from calrcpsp.assignment import STRATEGIES


def _pool_instance() -> Instance:
    """Four tasks needing the same skill, two resources that both hold it."""
    return Instance.from_dict(
        {
            "scenario_id": "pool",
            "tasks": [
                {"task_id": f"T{i}", "duration": 1.0, "required_skills": ["cut"]}
                for i in range(4)
            ],
            "dependencies": [],
            "resources": [
                {"resource_id": "R1", "resource_type": "Machine",
                 "skills": {"cut": 0.9}},
                {"resource_id": "R2", "resource_type": "Machine",
                 "skills": {"cut": 0.5}},
            ],
            "calendar_requirements": {
                "shifts": [{"name": "d", "start": "08:00", "end": "17:00",
                            "days": [0, 1, 2, 3, 4]}]
            },
        }
    )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_task_gets_exactly_one_resource(instance_path, strategy):
    instance = load_instance(instance_path)
    assignment = assign_resources(instance, strategy)
    assert set(assignment.task_to_resource) == set(instance.task_ids)
    valid = {r.resource_id for r in instance.resources}
    assert set(assignment.task_to_resource.values()) <= valid


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_assignment_is_deterministic(instance_path, strategy):
    instance = load_instance(instance_path)
    first = assign_resources(instance, strategy)
    second = assign_resources(instance, strategy)
    assert first.task_to_resource == second.task_to_resource
    assert first.coverage == second.coverage


def test_unknown_strategy_is_rejected(tiny):
    with pytest.raises(ValueError, match="unknown assignment strategy"):
        assign_resources(tiny, "nonsense")


def test_balanced_spreads_work_over_equal_resources():
    assignment = assign_resources(_pool_instance(), "balanced")
    assert assignment.load["R1"] == assignment.load["R2"] == 2.0


def test_coverage_prefers_the_more_proficient_resource():
    assignment = assign_resources(_pool_instance(), "coverage")
    # Both cover fully, so proficiency decides and R1 takes everything.
    assert assignment.load["R1"] == 4.0
    assert assignment.load["R2"] == 0.0


def test_coverage_is_between_zero_and_one(instance_path):
    assignment = assign_resources(load_instance(instance_path))
    assert all(0.0 <= v <= 1.0 for v in assignment.coverage.values())
    assert 0.0 <= assignment.mean_coverage <= 1.0
    assert assignment.uncovered == 0, "the data guarantees every skill is held somewhere"


def test_max_load_is_a_lower_bound_on_the_makespan(instance_path):
    instance = load_instance(instance_path)
    assignment = assign_resources(instance)
    schedule = solve(instance, assignment=assignment)
    assert schedule.makespan >= assignment.max_load - 1e-9


def test_balanced_is_not_worse_than_coverage_on_max_load(instance_path):
    """The default keeps the busiest resource lighter, which caps the makespan."""
    instance = load_instance(instance_path)
    balanced = assign_resources(instance, "balanced")
    coverage = assign_resources(instance, "coverage")
    assert balanced.max_load <= coverage.max_load + 1e-9


def test_coverage_strategy_matches_skills_at_least_as_well(instance_path):
    instance = load_instance(instance_path)
    balanced = assign_resources(instance, "balanced")
    coverage = assign_resources(instance, "coverage")
    assert coverage.mean_coverage >= balanced.mean_coverage - 1e-9
