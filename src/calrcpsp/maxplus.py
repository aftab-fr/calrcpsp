"""Max-plus matrices and the earliest-start recursion.

The max-plus semiring replaces addition by maximum and multiplication by
addition.  A scheduling problem becomes a matrix whose entry ``A[i, j]``
is the least amount of work that must elapse between the start of task
``i`` and the start of task ``j``.  Every weight in this module is in
work-hours.

The calendar is deliberately not folded into these matrices.  How much
calendar time a task consumes depends on when it starts, so it cannot be
written as a constant matrix entry.  The calendar is applied afterwards,
exactly, as a change of time base through ``W`` and ``W_inverse``.  See
:mod:`calrcpsp.calendar`.

Both routes to the earliest start times are provided and they agree:

``closure``
    the Kleene closure of the matrix, computed by a max-plus
    Floyd-Warshall in ``O(n^3)``.  Faithful to the algebra and useful for
    inspecting longest paths between any pair of tasks.
``earliest_start_times``
    the same result from the state recursion ``x = A^T (x) x`` evaluated
    in topological order, in ``O(n + e)``.  This is what the solver uses,
    because the graph is acyclic and the answer is identical.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from .assignment import Assignment
from .instance import Instance, InstanceError

__all__ = [
    "NEG_INF",
    "build_precedence_matrix",
    "build_resource_matrix",
    "combine_matrices",
    "closure",
    "topological_order",
    "earliest_start_times",
    "latest_start_times",
]

#: The max-plus zero element.
NEG_INF = -np.inf


def build_precedence_matrix(instance: Instance) -> np.ndarray:
    """Matrix of precedence edges, ``A[i, j] = duration(i)`` for ``i -> j``."""
    n = instance.n_tasks
    matrix = np.full((n, n), NEG_INF)
    durations = instance.durations()
    for i, j in instance.edges():
        if durations[i] > matrix[i, j]:
            matrix[i, j] = durations[i]
    return matrix


def topological_order(instance: Instance) -> list[int]:
    """Kahn topological order of the task indices."""
    n = instance.n_tasks
    indegree = [0] * n
    succ: list[list[int]] = [[] for _ in range(n)]
    for i, j in instance.edges():
        succ[i].append(j)
        indegree[j] += 1
    queue = [i for i in range(n) if indegree[i] == 0]
    order: list[int] = []
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        order.append(node)
        for child in succ[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != n:
        raise InstanceError("dependency graph is not acyclic")
    return order


def build_resource_matrix(
    instance: Instance, assignment: Assignment, order: list[int] | None = None
) -> np.ndarray:
    """Matrix of resource-sharing edges.

    Tasks assigned to the same resource cannot overlap, because the
    published format gives every resource unit capacity.  They are
    serialised in topological order, which keeps the combined graph
    acyclic.  Only consecutive pairs in that order get an edge: the
    closure recovers every other pair, so an ``O(k)`` chain replaces the
    ``O(k^2)`` complete order without changing the result.
    """
    n = instance.n_tasks
    matrix = np.full((n, n), NEG_INF)
    order = order if order is not None else topological_order(instance)
    rank = {task: position for position, task in enumerate(order)}
    durations = instance.durations()

    chains: dict[str, list[int]] = {}
    for index, task in enumerate(instance.tasks):
        chains.setdefault(assignment.resource_of(task.task_id), []).append(index)

    for members in chains.values():
        members.sort(key=lambda idx: (rank[idx], idx))
        for first, second in pairwise(members):
            if durations[first] > matrix[first, second]:
                matrix[first, second] = durations[first]
    return matrix


def combine_matrices(*matrices: np.ndarray) -> np.ndarray:
    """Max-plus sum of matrices, that is the elementwise maximum."""
    if not matrices:
        raise ValueError("combine_matrices needs at least one matrix")
    shape = matrices[0].shape
    for matrix in matrices[1:]:
        if matrix.shape != shape:
            raise ValueError("cannot combine matrices of different shapes")
    out = matrices[0].copy()
    for matrix in matrices[1:]:
        np.maximum(out, matrix, out=out)
    return out


def closure(matrix: np.ndarray) -> np.ndarray:
    """Max-plus Kleene closure by Floyd-Warshall, with zeros on the diagonal.

    Entry ``(i, j)`` of the result is the longest path in work-hours from
    task ``i`` to task ``j``.  Cost is ``O(n^3)``; for large instances
    prefer :func:`earliest_start_times`, which returns the same start
    vector far more cheaply.
    """
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("closure expects a square matrix")
    out = matrix.copy()
    np.fill_diagonal(out, np.maximum(np.diagonal(out), 0.0))
    n = out.shape[0]
    with np.errstate(invalid="ignore"):
        for k in range(n):
            column = out[:, k : k + 1]
            row = out[k : k + 1, :]
            candidate = column + row
            np.maximum(out, candidate, out=out)
    return out


def earliest_start_times(
    matrix: np.ndarray, order: list[int]
) -> np.ndarray:
    """Earliest start of every task, in work-hours from the project start.

    Evaluates ``x_j = max(0, max_i (x_i + A[i, j]))`` in topological
    order, which is the max-plus state recursion run to its fixed point in
    a single pass.
    """
    n = matrix.shape[0]
    starts = np.zeros(n, dtype=float)
    finite = np.isfinite(matrix)
    for i in order:
        targets = np.flatnonzero(finite[i])
        if targets.size == 0:
            continue
        candidate = starts[i] + matrix[i, targets]
        # Fancy indexing returns a copy, so assign the result back.
        starts[targets] = np.maximum(starts[targets], candidate)
    return starts


def latest_start_times(
    matrix: np.ndarray, order: list[int], durations: np.ndarray, horizon: float
) -> np.ndarray:
    """Latest start of every task that still meets ``horizon``.

    Backward pass over the same graph.  ``horizon`` is normally the
    makespan, so the difference between the latest and earliest start is
    the total float of each task.
    """
    n = matrix.shape[0]
    latest = np.full(n, horizon, dtype=float) - durations
    finite = np.isfinite(matrix)
    for i in reversed(order):
        targets = np.flatnonzero(finite[i])
        if targets.size == 0:
            continue
        bound = float(np.min(latest[targets] - matrix[i, targets]))
        if bound < latest[i]:
            latest[i] = bound
    return latest
