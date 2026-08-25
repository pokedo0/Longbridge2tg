from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONFIG_ENV_VAR = "LB2TG_CONFIG"


class ConfigError(ValueError):
    """Raised when the YAML configuration is missing or invalid."""


@dataclass(frozen=True)
class LongbridgeConfig:
    app_key: str
    app_secret: str
    access_token: str


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class ScheduleConfig:
    times: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    longbridge: LongbridgeConfig
    telegram: TelegramConfig
    schedule: ScheduleConfig
    log_level: str


def load_config(path: str | Path | None = None) -> AppConfig:
    configured_path = Path(path or os.getenv(CONFIG_ENV_VAR) or "config.yaml")
    if not configured_path.is_file():
        raise ConfigError(
            f"config file not found: {configured_path} "
            f"(set {CONFIG_ENV_VAR} or pass --config)"
        )

    try:
        raw_text = configured_path.read_text(encoding="utf-8")
        raw = yaml.safe_load(raw_text)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config file {configured_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("config root must be a YAML mapping")

    longbridge = _required_section(raw, "longbridge")
    telegram = _required_section(raw, "telegram")
    schedule = _required_section(raw, "schedule")

    log_level = str(raw.get("log_level", "INFO")).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")

    return AppConfig(
        longbridge=LongbridgeConfig(
            app_key=_secret(longbridge, "app_key"),
            app_secret=_secret(longbridge, "app_secret"),
            access_token=_secret(longbridge, "access_token"),
        ),
        telegram=TelegramConfig(
            bot_token=_secret(telegram, "bot_token"),
            chat_id=_non_empty_string(telegram, "chat_id"),
        ),
        schedule=ScheduleConfig(times=_parse_times(schedule.get("times"))),
        log_level=log_level,
    )


def _required_section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"{name} section is required and must be a mapping")
    return value


def _secret(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    if not value.strip():
        raise ConfigError(f"{name} is required and must not be empty")
    return value.strip()


def _non_empty_string(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if value is None or not str(value).strip():
        raise ConfigError(f"{name} is required and must not be empty")
    if not isinstance(value, str | int):
        raise ConfigError(f"{name} must be a string or integer")
    return str(value).strip()


def _parse_times(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("schedule.times is required and must be a non-empty list")

    parsed: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"^(\d{1,2}):(\d{2})$")
    for item in value:
        text = str(item).strip()
        match = pattern.fullmatch(text)
        if not match:
            raise ConfigError(f"invalid schedule time: {item!r}; expected HH:MM")

        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ConfigError(f"invalid schedule time: {item!r}")

        normalized = f"{hour:02d}:{minute:02d}"
        if normalized in seen:
            raise ConfigError(f"duplicate schedule time: {normalized}")
        seen.add(normalized)
        parsed.append(normalized)

    return tuple(sorted(parsed))

