"""Deletes old log files, as a separate process next to the services.

    uv run python -m common.log_cleaner                  # every LOG_CLEANUP_INTERVAL_MINUTES
    uv run python -m common.log_cleaner --once           # one pass, then exit
    uv run python -m common.log_cleaner --max-age-hours 6

A file is deleted when it matches `common.log.FILE_NAME`, `<service>.<stream>.<creation time>.log`
(`app` files from `common.log`, `console` files from scripts/start-bg.sh), and the creation time
in its name is older than now minus the maximum age: LOG_CLEANUP_MAX_AGE_HOURS (default 24) or
`--max-age-hours`, with the other settings in `common.log.LoggingConfig`. Files a symlink points to (`<service>.log`, `<service>.console.log`) are being
written and are kept, and so is anything not named that way. The directory is LOG_DIR, as for
`common.log`. The cleaner logs as service `log-cleaner`, so its own files are cleaned too.
"""

import argparse
import dataclasses
import threading
from datetime import datetime, timedelta
from pathlib import Path

from common.log import FILE_NAME, TIMESTAMP, LoggingConfig, get_logger, setup_logging

log = get_logger("common.log_cleaner")


def clean(directory: Path, older_than: timedelta, now: datetime | None = None) -> list[Path]:
    """Delete the timestamped log files in `directory` created before `now - older_than`."""
    if not directory.is_dir():
        return []
    cutoff = (now or datetime.now()) - older_than
    paths = list(directory.iterdir())
    current = {p.resolve() for p in paths if p.is_symlink()}
    deleted = []
    for path in paths:
        match = FILE_NAME.match(path.name)
        if not match or path.is_symlink() or path.resolve() in current:
            continue
        if datetime.strptime(match["time"], TIMESTAMP) < cutoff:
            path.unlink(missing_ok=True)
            deleted.append(path)
    return deleted


def run(directory: Path, older_than: timedelta, every: timedelta, stop: threading.Event) -> None:
    """Clean `directory` now and then every `every`, until `stop` is set."""
    log.info("cleaning %s every %s: files older than %s", directory, every, older_than)
    while True:
        for path in clean(directory, older_than):
            log.info("deleted %s", path.name)
        if stop.wait(every.total_seconds()):
            return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m common.log_cleaner", description=__doc__.split("\n")[0])
    parser.add_argument("--max-age-hours", type=float, help="overrides LOG_CLEANUP_MAX_AGE_HOURS (default 24)")
    parser.add_argument("--once", action="store_true", help="clean once and exit")
    args = parser.parse_args(argv)
    if args.max_age_hours is not None and args.max_age_hours <= 0:
        parser.error("--max-age-hours must be positive")
    config = LoggingConfig.from_env()
    if args.max_age_hours is not None:
        config = dataclasses.replace(config, cleanup_max_age_hours=args.max_age_hours)
    setup_logging("log-cleaner", config)
    if args.once:
        for path in clean(config.directory, config.cleanup_max_age):
            log.info("deleted %s", path.name)
        return
    try:
        run(config.directory, config.cleanup_max_age, config.cleanup_interval, threading.Event())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
