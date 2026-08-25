from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, Message

from .formatter import _TZ_CN
from .scheduler import ReportScheduler


logger = logging.getLogger(__name__)


class ChatAllowlistMiddleware:
    def __init__(self, allowed_chat_id: str) -> None:
        self.allowed_chat_id = allowed_chat_id.strip()

    async def __call__(
        self,
        handler: Callable[[Message, dict], Awaitable[object]],
        event: Message,
        data: dict,
    ) -> object | None:
        actual_chat_id = str(event.chat.id)
        if actual_chat_id != self.allowed_chat_id:
            logger.warning(
                "rejected Telegram message from unauthorized chat_id=%s",
                actual_chat_id,
            )
            return None
        return await handler(event, data)


def build_router(
    report_service: object,
    scheduler: ReportScheduler,
    allowed_chat_id: str,
) -> Router:
    router = Router(name="commands")
    router.message.middleware(ChatAllowlistMiddleware(allowed_chat_id))

    @router.message(Command("report_test"))
    async def report_test(message: Message) -> None:
        logger.info("accepted command /report_test chat_id=%s", message.chat.id)
        await message.answer("正在测试一次股票仓位汇报...")
        await report_service.run("手动测试")  # type: ignore[attr-defined]

    @router.message(Command("start_task"))
    async def start_task(message: Message) -> None:
        logger.info("accepted command /start_task chat_id=%s", message.chat.id)
        scheduler.start()
        await message.answer(_enabled_text(scheduler, True))

    @router.message(Command("stop_task"))
    async def stop_task(message: Message) -> None:
        logger.info("accepted command /stop_task chat_id=%s", message.chat.id)
        scheduler.stop()
        await message.answer("已停止每日定时汇报。")

    return router


async def run_polling(bot: Bot, router: Router) -> None:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await bot.set_my_commands(
        [
            BotCommand(command="report_test", description="立即测试一次汇报"),
            BotCommand(command="start_task", description="开始每日定时汇报"),
            BotCommand(command="stop_task", description="停止每日定时汇报"),
        ]
    )
    logger.info("starting Telegram long polling")
    await dispatcher.start_polling(bot)


def _enabled_text(scheduler: ReportScheduler, running: bool) -> str:
    if not running:
        return "已保存启动状态，但调度器当前未运行。"
    runs = scheduler.next_run_times()
    if not runs:
        return "已开始每日定时汇报，但没有可显示的下次执行时间。"
    formatted_runs = ", ".join(run.astimezone(_TZ_CN).strftime("%m-%d %H:%M") for run in runs[:10])
    suffix = " ..." if len(runs) > 10 else ""
    return f"已开始每日定时汇报。下次执行: {formatted_runs}{suffix} (UTC+8)"
