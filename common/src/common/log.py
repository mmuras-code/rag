"""Logging for every service: one config, applied once per process, and the loggers to use.

    from common.log import get_logger
    log = get_logger("search.sync")      # in any module, instead of logging.getLogger

    from common.log import setup_logging
    setup_logging("search")              # once, in the service's entry point

Libraries (`llm`, `agent`, `observability`) only call `get_logger`; the service running them sets
logging up, so the agent's lines land in the orchestrator's file. Each line is
`time LEVEL logger message` and goes to:

- `logs/<service>.app.<creation time>.log` at the `rag/` root (LOG_DIR overrides the directory),
  e.g. `logs/orchestrator.app.2026-10-01T14-30-05.log`. A new file starts at each process start,
  every LOG_ROLL_MINUTES (default 60, on clock boundaries counted from midnight, so hourly files
  start at :00), and at LOG_MAX_MB (default 50). `logs/<service>.log` is a symlink to the current
  file (`tail -F` follows it). Old files are deleted by a separate process, `common.log_cleaner`.
- stderr, unless LOG_STDERR is `false` (the background start in scripts/start-bg.sh sets that,
  so its console file holds only what bypasses logging, such as a crash at startup).

uvicorn's own loggers (startup, access log) are configured too, so they share the format and the
file: pass `log_config=None` to `uvicorn.run`, or uvicorn replaces this config with its own.

Settings are in `LoggingConfig`: its defaults, each overridden by an environment variable if set
(LOG_LEVEL, LOG_DIR, LOG_ROLL_MINUTES, ...). An invalid value stops the service at startup.
"""

import logging
import logging.config
import logging.handlers
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
# Every log file is named `<service>.<stream>.<creation time>.log`, e.g.
# `search.app.2026-10-01T14-30-05.log`; scripts/start-bg.sh names console files the same way.
TIMESTAMP = "%Y-%m-%dT%H-%M-%S"
FILE_NAME = re.compile(
    r"^(?P<service>[A-Za-z0-9_-]+)\.(?P<stream>app|console)\.(?P<time>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.log$"
)
# rag/, from rag/common/src/common/log.py (common is installed editable, so this is the repo).
ROOT = Path(__file__).resolve().parents[3]

# Loggers that are too chatty at INFO: httpx logs every request it sends.
QUIET = ("httpx", "httpcore")
# uvicorn's loggers: sent through the root handlers, so they share the format and the file.
UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")


class LogStream(StrEnum):
    APP = "app"  # written through logging, by TimestampedFileHandler
    CONSOLE = "console"  # a background process's stdout and stderr, by scripts/start-bg.sh


