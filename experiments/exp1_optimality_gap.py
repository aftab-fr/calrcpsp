#!/usr/bin/env python3
"""How far from optimal is the schedule calrcpsp returns? (Reviewer 1, point 5)

calrcpsp fixes two things before the algebra runs. It picks one resource per
task, and it serialises the tasks sharing a resource in topological order.
Given both choices the max-plus closure is exact, so the makespan it returns is
a feasible upper bound rather than an optimum. This experiment measures how
loose that bound is, by solving the same instances exactly with CP-SAT.

Two gaps are measured separately, because they come from different choices:

  sequencing gap   CP-SAT keeps the assignment calrcpsp chose and is free to
                   order the tasks on each resource. This isolates the cost of
                   the topological-order rule alone.

  full gap         CP-SAT chooses the assignment as well, from the resources
                   holding at least one of the skills the task requires, which
                   is the same eligibility rule the balanced strategy uses.
                   This is the cost of both heuristics together.

Both models work in work-hours, the same space the max-plus recursion uses.
The calendar mapping W^-1 is non-decreasing, so a shorter work-time makespan
always maps to an earlier or equal calendar finish, and comparing in work-time
is therefore sound.

Usage:
    python exp1_optimality_gap.py --dataset /path/to/data/scenarios
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from ortools.sat.python import cp_model

from calrcpsp import __version__, assign_resources, load_instance, solve

SCALE = 100  # work-hours -> integer work-centihours


def _scaled(instance):
    return [max(1, round(t.duration * SCALE)) for t in instance.tasks]


def _eligible(instance):
    """Resources holding at least one required skill, the balanced rule."""
    out = []
    for task in instance.tasks:
        req = set(task.required_skills)
        pool = [j for j, r in enumerate(instance.resources) if req & set(r.skills)]
        out.append(pool or list(range(instance.n_resources)))
    return out


def cpsat_fixed_assignment(instance, assignment, time_limit: float):
    """Optimal sequencing, assignment held at what calrcpsp chose."""
    n = instance.n_tasks
    dur = _scaled(instance)
    horizon = sum(dur)

    model = cp_model.CpModel()
    start = [model.new_int_var(0, horizon, f"s{i}") for i in range(n)]
    end = [model.new_int_var(0, horizon, f"e{i}") for i in range(n)]
    iv = [model.new_interval_var(start[i], dur[i], end[i], f"i{i}") for i in range(n)]

    for p, s in instance.edges():
        model.add(end[p] <= start[s])

    groups: dict[str, list[int]] = {}
    for i, task in enumerate(instance.tasks):
        groups.setdefault(assignment.resource_of(task.task_id), []).append(i)
    for members in groups.values():
        if len(members) > 1:
            model.add_no_overlap([iv[i] for i in members])

    makespan = model.new_int_var(0, horizon, "mk")
    model.add_max_equality(makespan, end)
    model.minimize(makespan)
    return _run(model, makespan, time_limit)


def cpsat_free_assignment(instance, time_limit: float):
    """Optimal assignment and sequencing, subject to skill eligibility."""
    n = instance.n_tasks
    m = instance.n_resources
    dur = _scaled(instance)
    horizon = sum(dur)
    pools = _eligible(instance)

    model = cp_model.CpModel()
    start = [model.new_int_var(0, horizon, f"s{i}") for i in range(n)]
    end = [model.new_int_var(0, horizon, f"e{i}") for i in range(n)]
    for i in range(n):
        model.add(end[i] == start[i] + dur[i])

    on = {}
    per_resource: dict[int, list] = {j: [] for j in range(m)}
    for i in range(n):
        lits = []
        for j in pools[i]:
            lit = model.new_bool_var(f"x{i}_{j}")
            on[(i, j)] = lit
            lits.append(lit)
            per_resource[j].append(
                model.new_optional_interval_var(start[i], dur[i], end[i], lit, f"o{i}_{j}")
            )
        model.add_exactly_one(lits)
    for j in range(m):
        if len(per_resource[j]) > 1:
            model.add_no_overlap(per_resource[j])

    for p, s in instance.edges():
        model.add(end[p] <= start[s])

    makespan = model.new_int_var(0, horizon, "mk")
    model.add_max_equality(makespan, end)
    model.minimize(makespan)
    return _run(model, makespan, time_limit, choice=(on, instance))


def _coverage(instance, picked) -> float:
    """Mean share of each task's required skills held by the resource it got."""
    total = 0.0
    for i, task in enumerate(instance.tasks):
        req = task.required_skills
        if not req:
            total += 1.0
            continue
        held = instance.resources[picked[i]].skills
        total += sum(1 for sk in req if sk in held) / len(req)
    return total / instance.n_tasks


