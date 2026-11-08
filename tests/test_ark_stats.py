import sqlite3

from src.ark_stats import ArkStatsStore, discord_timestamp, format_duration


def test_presentation_formats_durations_and_timezone_aware_timestamps():
    assert format_duration(120) == "2 minutes"
    assert format_duration(4500) == "1 hour 15 minutes"
    assert format_duration(183600) == "2 days 3 hours"
    assert discord_timestamp("2026-01-01T00:00:00+00:00") == "<t:1767225600:f>"
    assert discord_timestamp("2026-01-01T00:00:00Z") == "<t:1767225600:f>"
    assert discord_timestamp(None) is None
    assert discord_timestamp("2026-01-01T00:00:00") is None


def test_snapshot_baseline_and_bounded_accumulation(tmp_path):
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.record_snapshot({"id:a": "Alice"}, now_mono=100, now_wall="2026-01-01T00:00:00+00:00")
    store.record_snapshot({"id:a": "Alice", "id:b": "Bob"}, now_mono=110, now_wall="2026-01-01T00:00:10+00:00")
    store.record_snapshot({"id:b": "Bobby"}, now_mono=210, now_wall="2026-01-01T00:01:00+00:00")
    rows = {row[0]: row for row in store.stats()}
    assert rows["id:a"][2] == 10
    assert rows["id:b"][2] == 30
    assert rows["id:b"][1] == "Bobby"
    assert rows["id:b"][3] == "2026-01-01T00:01:00+00:00"


def test_missing_polls_and_restart_do_not_add_time(tmp_path):
    path = tmp_path / "stats.sqlite3"
    store = ArkStatsStore(path)
    store.record_snapshot({"id:a": "Alice"}, now_mono=1, now_wall="t1")
    store.record_snapshot({"id:a": "Alice"}, now_mono=11, now_wall="t2")
    store.close()
    reopened = ArkStatsStore(path)
    reopened.record_snapshot({"id:a": "Alice"}, now_mono=1000, now_wall="t3")
    assert reopened.stats("id:a")[2] == 10


def test_leave_join_duplicate_and_reset_boundary(tmp_path):
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.record_snapshot({"id:a": "Alice"}, now_mono=0, now_wall="t0")
    store.record_snapshot({"id:a": "Alice"}, now_mono=10, now_wall="t1")
    store.record_snapshot({"id:a": "Alice"}, now_mono=10, now_wall="t1")
    store.record_snapshot({}, now_mono=20, now_wall="t2")
    assert store.stats("id:a")[2] == 10
    store.reset()
    store.record_snapshot({"id:a": "Alice"}, now_mono=100, now_wall="t3")
    assert store.stats("id:a")[2] == 0


def test_schema_is_private_and_future_death_columns_exist(tmp_path):
    path = tmp_path / "stats.sqlite3"
    store = ArkStatsStore(path)
    columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(players)")}
    assert {"total_deaths", "last_death_cause"} <= columns
    assert store.tracking_started()
