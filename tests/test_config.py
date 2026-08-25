import pytest

from longbridge2tg.config import ConfigError, load_config


def write_config(tmp_path, body: str):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_config_validates_and_normalizes(tmp_path):
    path = write_config(
        tmp_path,
        """
longbridge:
  app_key: key
  app_secret: secret
  access_token: token
telegram:
  bot_token: tg-token
  chat_id: 123456789
schedule:
  times: ["20:00", "9:30"]
log_level: debug
""",
    )

    config = load_config(path)

    assert config.schedule.times == ("09:30", "20:00")
    assert config.telegram.chat_id == "123456789"
    assert config.log_level == "DEBUG"


@pytest.mark.parametrize(
    "missing",
    ["app_key", "app_secret", "access_token"],
)
def test_longbridge_secrets_are_required(tmp_path, missing):
    values = {
        "app_key": '"key"',
        "app_secret": '"secret"',
        "access_token": '"token"',
    }
    values[missing] = '""'
    body = f"""
longbridge:
  app_key: {values["app_key"]}
  app_secret: {values["app_secret"]}
  access_token: {values["access_token"]}
telegram:
  bot_token: tg-token
  chat_id: 123456789
schedule:
  times: ["09:30"]
"""
    path = write_config(tmp_path, body)

    with pytest.raises(ConfigError, match=missing):
        load_config(path)


def test_duplicate_schedule_times_are_rejected(tmp_path):
    path = write_config(
        tmp_path,
        """
longbridge:
  app_key: key
  app_secret: secret
  access_token: token
telegram:
  bot_token: tg-token
  chat_id: 123456789
schedule:
  times: ["09:30", "09:30"]
""",
    )

    with pytest.raises(ConfigError, match="duplicate schedule time"):
        load_config(path)
