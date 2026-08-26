from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import InputRichMessage

from .formatter import _TZ_CN, format_portfolio_snapshot
from .longbridge_client import PortfolioClient


logger = logging.getLogger(__name__)


class TelegramSender:
    def __init__(self, bot: Bot, chat_id: str) -> None:
        self.bot = bot
        self.chat_id = chat_id

    async def send(self, text: str, parse_mode: str | None = None) -> None:
        await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode=parse_mode)

    async def send_markdown(self, text: str) -> None:
        rich_message = InputRichMessage(markdown=text)
        await self.bot.send_rich_message(chat_id=self.chat_id, rich_message=rich_message)


class ReportService:
    def __init__(self, client: PortfolioClient, sender: TelegramSender) -> None:
        self.client = client
        self.sender = sender

    def set_sender(self, sender: TelegramSender) -> None:
        logger.info("switching telegram sender session")
        self.sender = sender

    async def run(self, trigger: str) -> bool:
        logger.info("running portfolio report: trigger=%s", trigger)
        try:
            snapshot = await self.client.get_portfolio_snapshot()
            chunks = format_portfolio_snapshot(snapshot, reported_at=datetime.now(tz=_TZ_CN))
            logger.info(
                "prepared report: trigger=%s messages=%d positions=%d",
                trigger,
                len(chunks),
                len(snapshot.positions),
            )
        except Exception:
            logger.exception("failed to fetch or format portfolio: trigger=%s", trigger)
            await self._safe_send("获取长桥账户仓位失败，请查看服务日志。")
            return False

        try:
            for index, chunk in enumerate(chunks, start=1):
                await self.sender.send_markdown(chunk)
                logger.info(
                    "sent report message: trigger=%s part=%d/%d bytes=%d",
                    trigger,
                    index,
                    len(chunks),
                    len(chunk.encode("utf-8")),
                )
        except Exception:
            logger.exception("failed to send portfolio report: trigger=%s", trigger)
            return False

        return True

    async def _safe_send(self, text: str) -> None:
        try:
            await self.sender.send(text)
        except Exception:
            logger.exception("also failed to send the error notification")
