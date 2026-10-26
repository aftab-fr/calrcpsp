"""Shared fixtures.

The six vendored instances are always used.  Set ``CALRCPSP_DATASET`` to a
copy of the full published deposit to run the same checks over all twelve.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from calrcpsp import load_instance, solve

FIXTURE_DIR = Path(__file__).parent / "data"


def _instance_paths() -> list[Path]:
    override = os.environ.get("CALRCPSP_DATASET")
    root = Path(override) if override else FIXTURE_DIR
    paths = sorted(root.glob("**/*.json"))
    if not paths:
        raise RuntimeError(f"no instance files under {root}")
    return paths


@pytest.fixture(scope="session")
def instance_paths() -> list[Path]:
    return _instance_paths()


@pytest.fixture(scope="session")
def instances(instance_paths):
    return [load_instance(p) for p in instance_paths]


@pytest.fixture(scope="session")
def tiny():
    return load_instance(FIXTURE_DIR / "tiny_manufacturing_demo.json")


@pytest.fixture(scope="session")
def schedules(instances):
    return [solve(inst) for inst in instances]


def pytest_generate_tests(metafunc):
    """Give every instance its own test case, named after the scenario."""
    if "instance_path" in metafunc.fixturenames:
        paths = _instance_paths()
        metafunc.parametrize("instance_path", paths, ids=[p.stem for p in paths])


#: Which marker each test module carries, so the suite can be reported by kind.
#: unit        one module, inputs built in the test
#: integration several modules together, a full solve or repair
#: benchmark   every instance the session can see, so it grows with the dataset
_KIND = {
    "test_calendar": "unit",
    "test_calendar_boundaries": "unit",
    "test_instance": "unit",
    "test_maxplus": "unit",
    "test_assignment": "unit",
    "test_schedule": "integration",
    "test_reschedule": "integration",
}


def pytest_collection_modifyitems(items):
    """Tag every test, so `-m unit`, `-m integration` and `-m benchmark` work.

    A test that is parametrised over the instance files is a benchmark run: it
    repeats for each instance and covers more as the dataset grows. Everything
    else keeps the kind of the module it lives in.
    """
    for item in items:
        module = item.module.__name__.rsplit(".", 1)[-1]
        kind = _KIND.get(module, "unit")
        if "instance_path" in getattr(item, "fixturenames", ()):
            kind = "benchmark"
        item.add_marker(getattr(pytest.mark, kind))
