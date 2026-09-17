"""Command line interface: ``calrcpsp <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .instance import InstanceError, load_instance, load_instances
from .metrics import validate_schedule
from .reschedule import disruption_from_spec, reschedule
from .scheduler import solve


def _collect(target: Path) -> list:
    if target.is_dir():
        return load_instances(target)
    return [load_instance(target)]


def _cmd_info(args: argparse.Namespace) -> int:
    for instance in _collect(Path(args.path)):
        print(
            f"{instance.scenario_id:38s} {instance.n_tasks:5d} tasks "
            f"{len(instance.dependencies):5d} deps {instance.n_resources:4d} resources "
            f"{instance.calendar.shift_type:14s} {len(instance.disruptions)} disruptions"
        )
    return 0


def _cmd_solve(args: argparse.Namespace) -> int:
    payload = []
    for instance in _collect(Path(args.path)):
        schedule = solve(instance, method=args.method)
        print(schedule.summary())
        print()
        payload.append(
            {"schedule": schedule.to_dict(), "validation": validate_schedule(schedule)}
        )
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"written: {args.json}")
    return 0


def _cmd_reschedule(args: argparse.Namespace) -> int:
    for instance in _collect(Path(args.path)):
        schedule = solve(instance, method=args.method)
        if not instance.disruptions:
            print(f"{instance.scenario_id}: no disruption records")
            continue
        print(f"{instance.scenario_id}: baseline makespan {schedule.makespan:.3f} work-hours")
        for spec in instance.disruptions:
            disruption = disruption_from_spec(spec, schedule)
            result = reschedule(schedule, disruption)
            print(
                f"  {spec.type:22s} {disruption.kind:16s} target={disruption.target:6s} "
                f"+{disruption.extra_hours:5.2f} h -> makespan {result.new_makespan:8.3f} "
                f"({result.delta_percent:+6.2f} %) in {result.seconds * 1000:7.2f} ms"
            )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    failures = 0
    for instance in _collect(Path(args.path)):
        schedule = solve(instance, method=args.method)
        report = validate_schedule(schedule)
        status = "PASS" if report["feasible"] else "FAIL"
        if not report["feasible"]:
            failures += 1
        print(
            f"[{status}] {instance.scenario_id:38s} "
            f"precedence={report['precedence_violations']} "
            f"conflicts={report['resource_conflicts']} "
            f"working-time={report['compliance']['working_time_compliance']:.4f}"
        )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="calrcpsp", description=__doc__)
    parser.add_argument("--version", action="version", version=f"calrcpsp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, handler, help_text in (
        ("info", _cmd_info, "list instances and their size"),
        ("solve", _cmd_solve, "schedule an instance or a directory of instances"),
        ("reschedule", _cmd_reschedule, "apply each stored disruption and repair"),
        ("validate", _cmd_validate, "check feasibility of the produced schedules"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("path", help="instance file or directory of instances")
        child.add_argument(
            "--method",
            choices=("topological", "closure"),
            default="topological",
            help="max-plus evaluation route (default: topological)",
        )
        if name == "solve":
            child.add_argument("--json", help="also write the full result to this file")
        child.set_defaults(func=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except InstanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
