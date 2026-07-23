from __future__ import annotations

import threading

from megachud.runtime.activity import ActivityTracker, submit_tracked


def test_idle_snapshot():
    tracker = ActivityTracker()
    snap = tracker.snapshot()
    assert snap["active"] is False
    assert snap["in_flight"] == 0
    assert snap["working_seconds"] is None
    assert snap["uptime_seconds"] >= 0


def test_tracked_marks_active_then_idle():
    tracker = ActivityTracker()
    with tracker.tracked():
        snap = tracker.snapshot()
        assert snap["active"] is True
        assert snap["in_flight"] == 1
        assert snap["working_seconds"] is not None
    after = tracker.snapshot()
    assert after["active"] is False
    assert after["in_flight"] == 0
    assert after["working_seconds"] is None


def test_nested_tracked_counts_concurrent_work():
    tracker = ActivityTracker()
    with tracker.tracked():
        with tracker.tracked():
            assert tracker.snapshot()["in_flight"] == 2
        assert tracker.snapshot()["in_flight"] == 1
    assert tracker.snapshot()["in_flight"] == 0


def test_tracked_decrements_even_on_exception():
    tracker = ActivityTracker()
    try:
        with tracker.tracked():
            raise ValueError("boom")
    except ValueError:
        pass
    assert tracker.snapshot()["in_flight"] == 0


def test_submit_tracked_runs_and_tracks(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    tracker = ActivityTracker()
    executor = ThreadPoolExecutor(max_workers=1)
    started = threading.Event()
    release = threading.Event()
    seen_in_flight = []

    def work():
        started.set()
        release.wait(timeout=2)
        return "done"

    future = submit_tracked(executor, tracker, work)
    started.wait(timeout=2)
    seen_in_flight.append(tracker.snapshot()["in_flight"])
    release.set()
    assert future.result(timeout=2) == "done"
    executor.shutdown(wait=True)

    assert seen_in_flight == [1]
    assert tracker.snapshot()["in_flight"] == 0