def file_name(service: str, stream: LogStream, created: datetime) -> str:
    """`<service>.<stream>.<creation time>.log`, the name FILE_NAME matches."""
    return f"{service}.{stream}.{created:{TIMESTAMP}}.log"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def _positive(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError:
        raise SystemExit(f"{name}={value!r} is not a number") from None
    if number <= 0:
        raise SystemExit(f"{name}={value!r} must be positive")
    return number


@dataclass(frozen=True)
class LoggingConfig:
    """Logging and log cleanup settings. `from_env()` takes each from its variable if set."""

    level: LogLevel = LogLevel.INFO  # LOG_LEVEL, case-insensitive
    directory: Path = ROOT / "logs"  # LOG_DIR
    roll_minutes: float = 60  # LOG_ROLL_MINUTES: time per file, counted from midnight
    max_mb: float = 50  # LOG_MAX_MB: size at which a new file starts
    stderr: bool = True  # LOG_STDERR: `false` writes the file only
    cleanup_max_age_hours: float = 24  # LOG_CLEANUP_MAX_AGE_HOURS: older files are deleted
    cleanup_interval_minutes: float = 60  # LOG_CLEANUP_INTERVAL_MINUTES: time between passes

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        defaults = cls()
        level = os.environ.get("LOG_LEVEL", defaults.level).upper()
        if level not in LogLevel.__members__:
            raise SystemExit(f"LOG_LEVEL={level!r} is not one of {[lv.value for lv in LogLevel]}")
        return cls(
            level=LogLevel(level),
            directory=Path(os.environ.get("LOG_DIR", defaults.directory)).expanduser(),
            roll_minutes=_positive("LOG_ROLL_MINUTES", defaults.roll_minutes),
            max_mb=_positive("LOG_MAX_MB", defaults.max_mb),
            stderr=os.environ.get("LOG_STDERR", "true").lower() != "false",
            cleanup_max_age_hours=_positive("LOG_CLEANUP_MAX_AGE_HOURS", defaults.cleanup_max_age_hours),
            cleanup_interval_minutes=_positive("LOG_CLEANUP_INTERVAL_MINUTES", defaults.cleanup_interval_minutes),
        )

    @property
    def cleanup_max_age(self) -> timedelta:
        return timedelta(hours=self.cleanup_max_age_hours)

    @property
    def cleanup_interval(self) -> timedelta:
        return timedelta(minutes=self.cleanup_interval_minutes)


class TimestampedFileHandler(logging.handlers.BaseRotatingHandler):
    """Writes to `<dir>/<service>.app.<creation time>.log`, e.g. `orchestrator.app.2026-10-01T14-30-05.log`.

    A new file starts when the process starts, every `roll_minutes` and when the file reaches
    `max_bytes`. Roll times are counted from local midnight (with 60, at every full hour), and
    midnight always starts a new file. `<dir>/<service>.log` is a symlink to the current file.
    Old files are left to `common.log_cleaner`.
    """

    def __init__(self, service: str, directory: str, max_bytes: int, roll_minutes: float = 60):
        self.service, self.directory, self.max_bytes = service, Path(directory), max_bytes
        self.roll_minutes = roll_minutes
        self.directory.mkdir(parents=True, exist_ok=True)
        self.period = self._period()
        super().__init__(self._new_path(), mode="a", encoding="utf-8")
        self._link()

    def _period(self) -> tuple:
        """The roll period `now` falls in: the day, and the interval number since midnight."""
        now = datetime.now()
        return now.date(), int((now.hour * 60 + now.minute + now.second / 60) // self.roll_minutes)

    def _new_path(self) -> str:
        return str(self.directory / file_name(self.service, LogStream.APP, datetime.now()))

    def _link(self) -> None:
        link = self.directory / f"{self.service}.log"
        link.unlink(missing_ok=True)
        link.symlink_to(Path(self.baseFilename).name)

    def shouldRollover(self, record) -> bool:
        if self._period() != self.period:
            return True
        return self.stream is not None and self.stream.tell() >= self.max_bytes

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        self.period = self._period()
        self.baseFilename = self._new_path()
        self.stream = self._open()
        self._link()


def dict_config(service: str, config: LoggingConfig | None = None) -> dict:
    """The logging config for `service`, as a `logging.config.dictConfig` dict."""
    config = config or LoggingConfig.from_env()
    level = config.level.value
    handlers = {
        "file": {"()": TimestampedFileHandler, "formatter": "default", "service": service,
                 "directory": str(config.directory),
                 "max_bytes": int(config.max_mb * 1024 * 1024),
                 "roll_minutes": config.roll_minutes},
    }
    if config.stderr:
        handlers["stderr"] = {"class": "logging.StreamHandler", "formatter": "default", "stream": "ext://sys.stderr"}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": FORMAT}},
        "handlers": handlers,
        "root": {"level": level, "handlers": list(handlers)},
        "loggers": {
            **{name: {"level": level, "handlers": [], "propagate": True} for name in UVICORN},
            **{name: {"level": LogLevel.WARNING.value} for name in QUIET},
        },
    }


_configured: str | None = None


def setup_logging(service: str, config: LoggingConfig | None = None) -> None:
    """Apply `dict_config(service, config)` once per process; later calls do nothing.

    `config` defaults to `LoggingConfig.from_env()`.
    """
    global _configured
    if _configured:
        return
    config = config or LoggingConfig.from_env()
    logging.config.dictConfig(dict_config(service, config))
    _configured = service
    file = next(h.baseFilename for h in logging.getLogger().handlers if isinstance(h, TimestampedFileHandler))
    get_logger("common.log").info("logging to %s at %s", file, config.level.value)


def get_logger(name: str) -> logging.Logger:
    """The logger for `name`, dotted by service and module (e.g. `agent.judges.llm`)."""
    return logging.getLogger(name)
