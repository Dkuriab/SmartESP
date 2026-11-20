"""Предел частоты запросов: скользящее окно, время — подделка."""

from web_mcp.limits import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_refuses() -> None:
    clock = Clock()
    limiter = RateLimiter(3, 60.0, clock)
    assert [limiter.allow() for _ in range(4)] == [True, True, True, False]


def test_window_slides() -> None:
    clock = Clock()
    limiter = RateLimiter(2, 60.0, clock)
    assert limiter.allow()
    clock.now += 30
    assert limiter.allow()
    assert not limiter.allow()
    clock.now += 31
    assert limiter.allow()
    assert not limiter.allow()


def test_refused_calls_do_not_count() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 10.0, clock)
    assert limiter.allow()
    for _ in range(5):
        clock.now += 1
        assert not limiter.allow()
    clock.now += 6
    assert limiter.allow()


def test_pause_blocks_until_it_ends() -> None:
    clock = Clock()
    limiter = RateLimiter(10, 60.0, clock)
    limiter.pause(120.0)
    assert limiter.paused()
    clock.now += 119
    assert limiter.paused()
    clock.now += 2
    assert not limiter.paused()
