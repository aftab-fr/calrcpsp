#!/usr/bin/env python3
"""What actually changes when a schedule is repaired? (Reviewer 1, point 7)

The submitted paper reported the repair time and the change in makespan. This
experiment opens that up and records, for every stored disruption record, how
many tasks move, how far they move, whether the resource assignment changes,
and how the critical path is redrawn.

Usage:
    python exp2_disruption_detail.py --dataset /path/to/data/scenarios
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

from calrcpsp import (
    __version__,
    assign_resources,
    compliance_report,
    disruption_from_spec,
    load_instance,
    precedence_violations,
    reschedule,
    resource_conflicts,
    solve,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default="../results/exp2_disruption_detail")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    print(f"calrcpsp {__version__}\n")
    print(f"{'instance':30s} {'disruption':20s} {'moved':>6} {'mean dt':>8} {'max dt':>8} "
          f"{'reasgn':>7} {'cp +/-':>8} {'mk %':>8}")
    print("-" * 100)

    for path in sorted(Path(args.dataset).glob("**/*.json")):
        instance = load_instance(path)
        assignment = assign_resources(instance)
        base = solve(instance, assignment=assignment)
        base_start = base.start_work_times
        base_res = dict(base.assignment.task_to_resource)
        base_cp = set(base.critical_path())

        for index, spec in enumerate(instance.disruptions):
            disruption = disruption_from_spec(spec, base)
            result = reschedule(base, disruption)
            new = result.schedule
            new_start = new.start_work_times
            new_cp = set(new.critical_path())

            shifts = [new_start[t] - base_start[t] for t in base_start
                      if abs(new_start[t] - base_start[t]) > 1e-9]
            reassigned = sum(1 for t, r in new.assignment.task_to_resource.items()
                             if base_res.get(t) != r)
            compliance = compliance_report(new)

            rows.append({
                "scenario_id": instance.scenario_id,
                "n_tasks": instance.n_tasks,
                "record_index": index,
                "disruption_type": spec.type,
                "severity": spec.severity,
                "applied_kind": disruption.kind,
                "target": disruption.target,
                "extra_hours": round(disruption.extra_hours, 4),
                "baseline_makespan": round(result.baseline_makespan, 4),
                "new_makespan": round(result.new_makespan, 4),
                "makespan_increase_pct": round(result.delta_percent, 4),
                "tasks_moved": len(shifts),
                "tasks_moved_pct": round(100.0 * len(shifts) / instance.n_tasks, 2),
                "start_shift_mean_h": round(statistics.mean(shifts), 4) if shifts else 0.0,
                "start_shift_median_h": round(statistics.median(shifts), 4) if shifts else 0.0,
                "start_shift_max_h": round(max(shifts), 4) if shifts else 0.0,
                "tasks_reassigned": reassigned,
                "critical_path_before": len(base_cp),
                "critical_path_after": len(new_cp),
                "critical_tasks_added": len(new_cp - base_cp),
                "critical_tasks_removed": len(base_cp - new_cp),
                "repair_ms": round(result.seconds * 1000, 3),
                "repaired_precedence_violations": len(precedence_violations(new)),
                "repaired_resource_conflicts": len(resource_conflicts(new)),
                "repaired_working_time_compliance": round(compliance.working_time, 6),
                "repaired_feasible": (not precedence_violations(new)
                                      and not resource_conflicts(new)
                                      and compliance.all_intervals_in_working_time),
            })
            r = rows[-1]
            print(f"{instance.scenario_id[:29]:30s} {spec.type[:19]:20s} "
                  f"{r['tasks_moved']:6d} {r['start_shift_mean_h']:8.2f} "
                  f"{r['start_shift_max_h']:8.2f} {r['tasks_reassigned']:7d} "
                  f"{r['critical_tasks_added']:3d}/{r['critical_tasks_removed']:<4d} "
                  f"{r['makespan_increase_pct']:7.2f}")

    csv_path = out_dir / "disruption_detail.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    moved_pct = [r["tasks_moved_pct"] for r in rows]
    shift_max = [r["start_shift_max_h"] for r in rows]
    summary = {
        "calrcpsp_version": __version__,
        "python": sys.version.split()[0],
        "records": len(rows),
        "all_repairs_feasible": all(r["repaired_feasible"] for r in rows),
        "records_with_no_task_moved": sum(1 for r in rows if r["tasks_moved"] == 0),
        "records_with_no_makespan_change": sum(1 for r in rows
                                               if r["makespan_increase_pct"] == 0.0),
        "tasks_reassigned_total": sum(r["tasks_reassigned"] for r in rows),
        "tasks_moved_pct": {
            "min": min(moved_pct), "max": max(moved_pct),
            "mean": round(statistics.mean(moved_pct), 2),
            "median": round(statistics.median(moved_pct), 2),
        },
        "start_shift_max_h": {
            "min": min(shift_max), "max": max(shift_max),
            "mean": round(statistics.mean(shift_max), 2),
        },
        "critical_path_changed_records": sum(
            1 for r in rows if r["critical_tasks_added"] or r["critical_tasks_removed"]),
    }
    (out_dir / "disruption_detail_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print("-" * 100)
    print(f"records {summary['records']}, all repairs feasible: {summary['all_repairs_feasible']}")
    print(f"tasks moved: {summary['tasks_moved_pct']['min']}% to "
          f"{summary['tasks_moved_pct']['max']}% of the instance "
          f"(mean {summary['tasks_moved_pct']['mean']}%)")
    print(f"largest start shift: {summary['start_shift_max_h']['max']} work-hours")
    print(f"tasks reassigned to a different resource: "
          f"{summary['tasks_reassigned_total']} (the repair keeps the assignment)")
    print(f"critical path changed on {summary['critical_path_changed_records']} records")
    print(f"\nwritten: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
