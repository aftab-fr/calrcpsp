"""Feasibility of the schedules the solver produces.

These are the four properties the library promises: work only happens in
working time, precedence always holds, resources never double book, and a
known instance keeps a stable makespan.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from calrcpsp import (
    Instance,
    WorkCalendar,
    assign_resources,
    compliance_report,
    load_instance,
    precedence_violations,
    resource_conflicts,
    resource_utilization,
    solve,
    validate_schedule,
)

# -- calendar compliance -------------------------------------------------

def test_every_scheduled_interval_is_working_time(instance_path):
    schedule = solve(load_instance(instance_path))
    calendar = schedule.calendar
    for task in schedule.tasks:
        assert task.segments, f"{task.task_id} has no scheduled interval"
        for begin, end in task.segments:
            assert end > begin
            assert calendar.is_working_time(begin)
            midpoint = begin + (end - begin) / 2
            assert calendar.is_working_time(midpoint), (
                f"{task.task_id} occupies non-working time at {midpoint}"
            )


def test_segments_account_for_the_whole_duration(instance_path):
    schedule = solve(load_instance(instance_path))
    for task in schedule.tasks:
        covered = sum((b - a).total_seconds() / 3600.0 for a, b in task.segments)
        assert covered == pytest.approx(task.duration, abs=1e-6)


def test_working_time_compliance_is_total(instance_path):
    report = compliance_report(solve(load_instance(instance_path)))
    assert report.all_intervals_in_working_time
    assert report.working_time == pytest.approx(1.0, abs=1e-9)


def test_uninterrupted_compliance_is_reported_even_when_below_one(instance_path):
    """Tasks may pause over a break. The stricter metric must still be a number."""
    report = compliance_report(solve(load_instance(instance_path)))
    assert 0.0 <= report.uninterrupted <= 1.0
    assert report.n_interrupted + round(report.uninterrupted * report.n_tasks) == report.n_tasks


# -- precedence and resources -------------------------------------------

def test_precedence_is_never_violated(instance_path):
    schedule = solve(load_instance(instance_path))
    assert precedence_violations(schedule) == []


def test_precedence_holds_in_calendar_time_too(instance_path):
    schedule = solve(load_instance(instance_path))
    starts = schedule.start_times()
    ends = {t.task_id: t.end for t in schedule.tasks}
    for pred, succ in schedule.instance.dependencies:
        assert starts[succ] >= ends[pred]


def test_no_resource_is_double_booked(instance_path):
    schedule = solve(load_instance(instance_path))
    assert resource_conflicts(schedule) == []


def test_schedule_validates(instance_path):
    report = validate_schedule(solve(load_instance(instance_path)))
    assert report["feasible"]
    assert report["precedence_violations"] == 0
    assert report["resource_conflicts"] == 0


# -- slack and critical path --------------------------------------------

def test_slack_is_non_negative_and_critical_tasks_have_none(instance_path):
    schedule = solve(load_instance(instance_path))
    for task in schedule.tasks:
        assert task.slack >= -1e-9
        if task.critical:
            assert task.slack == pytest.approx(0.0, abs=1e-9)
    assert schedule.critical_path(), "every schedule has at least one critical task"


def test_critical_path_spans_the_makespan(instance_path):
    schedule = solve(load_instance(instance_path))
    critical = [t for t in schedule.tasks if t.critical]
    assert max(t.end_work for t in critical) == pytest.approx(schedule.makespan)
    assert min(t.start_work for t in critical) == pytest.approx(0.0)


def test_utilisation_is_a_fraction(instance_path):
    utilisation = resource_utilization(solve(load_instance(instance_path)))
    assert 0.0 <= utilisation["mean"] <= 1.0


# -- a known instance ----------------------------------------------------

def _hand_instance() -> Instance:
    """Three tasks in a chain, one resource each, so the answer is obvious."""
    return Instance.from_dict(
        {
            "scenario_id": "hand_built",
            "tasks": [
                {"task_id": "A", "duration": 2.0, "required_skills": ["x"]},
                {"task_id": "B", "duration": 3.0, "required_skills": ["y"]},
                {"task_id": "C", "duration": 1.0, "required_skills": ["z"]},
            ],
            "dependencies": [["A", "B"], ["B", "C"]],
            "resources": [
                {"resource_id": "R1", "resource_type": "Machine", "skills": {"x": 1.0}},
                {"resource_id": "R2", "resource_type": "Machine", "skills": {"y": 1.0}},
                {"resource_id": "R3", "resource_type": "Machine", "skills": {"z": 1.0}},
            ],
            "calendar_requirements": {
                "shift_type": "standard_day",
                "shifts": [
                    {"name": "day", "start": "08:00", "end": "17:00",
                     "days": [0, 1, 2, 3, 4]}
                ],
                "lunch_break": {"start": "12:00", "end": "13:00"},
                "holidays": [],
            },
        }
    )


def test_hand_built_chain_matches_a_pen_and_paper_answer():
    schedule = solve(_hand_instance())
    assert schedule.makespan == pytest.approx(6.0)
    starts = schedule.start_times()
    assert starts["A"] == datetime(2025, 1, 6, 8, 0)
    assert starts["B"] == datetime(2025, 1, 6, 10, 0)
    # B runs 10:00 to 14:00 with an hour of lunch in the middle, so C starts at 14:00.
    assert starts["C"] == datetime(2025, 1, 6, 14, 0)
    assert schedule.task("C").end == datetime(2025, 1, 6, 15, 0)
    assert schedule.critical_path() == ("A", "B", "C")


#: Regression values produced by this implementation, not taken from any paper.
KNOWN_MAKESPANS = {
    "tiny_manufacturing_demo": 6.93,
    "tiny_assembly_demo": 11.59,
    "tiny_quality_demo": 5.91,
    "small_disrupted_manufacturing_25": 20.76,
    "small_multi_resource_35": 20.26,
    "small_shift_operations_40": 17.63,
}


def test_small_known_instance_has_a_stable_makespan(instance_path):
    instance = load_instance(instance_path)
    expected = KNOWN_MAKESPANS.get(instance.scenario_id)
    if expected is None:
        pytest.skip(f"no pinned makespan for {instance.scenario_id}")
    assert solve(instance).makespan == pytest.approx(expected, abs=5e-3)


def test_solving_twice_gives_the_same_answer(tiny):
    first, second = solve(tiny), solve(tiny)
    assert first.makespan == second.makespan
    assert first.start_times() == second.start_times()
    assert first.critical_path() == second.critical_path()


def test_both_methods_agree(instance_path):
    instance = load_instance(instance_path)
    assert solve(instance, method="topological").makespan == pytest.approx(
        solve(instance, method="closure").makespan
    )


def test_custom_calendar_and_assignment_are_honoured(tiny):
    calendar = WorkCalendar.continuous()
    schedule = solve(tiny, calendar=calendar, assignment=assign_resources(tiny, "coverage"))
    assert schedule.calendar.name == "continuous"
    assert schedule.assignment.strategy == "coverage"
    # With no breaks at all, no task can be interrupted.
    assert compliance_report(schedule).uninterrupted == pytest.approx(1.0)
