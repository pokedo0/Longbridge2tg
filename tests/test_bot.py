from types import SimpleNamespace

from longbridge2tg.bot import ChatAllowlistMiddleware


def test_allowlist_accepts_configured_chat():
    async def scenario():
        calls = []

        async def handler(message, data):
            calls.append(message)

        middleware = ChatAllowlistMiddleware("123456789")
        message = SimpleNamespace(chat=SimpleNamespace(id=123456789))
        await middleware(handler, message, {})
        return calls

    calls = __import__("asyncio").run(scenario())
    assert len(calls) == 1


def test_allowlist_rejects_other_chat():
    async def scenario():
        calls = []

        async def handler(message, data):
            calls.append(message)

        middleware = ChatAllowlistMiddleware("123456789")
        message = SimpleNamespace(chat=SimpleNamespace(id=987654321))
        await middleware(handler, message, {})
        return calls

    calls = __import__("asyncio").run(scenario())
    assert calls == []
