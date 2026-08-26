from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError

from .bot import build_router, run_polling
from .config import CONFIG_ENV_VAR, ConfigError, AppConfig, load_config
from .formatter import _TZ_CN
from .longbridge_client import LongbridgePositionsClient
from .reporter import ReportService, TelegramSender
from .scheduler import ReportScheduler


logger = logging.getLogger(__name__)

# Application-level reconnect loop. If polling keeps failing, exit non-zero so
# systemd restarts the whole process instead of hanging forever.
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_BASE_DELAY_SECONDS = 30
RECONNECT_MAX_DELAY_SECONDS = 1800
HEALTHY_SESSION_SECONDS = 300

class ShanghaiFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone(_TZ_CN)
        return timestamp.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        ShanghaiFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logging.basicConfig(level=getattr(logging, level), handlers=[handler])


def warn_if_config_is_world_readable(path: str) -> None:
    if os.name == "posix":
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077:
            logger.warning("config permissions are too open: %s has mode %o; recommend 600", path, mode)


async def run_application(config: AppConfig) -> None:
    client = LongbridgePositionsClient(config.longbridge)
    await client.start()

    service: ReportService | None = None
    scheduler: ReportScheduler | None = None
    reconnect_count = 0

    while True:
        session_started = time.monotonic()
        try:
            async with Bot(token=config.telegram.bot_token) as bot:
                sender = TelegramSender(bot, config.telegram.chat_id)
                if service is None or scheduler is None:
                    service = ReportService(client, sender)
                    scheduler = ReportScheduler(service, config.schedule.times)
                    scheduler.start()
                    logger.info("scheduler started automatically at application startup")
                else:
                    service.set_sender(sender)

                router = build_router(
                    report_service=service,
                    scheduler=scheduler,
                    allowed_chat_id=config.telegram.chat_id,
                )
                logger.info(
                    "application ready; authorized_chat_id=%s",
                    config.telegram.chat_id,
                )
                await run_polling(bot, router)
            return
        except (TelegramNetworkError, ConnectionError, OSError, TimeoutError) as exc:
            logger.error("telegram connection lost: %s", exc)
        except Exception:
            logger.exception("unexpected error during polling session")

        session_seconds = time.monotonic() - session_started
        if session_seconds >= HEALTHY_SESSION_SECONDS:
            reconnect_count = 1
        else:
            reconnect_count += 1
        if reconnect_count > MAX_RECONNECT_ATTEMPTS:
            logger.critical(
                "giving up after %d consecutive failed sessions; exiting so systemd can restart the service",
                MAX_RECONNECT_ATTEMPTS,
            )
            raise SystemExit(1)

        delay = min(
            RECONNECT_BASE_DELAY_SECONDS * 2 ** (reconnect_count - 1),
            RECONNECT_MAX_DELAY_SECONDS,
        )
        logger.warning(
            "reconnect %d/%d scheduled in %d seconds (last session lasted %.0f s)",
            reconnect_count,
            MAX_RECONNECT_ATTEMPTS,
            delay,
            session_seconds,
        )
        await asyncio.sleep(delay)
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Longbridge stock positions to Telegram")
    parser.add_argument(
        "--config",
        default=os.getenv(CONFIG_ENV_VAR, "config.yaml"),
        help=f"YAML config path (default: --config or ${CONFIG_ENV_VAR})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1

    setup_logging(config.log_level)
    logger.info("loaded configuration from %s", args.config)
    warn_if_config_is_world_readable(args.config)
    logger.info(
        "configured daily report times (UTC+8): %s",
        ", ".join(config.schedule.times),
    )

    try:
        asyncio.run(run_application(config))
    except KeyboardInterrupt:
        logger.info("received interrupt; shutting down")
    except Exception:
        logger.exception("application failed")
        return 1


    return 0
