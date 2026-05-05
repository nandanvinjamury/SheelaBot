from sheela.discord_bot.bot import respond_to


def test_ping_returns_pong():
    assert respond_to("ping") == "pong"


def test_ping_case_insensitive():
    assert respond_to("PING") == "pong"
    assert respond_to("Ping") == "pong"


def test_ping_with_whitespace():
    assert respond_to("  ping  ") == "pong"


def test_other_messages_return_none():
    assert respond_to("hello") is None
    assert respond_to("ping pong") is None
    assert respond_to("") is None
