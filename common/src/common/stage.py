"""Which stage a service runs in, and loading its .env file in development."""

import os
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv


class Stage(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


def stage() -> Stage:
    """STAGE from the real environment (not .env, since it decides whether .env is read)."""
    value = os.environ.get("STAGE", Stage.DEVELOPMENT)
    try:
        return Stage(value)
    except ValueError:
        raise SystemExit(f"STAGE={value!r} is not one of {[s.value for s in Stage]}") from None


def load_env(env_file: Path) -> Stage:
    """Load env_file into os.environ in development only, and return the stage.

    Other stages get their config from the environment only, so a stray .env can never leak into
    them. Variables already set in the environment win over the file.
    """
    current = stage()
    if current is Stage.DEVELOPMENT:
        load_dotenv(env_file)
    return current
