import asyncio
from decimal import Decimal
from longbridge2tg.models import AccountSummary, PortfolioSnapshot
from longbridge2tg.reporter import ReportService


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def get_portfolio_snapshot(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class FakeSender:
    def __init__(self):
        self.markdown_messages = []
        self.plain_messages = []
        self.error = None

    async def send(self, text, parse_mode=None):
        if self.error:
            raise self.error
        self.plain_messages.append(text)

    async def send_markdown(self, text):
        if self.error:
            raise self.error
        self.markdown_messages.append(text)


def empty_snapshot():
    return PortfolioSnapshot(
        positions=(),
        securities={},
        quotes={},
        balance=AccountSummary(Decimal("100"), Decimal("100"), "USD"),
    )


def test_successful_report_sends_rich_markdown_chunks():
    client = FakeClient(empty_snapshot())
    sender = FakeSender()
    service = ReportService(client, sender)

    result = asyncio.run(service.run("test"))

    assert result is True
    assert len(sender.markdown_messages) == 1
    assert "| 名称 | 代码 | 占比 | 状态 |" in sender.markdown_messages[0]
    assert client.calls == 1


def test_fetch_failure_sends_plain_user_notification():
    client = FakeClient(error=RuntimeError("api unavailable"))
    sender = FakeSender()
    service = ReportService(client, sender)

    result = asyncio.run(service.run("scheduled"))

    assert result is False
    assert sender.plain_messages == ["获取长桥账户仓位失败，请查看服务日志。"]
