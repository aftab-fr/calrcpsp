"""Repairing a schedule after a disruption."""

from __future__ import annotations

import pytest

from calrcpsp import (
    Disruption,
    InstanceError,
    disruption_from_spec,
    load_instance,
    precedence_violations,
    reschedule,
    resource_conflicts,
    solve,
    validate_schedule,
)


def test_reschedule_after_every_stored_disruption_is_feasible(instance_path):
    instance = load_instance(instance_path)
    baseline = solve(instance)
    assert instance.disruptions, "fixtures all carry disruption records"
    for spec in instance.disruptions:
        disruption = disruption_from_spec(spec, baseline)
        result = reschedule(baseline, disruption)
        report = validate_schedule(result.schedule)
        assert report["feasible"], f"{spec.type} produced an infeasible schedule"
        assert precedence_violations(result.schedule) == []
        assert resource_conflicts(result.schedule) == []


def test_disruption_never_shortens_the_project(instance_path):
    instance = load_instance(instance_path)
    baseline = solve(instance)
    for spec in instance.disruptions:
        result = reschedule(baseline, disruption_from_spec(spec, baseline))
        assert result.new_makespan >= baseline.makespan - 1e-9
        assert result.delta_hours >= -1e-9


def test_calendar_compliance_survives_rescheduling(instance_path):
    instance = load_instance(instance_path)
    baseline = solve(instance)
    for spec in instance.disruptions:
        result = reschedule(baseline, disruption_from_spec(spec, baseline))
        calendar = result.schedule.calendar
        for task in result.schedule.tasks:
            for begin, end in task.segments:
                assert calendar.is_working_time(begin + (end - begin) / 2)


def test_delaying_a_critical_task_moves_the_makespan(tiny):
    baseline = solve(tiny)
    critical = baseline.critical_path()[0]
    result = reschedule(baseline, Disruption.task_delay(critical, 2.0))
    assert result.new_makespan == pytest.approx(baseline.makespan + 2.0)
    assert result.delta_percent > 0


def test_delay_inside_the_slack_does_not_move_the_makespan(tiny):
    baseline = solve(tiny)
    slack = baseline.slack()
    relaxed = max(
        (t for t in baseline.tasks if not t.critical), key=lambda t: slack[t.task_id]
    )
    margin = slack[relaxed.task_id] / 2
    assert margin > 0
    result = reschedule(baseline, Disruption.task_delay(relaxed.task_id, margin))
    assert result.new_makespan == pytest.approx(baseline.makespan)


def test_resource_outage_targets_the_first_task_on_that_resource(tiny):
    baseline = solve(tiny)
    busiest = max(
        baseline.by_resource().items(), key=lambda kv: sum(t.duration for t in kv[1])
    )[0]
    result = reschedule(baseline, Disruption.resource_outage(busiest, 1.0))
    assert result.new_makespan >= baseline.makespan
    assert result.disruption.kind == "resource_outage"


def test_outage_on_an_idle_resource_is_an_error(tiny):
    baseline = solve(tiny)
    used = {t.resource_id for t in baseline.tasks}
    idle = [r.resource_id for r in tiny.resources if r.resource_id not in used]
    if not idle:
        pytest.skip("every resource is in use in this instance")
    with pytest.raises(InstanceError, match="performs no task"):
        reschedule(baseline, Disruption.resource_outage(idle[0], 1.0))


def test_targeting_rule_is_deterministic(tiny):
    baseline = solve(tiny)
    for spec in tiny.disruptions:
        first = disruption_from_spec(spec, baseline)
        second = disruption_from_spec(spec, baseline)
        assert first == second


def test_repaired_schedule_keeps_the_same_assignment(tiny):
    baseline = solve(tiny)
    result = reschedule(baseline, Disruption.task_delay(tiny.tasks[0].task_id, 1.0))
    assert result.schedule.assignment.task_to_resource == baseline.assignment.task_to_resource
    assert result.schedule.project_start == baseline.project_start
