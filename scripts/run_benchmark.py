#!/usr/bin/env python3
"""Run calrcpsp over a directory of CA-RCPSP instances and record what happens.

Every number this script writes comes from an actual run on the machine it
is executed on.  Nothing is copied from a paper.  Failures, timeouts and
infeasible results are written out with the same weight as successes.

Usage::

    python scripts/run_benchmark.py --dataset /path/to/data/scenarios
    python scripts/run_benchmark.py --dataset ... --repeats 10 --timeout 3600

Outputs, all under ``results/``:

``instance_results.csv``    one row per instance
``disruption_results.csv``  one row per stored disruption record
``benchmark_summary.json``  environment, totals and per-scale aggregates
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

from calrcpsp import (
    __version__,
    assign_resources,
    compliance_report,
    disruption_from_spec,
    load_instance,
    precedence_violations,
    reschedule,
    resource_conflicts,
    resource_utilization,
    solve,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS = REPO_ROOT / "results"


def _environment(args: argparse.Namespace) -> dict:
    return {
        "calrcpsp_version": __version__,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "timeout_seconds": args.timeout,
        "assignment_strategy": args.strategy,
    }


def _time_solve(
    instance, strategy: str, method: str, repeats: int
) -> tuple[list[float], list[float], list[float]]:
    """Solve ``repeats`` times and return total, algebra and calendar timings."""
    totals, algebra, calendar = [], [], []
    for _ in range(repeats):
        assignment = assign_resources(instance, strategy)
        begin = time.perf_counter()
        schedule = solve(instance, assignment=assignment, method=method)
        totals.append(time.perf_counter() - begin)
        algebra.append(schedule.solve_seconds)
        calendar.append(schedule.calendar_seconds)
    return totals, algebra, calendar


def run(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    paths = sorted(dataset.glob("**/*.json"))
    if not paths:
        print(f"error: no instance files under {dataset}", file=sys.stderr)
        return 2

    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    disruption_rows: list[dict] = []
    failures: list[dict] = []

    print(f"calrcpsp {__version__}: {len(paths)} instances from {dataset}")
    print(f"{'instance':38s} {'n':>5} {'makespan':>10} {'solve ms':>9} "
          f"{'cal ms':>8} {'util':>6} {'strict':>7} status")
    print("-" * 100)

    for path in paths:
        record: dict = {"file": path.name, "scenario_id": path.stem}
        try:
            instance = load_instance(path)
            assignment = assign_resources(instance, args.strategy)
            schedule = solve(instance, assignment=assignment, method=args.method)

            totals, algebra, calendar_times = _time_solve(
                instance, args.strategy, args.method, args.repeats
            )
            compliance = compliance_report(schedule)
            utilisation = resource_utilization(schedule)
            precedence = precedence_violations(schedule)
            conflicts = resource_conflicts(schedule)
            timed_out = max(totals) > args.timeout

            record.update(
                {
                    "scenario_id": instance.scenario_id,
                    "scale": instance.scale,
                    "n_tasks": instance.n_tasks,
                    "n_dependencies": len(instance.dependencies),
                    "n_resources": instance.n_resources,
                    "shift_type": instance.calendar.shift_type,
                    "n_holidays": len(instance.calendar.holidays),
                    "solved": True,
                    "timed_out": timed_out,
                    "makespan_work_hours": round(schedule.makespan, 4),
                    "elapsed_calendar_hours": round(schedule.elapsed_hours, 4),
                    "project_start": schedule.project_start.isoformat(),
                    "project_end": schedule.end.isoformat(),
                    "total_task_work_hours": round(instance.total_work_hours(), 4),
                    "solve_total_ms_mean": round(1000 * statistics.mean(totals), 4),
                    "solve_total_ms_std": round(
                        1000 * (statistics.stdev(totals) if len(totals) > 1 else 0.0), 4
                    ),
                    "algebra_ms_mean": round(1000 * statistics.mean(algebra), 4),
                    "calendar_ms_mean": round(1000 * statistics.mean(calendar_times), 4),
                    "critical_path_tasks": len(schedule.critical_path()),
                    "mean_slack_work_hours": round(
                        statistics.mean([t.slack for t in schedule.tasks]), 4
                    ),
                    "max_slack_work_hours": round(max(t.slack for t in schedule.tasks), 4),
                    "mean_utilization": round(utilisation["mean"], 4),
                    "available_work_hours": round(utilisation["available_work_hours"], 4),
                    "working_time_compliance": round(compliance.working_time, 6),
                    "uninterrupted_compliance": round(compliance.uninterrupted, 6),
                    "n_interrupted_tasks": compliance.n_interrupted,
                    "all_intervals_in_working_time": compliance.all_intervals_in_working_time,
                    "precedence_violations": len(precedence),
                    "resource_conflicts": len(conflicts),
                    "feasible": not precedence
                    and not conflicts
                    and compliance.all_intervals_in_working_time,
                    "skill_coverage_mean": round(assignment.mean_coverage, 4),
                    "tasks_fully_skill_covered": assignment.fully_covered,
                    "n_disruption_records": len(instance.disruptions),
                    "error": "",
                }
            )

            if args.closure:
                try:
                    begin = time.perf_counter()
                    closure_schedule = solve(
                        instance, assignment=assignment, method="closure"
                    )
                    record["closure_total_ms"] = round(
                        1000 * (time.perf_counter() - begin), 4
                    )
                    record["closure_matches_topological"] = bool(
                        abs(closure_schedule.makespan - schedule.makespan) < 1e-9
                    )
                except Exception as exc:  # pragma: no cover - reported, not raised
                    record["closure_total_ms"] = ""
                    record["closure_matches_topological"] = f"error: {exc}"

            for index, spec in enumerate(instance.disruptions):
                drow = {
                    "scenario_id": instance.scenario_id,
                    "scale": instance.scale,
                    "n_tasks": instance.n_tasks,
                    "record_index": index,
                    "disruption_type": spec.type,
                    "severity": spec.severity,
                    "spec_duration_hours": spec.duration_hours,
                }
                try:
                    disruption = disruption_from_spec(spec, schedule)
                    result = reschedule(schedule, disruption)
                    repair_times = [result.seconds]
                    repair_times.extend(
                        reschedule(schedule, disruption).seconds
                        for _ in range(max(args.repeats - 1, 0))
                    )
                    repaired_precedence = precedence_violations(result.schedule)
                    repaired_conflicts = resource_conflicts(result.schedule)
                    repaired_compliance = compliance_report(result.schedule)
                    drow.update(
                        {
                            "applied_kind": disruption.kind,
                            "target": disruption.target,
                            "extra_hours": round(disruption.extra_hours, 4),
                            "baseline_makespan": round(result.baseline_makespan, 4),
                            "new_makespan": round(result.new_makespan, 4),
                            "makespan_increase_hours": round(result.delta_hours, 4),
                            "makespan_increase_pct": round(result.delta_percent, 4),
                            "tasks_moved": result.affected_tasks,
                            "reschedule_ms_mean": round(
                                1000 * statistics.mean(repair_times), 4
                            ),
                            "reschedule_ms_std": round(
                                1000
                                * (
                                    statistics.stdev(repair_times)
                                    if len(repair_times) > 1
                                    else 0.0
                                ),
                                4,
                            ),
                            "repaired_precedence_violations": len(repaired_precedence),
                            "repaired_resource_conflicts": len(repaired_conflicts),
                            "repaired_working_time_compliance": round(
                                repaired_compliance.working_time, 6
                            ),
                            "repaired_feasible": not repaired_precedence
                            and not repaired_conflicts
                            and repaired_compliance.all_intervals_in_working_time,
                            "error": "",
                        }
                    )
                except Exception as exc:  # pragma: no cover - reported, not raised
                    drow.update({"repaired_feasible": False, "error": repr(exc)})
                    failures.append(
                        {
                            "scenario_id": instance.scenario_id,
                            "stage": f"disruption[{index}] {spec.type}",
                            "error": repr(exc),
                            "traceback": traceback.format_exc(),
                        }
                    )
                disruption_rows.append(drow)

            status = "ok" if record["feasible"] else "INFEASIBLE"
            if timed_out:
                status += " TIMEOUT"
            print(
                f"{instance.scenario_id:38s} {instance.n_tasks:5d} "
                f"{record['makespan_work_hours']:10.2f} "
                f"{record['solve_total_ms_mean']:9.2f} "
                f"{record['calendar_ms_mean']:8.2f} "
                f"{record['mean_utilization']:6.3f} "
                f"{record['uninterrupted_compliance']:7.3f} {status}"
            )

        except Exception as exc:  # pragma: no cover - reported, not raised
            record.update({"solved": False, "feasible": False, "error": repr(exc)})
            failures.append(
                {
                    "scenario_id": path.stem,
                    "stage": "solve",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            print(f"{path.stem:38s} {'':5} {'':>10} {'':>9} {'':>8} {'':>6} {'':>7} FAILED: {exc}")

        rows.append(record)

    # -- write csv files ---------------------------------------------------

    def write_csv(name: str, records: list[dict]) -> Path:
        target = results_dir / name
        if not records:
            target.write_text("", encoding="utf-8")
            return target
        fields: list[str] = []
        for record in records:
            for key in record:
                if key not in fields:
                    fields.append(key)
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for record in records:
                writer.writerow({key: record.get(key, "") for key in fields})
        return target

    instance_csv = write_csv("instance_results.csv", rows)
    disruption_csv = write_csv("disruption_results.csv", disruption_rows)

    # -- summary -----------------------------------------------------------

    solved = [r for r in rows if r.get("solved")]
    feasible = [r for r in solved if r.get("feasible")]
    by_scale: dict[str, dict] = {}
    for record in solved:
        scale = record.get("scale") or "unknown"
        bucket = by_scale.setdefault(
            scale, {"instances": 0, "makespan": [], "solve_ms": [],
                    "utilization": [], "uninterrupted": []}
        )
        bucket["instances"] += 1
        bucket["makespan"].append(record["makespan_work_hours"])
        bucket["solve_ms"].append(record["solve_total_ms_mean"])
        bucket["utilization"].append(record["mean_utilization"])
        bucket["uninterrupted"].append(record["uninterrupted_compliance"])

    for bucket in by_scale.values():
        for key in ("makespan", "solve_ms", "utilization", "uninterrupted"):
            values = bucket.pop(key)
            bucket[f"{key}_mean"] = round(statistics.mean(values), 4)
            bucket[f"{key}_min"] = round(min(values), 4)
            bucket[f"{key}_max"] = round(max(values), 4)

    repaired = [d for d in disruption_rows if not d.get("error")]
    summary = {
        "environment": _environment(args),
        "dataset": str(dataset),
        "totals": {
            "instances_found": len(rows),
            "instances_solved": len(solved),
            "instances_feasible": len(feasible),
            "instances_failed": len(rows) - len(solved),
            "instances_timed_out": sum(1 for r in solved if r.get("timed_out")),
            "disruption_records": len(disruption_rows),
            "disruptions_repaired": len(repaired),
            "disruptions_failed": len(disruption_rows) - len(repaired),
            "repaired_all_feasible": all(
                d.get("repaired_feasible") for d in repaired
            )
            if repaired
            else None,
        },
        "aggregates": {
            "working_time_compliance_min": min(
                (r["working_time_compliance"] for r in solved), default=None
            ),
            "uninterrupted_compliance_min": min(
                (r["uninterrupted_compliance"] for r in solved), default=None
            ),
            "uninterrupted_compliance_max": max(
                (r["uninterrupted_compliance"] for r in solved), default=None
            ),
            "solve_ms_min": min((r["solve_total_ms_mean"] for r in solved), default=None),
            "solve_ms_max": max((r["solve_total_ms_mean"] for r in solved), default=None),
            "reschedule_ms_min": min(
                (d["reschedule_ms_mean"] for d in repaired), default=None
            ),
            "reschedule_ms_max": max(
                (d["reschedule_ms_mean"] for d in repaired), default=None
            ),
            "makespan_increase_pct_min": min(
                (d["makespan_increase_pct"] for d in repaired), default=None
            ),
            "makespan_increase_pct_max": max(
                (d["makespan_increase_pct"] for d in repaired), default=None
            ),
            "skill_coverage_mean_min": min(
                (r["skill_coverage_mean"] for r in solved), default=None
            ),
        },
        "by_scale": by_scale,
        "failures": failures,
    }

    summary_path = results_dir / "benchmark_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("-" * 100)
    print(
        f"solved {len(solved)}/{len(rows)}, feasible {len(feasible)}/{len(rows)}, "
        f"failed {len(rows) - len(solved)}, timed out "
        f"{summary['totals']['instances_timed_out']}"
    )
    print(
        f"disruptions repaired {len(repaired)}/{len(disruption_rows)}, "
        f"all repairs feasible: {summary['totals']['repaired_all_feasible']}"
    )
    print(f"written: {instance_csv}")
    print(f"written: {disruption_csv}")
    print(f"written: {summary_path}")
    return 0 if len(feasible) == len(rows) and not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(REPO_ROOT / "tests" / "data"),
        help="directory of CA-RCPSP JSON instances (searched recursively)",
    )
    parser.add_argument("--results", default=str(DEFAULT_RESULTS), help="output directory")
    parser.add_argument("--repeats", type=int, default=5, help="timing repeats per instance")
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="wall-clock budget per solve, in seconds; exceeding it is recorded, "
        "not interrupted",
    )
    parser.add_argument("--strategy", default="balanced", choices=("balanced", "coverage"))
    parser.add_argument("--method", default="topological", choices=("topological", "closure"))
    parser.add_argument(
        "--closure",
        action="store_true",
        help="also solve by Kleene closure and check that both routes agree",
    )
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
