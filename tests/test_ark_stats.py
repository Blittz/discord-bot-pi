import sqlite3
from pathlib import Path

from src.ark_stats import ArkStatsStore, discover_server_name, discord_timestamp, format_duration, parse_death_line, parse_server_start_line


FIXTURE = Path(__file__).parent / "fixtures/ark_deaths.log"


def test_death_parser_extracts_creature_and_zombified_classification():
    event = parse_death_line(FIXTURE.read_text().splitlines()[0])
    assert event.victim_name == "Blittz"
    assert event.victim_level == 75
    assert event.killer_name == "Zombified Pteranodon"
    assert event.killer_level == 10
    assert event.zombified is True


def test_server_name_parser_requires_verified_start_format(tmp_path):
    line = '[2026.11.08-23.03.57:815][ 16]Server: "Vox Noctis" has successfully started!'
    assert parse_server_start_line(line) == "Vox Noctis"
    assert parse_server_start_line('Server: "Vox Noctis" has successfully started!') is None
    assert parse_server_start_line('[2026.11.08-23.03.57:815][16]Server: "Vox Noctis" started!') is None
    path = tmp_path / "ShooterGame.log"
    path.write_text("noise\n" + line + "\n")
    assert discover_server_name(path) == "Vox Noctis"


def test_death_parser_accepts_unknown_killer_and_rejects_ambiguous_lines():
    event = parse_death_line("2026.11.08_14.11.00: Blittz - Lvl 75 () was killed!")
    assert event is not None and event.killer_name is None
    assert parse_death_line("not a death record") is None


def test_death_parser_accepts_unreal_prefix_and_numeric_killer_sid_suffix():
    drowning = parse_death_line("[2026.11.08-22.07.38:308][252]2026.11.08_22.07.38: Blittz - Lvl 75 () was killed!")
    falling = parse_death_line("[2026.11.08-22.08.39:821][774]2026.11.08_22.08.39: Blittz - Lvl 75 () was killed! [KillerSID: 614811848]")
    assert drowning is not None and drowning.killer_name is None
    assert falling is not None and falling.killer_name is None


def test_death_parser_rejects_malformed_killer_sid_suffix():
    assert parse_death_line("2026.11.08_22.08.39: Blittz - Lvl 75 () was killed! [KillerSID: unknown]") is None
    assert parse_death_line("2026.11.08_22.08.39: Blittz - Lvl 75 () was killed! extra text") is None


def test_creature_deaths_accept_numeric_killer_sid_suffix():
    rex = parse_death_line("2026.11.08_22.09.00: Blittz - Lvl 75 () was killed by a Rex - Lvl 20 ()! [KillerSID: 12345]")
    zombie = parse_death_line("2026.11.08_22.10.00: Blittz - Lvl 75 () was killed by a Zombified Stegosaurus - Lvl 29 ()! [KillerSID: 12345]")
    assert rex is not None and rex.killer_name == "Rex" and rex.zombified is False
    assert zombie is not None and zombie.killer_name == "Zombified Stegosaurus" and zombie.zombified is True


def test_log_collector_starts_at_end_and_deduplicates(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text(FIXTURE.read_text())
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    assert store.collect_log(path, {"id:blittz": "Blittz"}) == 0
    with path.open("a") as handle:
        handle.write("2026.11.08_14.11.00: Blittz - Lvl 75 () was killed by a Rex - Lvl 20 ()!\n")
    assert store.collect_log(path, {"id:blittz": "Blittz"}) == 1
    assert store.collect_log(path, {"id:blittz": "Blittz"}) == 0
    assert store.death_summary("id:blittz")[:2] == (1, 0)


def test_log_collector_handles_partial_lines_and_truncation(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text("")
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.collect_log(path, {})
    with path.open("a") as handle:
        handle.write("2026.11.08_14.12.00: Blittz - Lvl 75 () was killed!")
    assert store.collect_log(path, {}) == 0
    with path.open("a") as handle:
        handle.write("\n")
    assert store.collect_log(path, {}) == 1


def test_rotation_recovers_unread_tail_from_matching_backup(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text("2026.11.08_14.14.00: Blittz - Lvl 75 () was killed!\n")
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.collect_log(path, {})
    with path.open("a") as handle:
        handle.write("2026.11.08_14.15.00: Blittz - Lvl 75 () was killed!\n")
    backup = tmp_path / "ShooterGame-backup-1.log"
    path.rename(backup)
    path.write_text("2026.11.08_14.16.00: Blittz - Lvl 75 () was killed!\n")
    assert store.collect_log(path, {}) == 1


def test_rotation_recovers_by_unique_content_when_inode_changes(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text("header\n")
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.collect_log(path, {})
    with path.open("a") as handle:
        handle.write("2026.11.08_14.17.00: Blittz - Lvl 75 () was killed!\n")
    old = tmp_path / "old.log"
    path.rename(old)
    backup = tmp_path / "ShooterGame-backup-copy.log"
    backup.write_bytes(old.read_bytes())
    path.write_text("new active\n")
    assert store.collect_log(path, {}) == 1


def test_unmatched_rotation_records_coverage_gap(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text("old\n")
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.collect_log(path, {})
    path.rename(tmp_path / "unrelated.log")
    path.write_text("new\n")
    store.collect_log(path, {})
    assert store._metadata("death_coverage_gap")


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


def test_interrupted_snapshot_resumes_from_fresh_baseline(tmp_path):
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.record_snapshot({"id:a": "Alice"}, now_mono=0, now_wall="t0")
    store.record_snapshot({"id:a": "Alice"}, now_mono=10, now_wall="t1")
    store.interrupt_snapshot()
    store.record_snapshot({"id:a": "Alice"}, now_mono=1000, now_wall="t2")
    store.record_snapshot({"id:a": "Alice"}, now_mono=1010, now_wall="t3")
    assert store.stats("id:a")[2] == 20


def test_reset_clears_stats_cursor_and_preserves_server_name(tmp_path):
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.set_server_name("Vox Noctis")
    store.record_snapshot({"id:a": "Alice"}, now_mono=0, now_wall="t0")
    store.record_snapshot({"id:a": "Alice"}, now_mono=10, now_wall="t1")
    store.reset()
    assert store.server_name() == "Vox Noctis"
    assert store.stats("id:a")[2] == 0
    assert store.tracking_started()
    assert store._metadata("death_file_state") is None
    assert store._epoch() == 2


def test_reset_starts_new_baseline_without_replaying_history(tmp_path):
    path = tmp_path / "ShooterGame.log"
    path.write_text("2026.11.08_23.00.00: Alice - Lvl 1 () was killed!\n")
    store = ArkStatsStore(tmp_path / "stats.sqlite3")
    store.collect_log(path, {"id:a": "Alice"})
    store.reset()
    assert store.collect_log(path, {"id:a": "Alice"}) == 0


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
