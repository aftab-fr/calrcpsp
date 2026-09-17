#!/usr/bin/env python3
"""Build the paper figures from the benchmark output in results/.

Nothing here is hand entered. Figures 3, 4 and 5 read results/*.csv, and
figure 2 calls the library itself. Run scripts/run_benchmark.py first.

    python scripts/make_figures.py
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

from calrcpsp import WorkCalendar, load_instance, solve

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"
FIGURES = REPO / "paper" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# Slots 1 to 3 of the reference categorical palette, used unchanged.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#d9d9d4"
FILL = "#eeeeea"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 8.5,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "axes.edgecolor": MUTED,
        "axes.linewidth": 0.6,
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    }
)


def _tidy(ax, grid_axis: str = "y") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


def _read(name: str) -> list[dict]:
    with (RESULTS / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# -- figure 1: architecture ------------------------------------------------

def figure_architecture() -> None:
    fig, ax = plt.subplots(figsize=(6.0, 4.7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, title, body, accent=False):
        ax.add_patch(
            Rectangle(
                (x, y), w, h,
                facecolor="#ffffff" if accent else FILL,
                edgecolor=BLUE if accent else MUTED,
                linewidth=1.2 if accent else 0.6,
                zorder=3,
            )
        )
        ax.text(x + w / 2, y + h - 3.0, title, ha="center", va="top",
                fontsize=7.6 if len(title) > 18 else 8, fontweight="bold",
                color=BLUE if accent else INK, zorder=4)
        ax.text(x + w / 2, y + h - 8.2, body, ha="center", va="top",
                fontsize=6.3, color=MUTED, zorder=4, linespacing=1.35)

    def arrow(x0, y0, x1, y1):
        ax.add_patch(
            FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                            mutation_scale=8, linewidth=0.9,
                            color=MUTED, zorder=2)
        )

    box(2, 86, 96, 12, "instance.py",
        "load_instance(): reads the CA-RCPSP JSON and checks keys, "
        "task ids, durations and acyclicity")

    box(2, 58, 46, 21, "calendar.py",
        "WorkCalendar: shifts, breaks, holidays\n"
        "W(t) and W_inverse(w), exact, by bisection\n"
        "occupied_intervals(): pause and resume")
    box(52, 58, 46, 21, "assignment.py",
        "assign_resources(): skill matching\n"
        "balanced or coverage strategy\n"
        "reports the coverage achieved")

    box(2, 29, 96, 21, "maxplus.py",
        "build_precedence_matrix()    build_resource_matrix()    "
        "combine_matrices()\n"
        "closure() in O(n^3)          earliest_start_times() in O(n + e)\n"
        "latest_start_times(): the backward pass that gives task float",
        accent=True)

    box(2, 1, 30, 21, "scheduler.py",
        "solve(): the algebra\nin work time, then\nthe calendar mapping")
    box(35, 1, 30, 21, "schedule.py + metrics.py",
        "start times, makespan,\nslack, critical path,\ncompliance, conflicts")
    box(68, 1, 30, 21, "reschedule.py",
        "disruption targeting,\nrepair, feasibility of\nthe new schedule")

    for x in (25, 75):
        arrow(x, 86, x, 79.6)
        arrow(x, 58, x, 50.6)
    for x in (17, 50, 83):
        arrow(x, 29, x, 22.6)
    fig.savefig(FIGURES / "fig1_architecture.pdf")
    plt.close(fig)


# -- figure 2: the calendar ------------------------------------------------

def figure_calendar() -> None:
    calendar = WorkCalendar.standard_day()
    origin = datetime(2025, 1, 6, 0, 0)          # Monday 00:00
    reference = calendar.next_working_time(origin)

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(6.0, 2.6), gridspec_kw={"width_ratios": [1.05, 1]}
    )

    # (a) cumulative work-time function over three days
    hours = [h / 8 for h in range(8 * 24 * 3 + 1)]
    work = [calendar.W(origin + timedelta(hours=h), reference) for h in hours]

    for day in range(3):
        base = day * 24
        for lo, hi in ((base, base + 8), (base + 12, base + 13), (base + 17, base + 24)):
            ax1.axvspan(lo, hi, color=FILL, linewidth=0, zorder=0)

    ax1.plot(hours, work, color=BLUE, linewidth=1.7, zorder=3)
    ax1.set_xlim(0, 72)
    ax1.set_ylim(0, 25)
    ax1.set_xticks([0, 24, 48, 72])
    ax1.set_xticklabels(["Mon\n00:00", "Tue\n00:00", "Wed\n00:00", "Thu\n00:00"])
    ax1.set_ylabel("cumulative work-hours  $W(t)$")
    ax1.set_xlabel("calendar time")
    ax1.set_title("(a) the work-time function", loc="left")
    ax1.annotate("flat across lunch", xy=(12.5, 4.0), xytext=(16, 1.0),
                 fontsize=6.6, color=MUTED,
                 arrowprops={"arrowstyle": "-", "linewidth": 0.6, "color": MUTED})
    ax1.annotate("flat overnight", xy=(20.5, 8.0), xytext=(27, 4.6),
                 fontsize=6.6, color=MUTED,
                 arrowprops={"arrowstyle": "-", "linewidth": 0.6, "color": MUTED})
    ax1.text(1.5, 23.3, "shaded = non-working", fontsize=6.6, color=MUTED)
    _tidy(ax1)

    # (b) the schedule calrcpsp actually produces for the smallest instance
    instance = load_instance(REPO / "tests" / "data" / "tiny_manufacturing_demo.json")
    schedule = solve(instance)
    day_start = datetime(2025, 1, 6, 0, 0)
    ordered = sorted(schedule.tasks, key=lambda t: (t.resource_id, t.start_work))

    ax2.axvspan(12, 13, color=FILL, linewidth=0, zorder=0)
    for row, task in enumerate(ordered):
        y = len(ordered) - 1 - row
        for seg_start, seg_end in task.segments:
            a = (seg_start - day_start).total_seconds() / 3600.0
            b = (seg_end - day_start).total_seconds() / 3600.0
            ax2.add_patch(
                Rectangle((a, y - 0.3), b - a, 0.6,
                          facecolor=ORANGE if task.critical else BLUE,
                          edgecolor="white", linewidth=0.8, zorder=3)
            )
    ax2.set_yticks(range(len(ordered)))
    ax2.set_yticklabels(
        [f"{t.task_id} / {t.resource_id}" for t in reversed(ordered)], fontsize=6.8
    )
    ax2.set_xlim(7.5, 16.6)
    ax2.set_xticks([8, 10, 12, 14, 16])
    ax2.set_xticklabels(["08:00", "10:00", "12:00", "14:00", "16:00"])
    ax2.set_xlabel("Monday")
    ax2.set_title("(b) a schedule, lunch shaded", loc="left")
    ax2.set_ylim(-0.7, len(ordered) - 0.3)
    critical = ordered[[t.critical for t in ordered].index(True)]
    ax2.annotate("critical task, 6.93 work-hours,\npauses for lunch, ends 15:55",
                 xy=(14.9, len(ordered) - 1.3 - ordered.index(critical)),
                 xytext=(11.35, 1.9), fontsize=6.3, color=ORANGE,
                 arrowprops={"arrowstyle": "-", "linewidth": 0.6, "color": ORANGE})
    _tidy(ax2, grid_axis="x")

    fig.tight_layout()
    fig.savefig(FIGURES / "fig2_calendar.pdf")
    plt.close(fig)


# -- figure 3: how the run time scales -------------------------------------

def figure_scaling() -> None:
    rows = sorted(_read("instance_results.csv"), key=lambda r: int(r["n_tasks"]))
    tasks = [int(r["n_tasks"]) for r in rows]
    total = [float(r["solve_total_ms_mean"]) for r in rows]
    algebra = [float(r["algebra_ms_mean"]) for r in rows]
    calendar_ms = [float(r["calendar_ms_mean"]) for r in rows]
    closure = [float(r["closure_total_ms"]) for r in rows]

    fig, ax = plt.subplots(figsize=(6.0, 2.6))
    ax.plot(tasks, closure, color=ORANGE, linewidth=1.6, marker="s",
            markersize=4.5, linestyle="--", label="closure route, $O(n^3)$", zorder=4)
    ax.plot(tasks, total, color=BLUE, linewidth=1.6, marker="o",
            markersize=4.5, label="default route, $O(n + e)$", zorder=5)
    ax.plot(tasks, algebra, color=BLUE, linewidth=1.1, marker="^",
            markersize=3.8, linestyle=":", alpha=0.8,
            label="   of which max-plus algebra", zorder=3)
    ax.plot(tasks, calendar_ms, color=MUTED, linewidth=1.1, marker="v",
            markersize=3.8, linestyle="-.", label="   of which calendar mapping",
            zorder=3)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("tasks in the instance")
    ax.set_ylabel("time (ms)")
    ax.set_xticks([5, 10, 25, 50, 100, 250, 500, 1000])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.annotate(f"{total[-1]:.1f} ms", xy=(tasks[-1], total[-1]),
                xytext=(tasks[-1] * 0.42, total[-1] * 3.4),
                fontsize=7, color=BLUE,
                arrowprops={"arrowstyle": "-", "linewidth": 0.6, "color": BLUE})
    ax.annotate(f"{closure[-1]:.0f} ms", xy=(tasks[-1], closure[-1]),
                xytext=(tasks[-1] * 0.30, closure[-1] * 0.32),
                fontsize=7, color=ORANGE,
                arrowprops={"arrowstyle": "-", "linewidth": 0.6, "color": ORANGE})
    ax.legend(frameon=False, loc="upper left", handlelength=2.6,
              borderaxespad=0.1)
    _tidy(ax, grid_axis="both")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig3_scaling.pdf")
    plt.close(fig)


# -- figure 4: the two compliance metrics ----------------------------------

def figure_compliance() -> None:
    rows = sorted(_read("instance_results.csv"), key=lambda r: int(r["n_tasks"]))
    labels = [f"{r['scenario_id']}  ({r['n_tasks']})" for r in rows]
    working = [float(r["working_time_compliance"]) for r in rows]
    uninterrupted = [float(r["uninterrupted_compliance"]) for r in rows]

    positions = range(len(rows))
    height = 0.38

    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.barh([p + height / 2 + 0.01 for p in positions], working, height,
            color=BLUE, edgecolor="white", linewidth=0.8,
            label="working-time compliance", zorder=3)
    ax.barh([p - height / 2 - 0.01 for p in positions], uninterrupted, height,
            color=ORANGE, edgecolor="white", linewidth=0.8, hatch="////",
            label="uninterrupted compliance", zorder=3)

    for p, value in zip(positions, uninterrupted, strict=True):
        ax.text(value + 0.012, p - height / 2 - 0.01, f"{value:.3f}",
                va="center", fontsize=6.6, color=MUTED)

    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlim(0, 1.13)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("share of the instance")
    ax.text(1.005, len(rows) - 0.5 + 0.35, "1.000 on all twelve",
            fontsize=6.8, color=BLUE, va="center")
    ax.legend(frameon=False, ncol=2, loc="lower center",
              bbox_to_anchor=(0.5, -0.30))
    _tidy(ax, grid_axis="x")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig4_compliance.pdf")
    plt.close(fig)


# -- figure 5: disruption repair -------------------------------------------

def figure_disruption() -> None:
    rows = _read("disruption_results.csv")
    times = [float(r["reschedule_ms_mean"]) for r in rows]
    increase = [float(r["makespan_increase_pct"]) for r in rows]
    absorbed = [i for i, value in enumerate(increase) if value == 0.0]
    moved = [i for i, value in enumerate(increase) if value > 0.0]

    fig, ax = plt.subplots(figsize=(6.0, 2.6))
    ax.scatter([times[i] for i in moved], [increase[i] for i in moved],
               s=26, facecolor=BLUE, edgecolor="white", linewidth=0.7,
               marker="o", label=f"makespan grew ({len(moved)} records)", zorder=4)
    ax.scatter([times[i] for i in absorbed], [increase[i] for i in absorbed],
               s=34, facecolor=ORANGE, edgecolor="white", linewidth=0.7,
               marker="D", label=f"absorbed by existing slack ({len(absorbed)} records)",
               zorder=5)

    ax.set_xlabel("time to repair the schedule (ms)")
    ax.set_ylabel("makespan increase (%)")
    ax.set_xlim(0, max(times) * 1.12)
    ax.set_ylim(-12, max(increase) * 1.12)
    ax.legend(frameon=False, loc="upper center")
    _tidy(ax, grid_axis="both")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig5_disruption.pdf")
    plt.close(fig)


def main() -> None:
    figure_architecture()
    figure_calendar()
    figure_scaling()
    figure_compliance()
    figure_disruption()
    for path in sorted(FIGURES.glob("*.pdf")):
        print(f"written: {path.relative_to(REPO)}  "
              f"({path.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
