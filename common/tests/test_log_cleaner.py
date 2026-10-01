import threading
from datetime import datetime, timedelta

import pytest

from common import log_cleaner
from common.log import LoggingConfig
from common.log_cleaner import clean

NOW = datetime(2026, 10, 2, 12, 0, 0)


def touch(directory, name):
    path = directory / name
    path.write_text("x")
    return path


def test_deletes_files_whose_name_time_is_older_than_the_max_age(tmp_path):
    old = touch(tmp_path, "search.app.2026-10-01T11-59-59.log")
    fresh = touch(tmp_path, "search.app.2026-10-01T12-00-01.log")
    other_service = touch(tmp_path, "orchestrator.console.2026-09-30T00-00-00.log")
    deleted = clean(tmp_path, timedelta(hours=24), NOW)
    assert set(deleted) == {old, other_service}
    assert not old.exists() and fresh.exists()


def test_keeps_current_files_symlinks_and_files_off_the_pattern(tmp_path):
    current = touch(tmp_path, "search.app.2026-09-01T00-00-00.log")
    console = touch(tmp_path, "search.console.2026-09-01T00-00-00.log")
    (tmp_path / "search.log").symlink_to(current.name)
    (tmp_path / "search.console.log").symlink_to(console.name)
    unrelated = [touch(tmp_path, name) for name in ("search.2020-01-01T00-00-00.log", "notes.txt")]
    assert clean(tmp_path, timedelta(hours=24), NOW) == []
    assert all(p.exists() for p in [current, console, *unrelated])


def test_max_age_is_configurable(tmp_path, monkeypatch):
    path = touch(tmp_path, "search.app.2026-10-02T10-00-00.log")
    monkeypatch.setenv("LOG_CLEANUP_MAX_AGE_HOURS", "1.5")
    config = LoggingConfig.from_env()
    assert config.cleanup_max_age == timedelta(hours=1.5)
    assert clean(tmp_path, config.cleanup_max_age, NOW) == [path]


@pytest.mark.parametrize("value", ["soon", "0", "-1"])
def test_bad_max_age_stops_the_cleaner(monkeypatch, value):
    monkeypatch.setenv("LOG_CLEANUP_MAX_AGE_HOURS", value)
    with pytest.raises(SystemExit, match="LOG_CLEANUP_MAX_AGE_HOURS"):
        LoggingConfig.from_env()


def test_missing_directory_is_not_an_error(tmp_path):
    assert clean(tmp_path / "missing", timedelta(hours=24)) == []


def test_run_cleans_until_stopped(tmp_path):
    touch(tmp_path, "search.console.2020-01-01T00-00-00.log")
    stop = threading.Event()
    stop.set()
    log_cleaner.run(tmp_path, timedelta(hours=24), timedelta(minutes=60), stop)
    assert list(tmp_path.iterdir()) == []


def test_once_from_the_command_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_STDERR", "false")
    monkeypatch.setattr(log_cleaner, "setup_logging", lambda service, config: None)
    old = touch(tmp_path, "search.console.2020-01-01T00-00-00.log")
    log_cleaner.main(["--once", "--max-age-hours", "1"])
    assert not old.exists()
