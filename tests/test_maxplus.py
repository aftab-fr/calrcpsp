"""Max-plus matrices, closure and the start-time recursion."""

from __future__ import annotations

import numpy as np
import pytest

from calrcpsp import (
    assign_resources,
    build_precedence_matrix,
    build_resource_matrix,
    closure,
    combine_matrices,
    earliest_start_times,
    load_instance,
    topological_order,
)


def _combined(instance):
    assignment = assign_resources(instance)
    order = topological_order(instance)
    matrix = combine_matrices(
        build_precedence_matrix(instance),
        build_resource_matrix(instance, assignment, order=order),
    )
    return matrix, order


def test_precedence_matrix_holds_predecessor_durations(tiny):
    matrix = build_precedence_matrix(tiny)
    for pred, succ in tiny.dependencies:
        i, j = tiny.index_of(pred), tiny.index_of(succ)
        assert matrix[i, j] == pytest.approx(tiny.task(pred).duration)
    assert np.isneginf(matrix).sum() == tiny.n_tasks**2 - len(tiny.dependencies)


def test_resource_matrix_chains_tasks_on_one_resource(tiny):
    assignment = assign_resources(tiny)
    matrix = build_resource_matrix(tiny, assignment)
    for members in assignment.groups().values():
        edges = sum(
            1
            for a in members
            for b in members
            if np.isfinite(matrix[tiny.index_of(a), tiny.index_of(b)])
        )
        # A chain over k tasks has exactly k - 1 edges.
        assert edges == max(len(members) - 1, 0)


def test_combine_takes_the_elementwise_maximum():
    a = np.array([[0.0, 2.0], [-np.inf, 0.0]])
    b = np.array([[1.0, -np.inf], [-np.inf, 3.0]])
    combined = combine_matrices(a, b)
    assert combined[0, 0] == 1.0
    assert combined[0, 1] == 2.0
    assert combined[1, 1] == 3.0


def test_combine_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        combine_matrices(np.zeros((2, 2)), np.zeros((3, 3)))


def test_closure_finds_the_longest_path():
    # A -> B -> C with durations 2 and 3, plus a direct A -> C of 1.
    matrix = np.full((3, 3), -np.inf)
    matrix[0, 1] = 2.0
    matrix[1, 2] = 3.0
    matrix[0, 2] = 1.0
    star = closure(matrix)
    assert star[0, 2] == pytest.approx(5.0)
    assert star[0, 0] == pytest.approx(0.0)


def test_closure_and_recursion_agree(instance_path):
    """The O(n^3) closure and the O(n + e) recursion give the same starts."""
    instance = load_instance(instance_path)
    matrix, order = _combined(instance)
    fast = earliest_start_times(matrix, order)

    star = closure(matrix)
    np.fill_diagonal(star, -np.inf)
    with np.errstate(invalid="ignore"):
        slow = np.max(star, axis=0)
    slow = np.maximum(np.where(np.isfinite(slow), slow, 0.0), 0.0)

    assert np.allclose(fast, slow, atol=1e-9)


def test_topological_order_respects_edges(instance_path):
    instance = load_instance(instance_path)
    order = topological_order(instance)
    position = {task: index for index, task in enumerate(order)}
    assert len(order) == instance.n_tasks
    for i, j in instance.edges():
        assert position[i] < position[j]
