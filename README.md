# calrcpsp

**Calendar-aware resource-constrained project scheduling in Python.**

[![tests](https://github.com/aftab-fr/calrcpsp/actions/workflows/tests.yml/badge.svg)](https://github.com/aftab-fr/calrcpsp/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)

---

## Purpose

Most project scheduling tools assume that once a task starts, work continues
without interruption. Real shop floors do not behave that way. Machines and
people follow shifts, stop for lunch, go home at night, rest at weekends and
observe public holidays. How long a task really takes therefore depends on
*when* it starts.

`calrcpsp` schedules projects where that matters. It:

- reads the published **CA-RCPSP** benchmark JSON format directly, where the
  work calendar is stored as a first-class object alongside the task graph and
  the resource pool;
- converts between calendar time and work time exactly, through a cumulative
  work-time function `W(t)` and its inverse;
- builds **max-plus** scheduling matrices for precedence and for resource
  sharing, and solves them;
- returns start times, makespan, task slack, the critical path and calendar
  compliance;
- repairs a schedule after a disruption.

Every step is callable on its own, so you can use only the calendar, only the
matrices, or the whole pipeline.

The benchmark format it reads comes from:

> M. A. Uddin, J. Gaber, P. Petitjean, F. Cortinovis.
> *An expert-informed multi-scale synthetic benchmark dataset for
> calendar-aware resource-constrained project scheduling (CA-RCPSP).*
> Data in Brief **69** (2026) 113256.
> [doi:10.1016/j.dib.2026.113256](https://doi.org/10.1016/j.dib.2026.113256)
> Data: [doi:10.5281/zenodo.20553817](https://doi.org/10.5281/zenodo.20553817)

`calrcpsp` is independent software. It is not required to use that dataset, and
the dataset is not required to use `calrcpsp`: any JSON following the same
schema works, and calendars can be built in code.

---

## Install

```bash
python -m pip install calrcpsp
```

From source:

```bash
git clone https://github.com/aftab-fr/calrcpsp.git
cd calrcpsp
python -m pip install -e ".[test]"
pytest
```

Requires Python 3.10 or newer. The only runtime dependency is NumPy.
`requirements-lock.txt` holds the exact versions this release was tested with.

---

## Ten line example

```python
from calrcpsp import load_instance, solve, compliance_report

instance = load_instance("tests/data/tiny_manufacturing_demo.json")
schedule = solve(instance)

print(schedule.makespan)                       # 6.93 work-hours
print(schedule.start_times()["T006"])          # 2025-01-06 08:00:00
print(schedule.task("T006").end)               # 2025-01-06 15:55:48
print(schedule.slack()["T001"])                # 4.67 work-hours of float
print(schedule.critical_path())                # ('T006',)
print(compliance_report(schedule).working_time)        # 1.0
print(compliance_report(schedule).uninterrupted)       # 0.833
```

`T006` needs 6.93 hours of work. It starts at 08:00 and finishes at 15:55, not
at 14:56, because the hour of lunch does not count as work.

### Command line

```bash
calrcpsp info      path/to/scenarios      # list instances and their size
calrcpsp solve     instance.json          # schedule and print a summary
calrcpsp validate  path/to/scenarios      # check every schedule is feasible
calrcpsp reschedule instance.json         # apply each stored disruption
```

---

## What each piece does on its own

```python
from datetime import datetime
from calrcpsp import (
    load_instance, WorkCalendar, assign_resources,
    build_precedence_matrix, build_resource_matrix, combine_matrices,
    closure, solve, reschedule, Disruption,
)

instance = load_instance("instance.json")

# 1. The calendar, on its own.
calendar = WorkCalendar.from_spec(instance.calendar)
start = calendar.next_working_time(datetime(2025, 1, 6, 0, 0))
calendar.W(datetime(2025, 1, 7, 10, 0), start)   # work-hours elapsed
calendar.W_inverse(12.5, start)                  # when 12.5 work-hours are done

# 2. Resource assignment, on its own.
assignment = assign_resources(instance, strategy="balanced")

# 3. The max-plus matrices, on their own.
A = build_precedence_matrix(instance)            # precedence edges
R = build_resource_matrix(instance, assignment)  # resource sharing edges
M = combine_matrices(A, R)                       # max-plus sum
star = closure(M)                                # longest path between any pair

# 4. Solve, then repair after a disruption.
schedule = solve(instance)
result = reschedule(schedule, Disruption.task_delay("T004", extra_hours=3.0))
result.new_makespan, result.delta_percent, result.seconds
```

You can also supply your own calendar instead of the one in the file:

```python
from calrcpsp import ShiftSpec, WorkCalendar
from datetime import date

night_shop = WorkCalendar(
    shifts=[
        ShiftSpec("day",     "06:00", "14:00", (0, 1, 2, 3, 4)),
        ShiftSpec("evening", "14:00", "22:00", (0, 1, 2, 3, 4)),
        ShiftSpec("night",   "22:00", "06:00", (0, 1, 2, 3, 4)),
    ],
    lunch_break=None,
    holidays=[date(2025, 12, 25)],
)
schedule = solve(instance, calendar=night_shop)
```

---

## Input format

An instance is a single JSON object. These keys are read:

| Key | Required | Meaning |
|---|---|---|
| `scenario_id` | no | identifier, defaults to `unnamed` |
| `tasks` | **yes** | list of tasks |
| `dependencies` | no | list of `[predecessor, successor]` task-id pairs forming a DAG |
| `resources` | **yes** | list of machines and workers |
| `calendar_requirements` | **yes** | shifts, break and holidays |
| `disruptions` | no | disruption records |
| `expected_performance` | no | kept but never used by the solver |

A task:

```json
{ "task_id": "T001", "task_type": "processing", "duration": 1.72,
  "required_skills": ["cnc_operation"], "priority": 1 }
```

`duration` is in **work-hours**, not elapsed hours.

A resource:

```json
{ "resource_id": "M001", "name": "Saw 1", "resource_type": "Machine",
  "skills": { "cutting": 0.9, "machining": 0.75 },
  "cost_per_hour": 39.61, "efficiency": 0.814 }
```

A calendar:

```json
{ "shift_type": "standard_day",
  "shifts": [{ "name": "day", "start": "08:00", "end": "17:00",
               "days": [0, 1, 2, 3, 4] }],
  "lunch_break": { "start": "12:00", "end": "13:00" },
  "holidays": ["2025-01-01", "2025-05-01", "2025-07-14", "2025-12-25"] }
```

`days` uses Python weekday numbers, Monday is 0. An `end` at or before `start`
means the shift runs past midnight, so `"17:00"` to `"01:00"` is an evening
shift finishing the next morning.

Loading fails with a clear `InstanceError` on a missing key, a duplicate task
id, a dependency pointing at a task that does not exist, a non-positive
duration, or a cycle in the dependency graph.

---

## How the calendar is handled

Durations are work-hours. The max-plus recursion runs entirely in work time,
and the calendar is applied afterwards as an exact change of time base through
`W` and `W_inverse`. The calendar is deliberately **not** folded into the
matrices: how much calendar time a task consumes depends on when it starts, so
it cannot be written as a constant matrix entry.

A task runs only during working periods, and it may **pause and resume**. A
three hour task starting on Friday at 15:00 works two hours before the shift
ends and finishes the last hour on Monday morning. `TaskSchedule.segments` lists
the periods actually occupied.

Because of that, calendar compliance is reported two ways and both are printed:

| Metric | Question | Result on the 12 published instances |
|---|---|---|
| `working_time` | what share of scheduled work falls inside working periods? | **1.000 on all 12** |
| `uninterrupted` | what share of tasks never cross a non-working period? | 0.440 to 1.000 |

The first is the correctness property, and the test suite asserts it. The
second is stricter and lower by design: a scheduler that lets tasks pause over
lunch cannot score 1.0 on it unless the calendar has no breaks at all. Quoting
only one of the two numbers would be misleading, so `calrcpsp` always gives
both.

---

## What this library does not do

These are limits of the model or of the data, and nothing is stubbed out to
hide them:

- **Unit capacity only.** The published format has no capacity field, so each
  resource performs one task at a time.
- **One resource per task.** Some tasks require a skill set that no single
  resource holds: between 3 and 179 tasks per published instance. The
  assignment reports the coverage it achieved (`Assignment.mean_coverage`,
  `Assignment.fully_covered`) instead of pretending the task is fully staffed.
- **No transition or setup times.** The format stores no `w_ij`, so edge
  weights are the predecessor duration alone.
- **No maintenance windows, deadlines or task priorities.** The format either
  omits these or leaves them `null` in every deposited instance.
- **Rescheduling is a full re-solve**, not an incremental matrix update. On
  these instances a repair takes under 19 ms, so the simpler and more clearly
  correct route was kept.
- **No solver comparison.** `calrcpsp` reports its own behaviour. It ships no
  CP or MIP baseline.

---

## Results on the published dataset

Produced by `scripts/run_benchmark.py` on the twelve deposited instances.
Raw output is in [`results/`](results/). Machine: Apple arm64, macOS 26.6.2,
Python 3.13.2, NumPy 2.2.6. Solve times are the mean of 5 repeats.

| Instance | Tasks | Makespan (work-h) | Solve (ms) | Utilisation | Working-time | Uninterrupted |
|---|---:|---:|---:|---:|---:|---:|
| tiny_quality_demo | 5 | 5.91 | 1.04 | 0.331 | 1.000 | 0.800 |
| tiny_manufacturing_demo | 6 | 6.93 | 1.62 | 0.393 | 1.000 | 0.833 |
| tiny_assembly_demo | 8 | 11.59 | 1.64 | 0.392 | 1.000 | 0.500 |
| small_disrupted_manufacturing_25 | 25 | 20.76 | 2.42 | 0.431 | 1.000 | 0.440 |
| small_multi_resource_35 | 35 | 20.26 | 2.82 | 0.461 | 1.000 | 0.457 |
| small_shift_operations_40 | 40 | 17.63 | 3.21 | 0.540 | 1.000 | 0.800 |
| medium_complex_manufacturing_120 | 120 | 34.34 | 6.28 | 0.487 | 1.000 | 0.483 |
| medium_multi_shift_factory_150 | 150 | 63.51 | 6.57 | 0.352 | 1.000 | 0.667 |
| medium_supply_chain_180 | 180 | 57.31 | 6.48 | 0.401 | 1.000 | 0.478 |
| large_industrial_scale_500 | 500 | 46.92 | 15.95 | 0.769 | 1.000 | 0.692 |
| large_enterprise_manufacturing_750 | 750 | 76.32 | 17.57 | 0.668 | 1.000 | 0.688 |
| large_mega_scale_factory_1000 | 1000 | 92.88 | 15.26 | 0.769 | 1.000 | 1.000 |

All 12 instances solved. All 12 schedules are feasible: no precedence
violation, no resource double booking, and every scheduled interval inside
working time. No failures and no timeouts against a 3600 s budget.

All 34 stored disruption records were applied and repaired, and all 34 repaired
schedules are feasible. Repair takes 0.78 ms to 17.09 ms. The makespan increase
ranges from 0.0 % to 258.4 %; five of the 34 records are absorbed entirely by
existing slack and move the makespan not at all.

Reproduce it:

```bash
python scripts/run_benchmark.py --dataset /path/to/carm-plus-dataset/data/scenarios
```

Without `--dataset` it runs on the six instances vendored in `tests/data/`.

---

## Reproducing a published result

The dataset article reports that all twelve instances pass nine structural
integrity checks, and that each instance regenerates exactly from its stored
seed. Both are reproducible from the dataset repository, and `calrcpsp` then
confirms that all twelve are also solvable:

```bash
# 1. Get the published deposit.
git clone https://github.com/aftab-fr/carm-plus-dataset.git
cd carm-plus-dataset
python -m pip install -r requirements.txt

# 2. Regenerate all twelve instances from their seeds and re-validate.
python code/generate_all_scenarios.py     # rewrites the 12 JSON files
python code/validate_dataset.py           # expect: all 12 [PASS]

# 3. Schedule them with calrcpsp.
cd ..
calrcpsp validate carm-plus-dataset/data/scenarios   # expect: 12 x [PASS]
```

Step 2 reproduces the published claim. Regenerating the instances gives files
identical to the deposited ones apart from the `generated_at` timestamp, and
all twelve pass all nine checks.

Note that the solver comparison table in the dataset article is **not**
reproducible from published code, and `calrcpsp` does not attempt to reproduce
it. Its numbers came from solver runs whose source was not deposited, and the
article itself states that the table is an ingestion compatibility check rather
than a performance benchmark, from which no solver ranking should be inferred.
All numbers in this README come from `scripts/run_benchmark.py`.

---

## Testing

```bash
pytest                                                    # 6 vendored instances
CALRCPSP_DATASET=/path/to/data/scenarios pytest           # all 12
```

219 tests on the vendored fixtures, 387 on the full deposit. They check:

- `W` and `W_inverse` round trip, stay monotonic, skip breaks, nights,
  weekends and holidays, and handle shifts that cross midnight;
- every scheduled interval of every task lies inside working time, and the
  segments account for the full task duration;
- precedence is never violated, in work time and in calendar time;
- no resource is ever double booked;
- the `O(n^3)` Kleene closure and the `O(n + e)` recursion give identical
  start times on every instance;
- a hand-built chain matches a pen-and-paper answer, including the lunch break;
- pinned makespans for six instances do not drift;
- every stored disruption produces a feasible repaired schedule whose makespan
  never decreases, and compliance survives the repair.

CI runs the suite on Linux, macOS and Windows, on Python 3.10 to 3.13.

---

## Citing

See [`CITATION.cff`](CITATION.cff). Please also cite the dataset article above
if you use the CA-RCPSP instances.

## Licence

MIT. See [`LICENSE.txt`](LICENSE.txt).

The six JSON instances in `tests/data/` come from the CA-RCPSP dataset and are
redistributed under CC BY 4.0 with attribution; see `tests/data/SOURCE.md`.
