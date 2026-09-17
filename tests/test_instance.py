"""Reading and validating instance files."""

from __future__ import annotations

import pytest

from calrcpsp import Instance, InstanceError, load_instance, load_instances

from .conftest import FIXTURE_DIR


def test_loads_every_fixture(instance_path):
    instance = load_instance(instance_path)
    assert instance.n_tasks > 0
    assert instance.n_resources > 0
    assert instance.scenario_id


def test_load_directory():
    found = load_instances(FIXTURE_DIR)
    assert len(found) == 6
    assert len({i.scenario_id for i in found}) == 6


def test_fields_have_expected_types(tiny):
    task = tiny.tasks[0]
    assert isinstance(task.duration, float) and task.duration > 0
    assert isinstance(task.required_skills, tuple)
    assert tiny.calendar.shifts
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in tiny.dependencies)
    assert tiny.durations() == tuple(t.duration for t in tiny.tasks)


def test_dependencies_reference_real_tasks(instance_path):
    instance = load_instance(instance_path)
    ids = set(instance.task_ids)
    for pred, succ in instance.dependencies:
        assert pred in ids and succ in ids


def test_cycle_is_rejected():
    raw = {
        "scenario_id": "cyclic",
        "tasks": [
            {"task_id": "A", "duration": 1.0},
            {"task_id": "B", "duration": 1.0},
        ],
        "dependencies": [["A", "B"], ["B", "A"]],
        "resources": [{"resource_id": "R1", "skills": {}}],
        "calendar_requirements": {
            "shifts": [{"name": "d", "start": "08:00", "end": "17:00", "days": [0, 1, 2, 3, 4]}]
        },
    }
    with pytest.raises(InstanceError, match="cycle"):
        Instance.from_dict(raw)


def test_self_dependency_is_rejected():
    raw = {
        "scenario_id": "selfdep",
        "tasks": [{"task_id": "A", "duration": 1.0}],
        "dependencies": [["A", "A"]],
        "resources": [{"resource_id": "R1", "skills": {}}],
        "calendar_requirements": {
            "shifts": [{"name": "d", "start": "08:00", "end": "17:00", "days": [0]}]
        },
    }
    with pytest.raises(InstanceError, match="itself"):
        Instance.from_dict(raw)


def test_unknown_dependency_is_rejected():
    raw = {
        "scenario_id": "dangling",
        "tasks": [{"task_id": "A", "duration": 1.0}],
        "dependencies": [["A", "Z"]],
        "resources": [{"resource_id": "R1", "skills": {}}],
        "calendar_requirements": {
            "shifts": [{"name": "d", "start": "08:00", "end": "17:00", "days": [0]}]
        },
    }
    with pytest.raises(InstanceError, match="unknown task"):
        Instance.from_dict(raw)


def test_missing_top_level_key_is_rejected():
    with pytest.raises(InstanceError, match="missing required top-level key"):
        Instance.from_dict({"tasks": [], "resources": []})


def test_non_positive_duration_is_rejected():
    raw = {
        "scenario_id": "zero",
        "tasks": [{"task_id": "A", "duration": 0.0}],
        "dependencies": [],
        "resources": [{"resource_id": "R1", "skills": {}}],
        "calendar_requirements": {
            "shifts": [{"name": "d", "start": "08:00", "end": "17:00", "days": [0]}]
        },
    }
    with pytest.raises(InstanceError, match="non-positive duration"):
        Instance.from_dict(raw)
