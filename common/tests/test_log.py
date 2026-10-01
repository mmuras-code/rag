import logging
import os
import time

import pytest

from common import log
from common.log import (
    LoggingConfig,
    LogLevel,
    TimestampedFileHandler,
    dict_config,
    get_logger,
)

LOG_VARS = ("LOG_LEVEL", "LOG_DIR", "LOG_ROLL_MINUTES", "LOG_MAX_MB", "LOG_STDERR",
            "LOG_CLEANUP_MAX_AGE_HOURS", "LOG_CLEANUP_INTERVAL_MINUTES")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in LOG_VARS:
        monkeypatch.delenv(name, raising=False)


def test_config_defaults_without_env():
    assert LoggingConfig.from_env() == LoggingConfig()
    config = LoggingConfig()
    assert (config.level, config.roll_minutes, config.max_mb, config.stderr) == (LogLevel.INFO, 60, 50, True)
    assert config.directory == log.ROOT / "logs"
    assert (config.cleanup_max_age_hours, config.cleanup_interval_minutes) == (24, 60)


def test_config_from_env(monkeypatch, tmp_path):
    for name, value in {"LOG_LEVEL": "debug", "LOG_DIR": str(tmp_path), "LOG_ROLL_MINUTES": "15",
                        "LOG_MAX_MB": "5", "LOG_STDERR": "false", "LOG_CLEANUP_MAX_AGE_HOURS": "6",
                        "LOG_CLEANUP_INTERVAL_MINUTES": "10"}.items():
        monkeypatch.setenv(name, value)
    assert LoggingConfig.from_env() == LoggingConfig(LogLevel.DEBUG, tmp_path, 15, 5, False, 6, 10)


@pytest.mark.parametrize(("name", "value"), [("LOG_LEVEL", "LOUD"), ("LOG_ROLL_MINUTES", "0"),
                                             ("LOG_MAX_MB", "big"), ("LOG_CLEANUP_INTERVAL_MINUTES", "-1")])
def test_invalid_env_stops_the_service(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit, match=name):
        LoggingConfig.from_env()


def test_dict_config_writes_to_the_service_file_and_stderr(tmp_path):
    config = dict_config("search", LoggingConfig(directory=tmp_path, roll_minutes=15, max_mb=1))
    assert config["root"]["handlers"] == ["file", "stderr"]
    file = config["handlers"]["file"]
    assert (file["service"], file["directory"], file["roll_minutes"], file["max_bytes"]) == (
        "search", str(tmp_path), 15, 1024 * 1024)
    assert config["loggers"]["httpx"]["level"] == "WARNING"
    assert config["loggers"]["uvicorn.access"]["propagate"] is True


def test_dict_config_reads_env_by_default(monkeypatch):
    monkeypatch.setenv("LOG_STDERR", "false")
    assert dict_config("search")["root"]["handlers"] == ["file"]


def handler(tmp_path, **kwargs):
    args = {"service": "search", "directory": str(tmp_path), "max_bytes": 10_000} | kwargs
    h = TimestampedFileHandler(**args)
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def record(msg):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def test_file_name_has_service_and_creation_time_and_a_current_symlink(tmp_path):
    h = handler(tmp_path)
    h.emit(record("hello"))
    h.close()
    files = [p for p in tmp_path.iterdir() if not p.is_symlink()]
    assert len(files) == 1
    match = log.FILE_NAME.match(files[0].name)
    assert match and match["service"] == "search" and match["stream"] == "app"
    link = tmp_path / "search.log"
    assert link.is_symlink() and link.read_text() == "hello\n"


def test_rolls_over_at_max_size(tmp_path, monkeypatch):
    h = handler(tmp_path, max_bytes=10)
    h.emit(record("x" * 20))
    first = h.baseFilename
    # Next second, so the new file gets a different name.
    later = log.datetime.fromtimestamp(time.time() + 1)
    monkeypatch.setattr(log, "datetime", type("D", (), {"now": staticmethod(lambda: later)}))
    h.emit(record("y"))
    h.close()
    assert h.baseFilename != first
    assert os.path.realpath(tmp_path / "search.log") == h.baseFilename


def at(monkeypatch, when):
    monkeypatch.setattr(log, "datetime", type("D", (), {"now": staticmethod(lambda: when)}))


@pytest.mark.parametrize(("roll_minutes", "later", "rolls"), [
    (60, log.datetime(2026, 10, 1, 14, 59, 59), False),
    (60, log.datetime(2026, 10, 1, 15, 0, 0), True),
    (15, log.datetime(2026, 10, 1, 14, 44, 59), False),
    (15, log.datetime(2026, 10, 1, 14, 45, 0), True),
    (1440, log.datetime(2026, 10, 2, 0, 0, 0), True),
])
def test_rolls_over_on_clock_boundaries(tmp_path, monkeypatch, roll_minutes, later, rolls):
    at(monkeypatch, log.datetime(2026, 10, 1, 14, 30, 5))
    h = handler(tmp_path, roll_minutes=roll_minutes)
    first = h.baseFilename
    at(monkeypatch, later)
    h.emit(record("x"))
    h.close()
    assert (h.baseFilename != first) is rolls


def test_file_name_pattern():
    name = log.file_name("log-cleaner", log.LogStream.CONSOLE, log.datetime(2026, 10, 1, 14, 30, 5))
    assert name == "log-cleaner.console.2026-10-01T14-30-05.log"
    assert log.FILE_NAME.match(name).groupdict() == {
        "service": "log-cleaner", "stream": "console", "time": "2026-10-01T14-30-05"}
    for other in ("search.log", "search.console.log", "search.2026-10-01T14-30-05.log", "search.app.today.log"):
        assert not log.FILE_NAME.match(other)


def test_get_logger_is_the_standard_logger():
    assert get_logger("agent") is logging.getLogger("agent")
