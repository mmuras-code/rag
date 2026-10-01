import os

import pytest

from common.stage import Stage, load_env, stage


def test_stage_parses_and_rejects_unknown(monkeypatch):
    monkeypatch.setenv("STAGE", "production")
    assert stage() is Stage.PRODUCTION
    monkeypatch.delenv("STAGE")
    assert stage() is Stage.DEVELOPMENT
    monkeypatch.setenv("STAGE", "prod")
    with pytest.raises(SystemExit):
        stage()


@pytest.mark.parametrize(("stage_value", "loaded"), [("development", True), ("production", False)])
def test_load_env_only_in_development(monkeypatch, tmp_path, stage_value, loaded):
    env_file = tmp_path / ".env"
    env_file.write_text("COMMON_TEST_VALUE=from-file\n")
    monkeypatch.setenv("STAGE", stage_value)
    monkeypatch.delenv("COMMON_TEST_VALUE", raising=False)
    load_env(env_file)
    assert (os.environ.get("COMMON_TEST_VALUE") == "from-file") is loaded
    monkeypatch.delenv("COMMON_TEST_VALUE", raising=False)


def test_environment_wins_over_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("COMMON_TEST_VALUE=from-file\n")
    monkeypatch.delenv("STAGE", raising=False)
    monkeypatch.setenv("COMMON_TEST_VALUE", "from-env")
    load_env(env_file)
    assert os.environ["COMMON_TEST_VALUE"] == "from-env"