def _run(model, objective, time_limit: float, choice=None):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    begin = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - begin
    name = solver.status_name(status)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        out = {
            "status": name,
            "makespan": solver.value(objective) / SCALE,
            "bound": solver.best_objective_bound / SCALE,
            "seconds": elapsed,
            "coverage": None,
        }
        if choice is not None:
            on, instance = choice
            picked = {}
            for (i, j), lit in on.items():
                if solver.value(lit):
                    picked[i] = j
            out["coverage"] = _coverage(instance, picked)
        return out
    return {"status": name, "makespan": None, "bound": None,
            "seconds": elapsed, "coverage": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--max-tasks", type=int, default=200,
                    help="skip instances larger than this (default 200)")
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--out", default="../results/exp1_optimality_gap")
    args = ap.parse_args(argv)

    paths = sorted(Path(args.dataset).glob("**/*.json"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"calrcpsp {__version__}  |  CP-SAT time limit {args.time_limit:.0f} s per model\n")
    print(f"{'instance':34s} {'n':>5} {'calrcpsp':>9} {'seq opt':>9} {'gap%':>7} "
          f"{'free opt':>9} {'gap%':>7}  status")
    print("-" * 104)

    for path in paths:
        instance = load_instance(path)
        if instance.n_tasks > args.max_tasks:
            continue
        begin = time.perf_counter()
        assignment = assign_resources(instance)
        schedule = solve(instance, assignment=assignment)
        ours_total_ms = (time.perf_counter() - begin) * 1000
        ours = schedule.makespan

        fixed = cpsat_fixed_assignment(instance, assignment, args.time_limit)
        free = cpsat_free_assignment(instance, args.time_limit)

        def gap(ref, ours=ours):
            """Percent by which our makespan exceeds the reference."""
            if ref is None or ref <= 0:
                return None
            return round(100.0 * (ours - ref) / ref, 2)

        row = {
            "scenario_id": instance.scenario_id,
            "n_tasks": instance.n_tasks,
            "n_resources": instance.n_resources,
            "calrcpsp_makespan": round(ours, 4),
            "calrcpsp_algebra_ms": round(schedule.solve_seconds * 1000, 3),
            "calrcpsp_total_ms": round(ours_total_ms, 3),
            "calrcpsp_coverage": round(assignment.mean_coverage, 4),
            "seq_opt_makespan": None if fixed["makespan"] is None else round(fixed["makespan"], 4),
            "seq_opt_bound": None if fixed["bound"] is None else round(fixed["bound"], 4),
            "seq_opt_status": fixed["status"],
            "seq_opt_seconds": round(fixed["seconds"], 3),
            "seq_gap_pct": gap(fixed["makespan"]),
            "free_opt_makespan": None if free["makespan"] is None else round(free["makespan"], 4),
            "free_opt_bound": None if free["bound"] is None else round(free["bound"], 4),
            "free_opt_status": free["status"],
            "free_opt_seconds": round(free["seconds"], 3),
            "free_gap_pct": gap(free["makespan"]),
            "free_opt_coverage": None if free["coverage"] is None else round(free["coverage"], 4),
        }
        rows.append(row)
        print(f"{instance.scenario_id:34s} {instance.n_tasks:5d} {ours:9.2f} "
              f"{row['seq_opt_makespan'] or float('nan'):9.2f} "
              f"{row['seq_gap_pct'] if row['seq_gap_pct'] is not None else float('nan'):7.2f} "
              f"{row['free_opt_makespan'] or float('nan'):9.2f} "
              f"{row['free_gap_pct'] if row['free_gap_pct'] is not None else float('nan'):7.2f}"
              f"  {fixed['status']}/{free['status']}")

    csv_path = out_dir / "optimality_gap.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    seq = [r["seq_gap_pct"] for r in rows if r["seq_gap_pct"] is not None]
    fre = [r["free_gap_pct"] for r in rows if r["free_gap_pct"] is not None]
    summary = {
        "environment": {
            "calrcpsp": __version__,
            "python": sys.version.split()[0],
            "ortools": getattr(cp_model, "__version__", "see requirements"),
            "platform": platform.platform(),
            "time_limit_s": args.time_limit,
        },
        "instances": len(rows),
        "sequencing_gap_pct": {
            "proved_optimal": sum(1 for r in rows if r["seq_opt_status"] == "OPTIMAL"),
            "min": min(seq) if seq else None,
            "max": max(seq) if seq else None,
            "mean": round(statistics.mean(seq), 2) if seq else None,
            "median": round(statistics.median(seq), 2) if seq else None,
        },
        "full_gap_pct": {
            "proved_optimal": sum(1 for r in rows if r["free_opt_status"] == "OPTIMAL"),
            "min": min(fre) if fre else None,
            "max": max(fre) if fre else None,
            "mean": round(statistics.mean(fre), 2) if fre else None,
            "median": round(statistics.median(fre), 2) if fre else None,
        },
    }
    (out_dir / "optimality_gap_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print("-" * 104)
    seq_s = summary["sequencing_gap_pct"]
    print(f"sequencing gap: mean {seq_s['mean']}%  "
          f"range {seq_s['min']} to {seq_s['max']}%  "
          f"({seq_s['proved_optimal']}/{len(rows)} proved optimal)")
    print(f"full gap      : mean {summary['full_gap_pct']['mean']}%  "
          f"range {summary['full_gap_pct']['min']} to {summary['full_gap_pct']['max']}%  "
          f"({summary['full_gap_pct']['proved_optimal']}/{len(rows)} proved optimal)")
    print(f"\nwritten: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
