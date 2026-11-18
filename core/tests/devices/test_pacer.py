"""Тесты темпа отправки ответа: ~1 с сразу, дальше ≤ 4× реального времени, не больше 10 с впереди."""

from hub_helpers import SECOND, FakeClock

from smartesp.devices.playback import _Pacer  # pyright: ignore[reportPrivateUsage]

PIECE = 4096  # кадр к колонке
PIECE_S = PIECE / SECOND
STEP_S = 0.001  # шаг подставных часов в симуляции


def simulate(total_s: float, clock: FakeClock, pacer: _Pacer) -> list[tuple[float, float, float]]:
    """Шлёт total_s секунд звука кадрами, как только темп позволяет; время двигает по STEP_S.

    Возвращает по каждому кадру (момент отправки, сколько всего отправлено в секундах, впереди).
    """
    sent = 0
    log: list[tuple[float, float, float]] = []
    while sent < total_s * SECOND:
        if pacer.ready():
            pacer.add(PIECE)
            sent += PIECE
            log.append((clock.now, sent / SECOND, pacer.ahead()))
        else:
            clock.now += STEP_S
    return log


def test_burst_then_4x_then_real_time() -> None:
    clock = FakeClock()
    log = simulate(30.0, clock, _Pacer(clock))

    burst = [sent for t, sent, _ in log if t == 0.0]
    assert 1.0 <= burst[-1] <= 1.0 + PIECE_S  # первая секунда — сразу

    for t, sent, ahead in log:
        assert sent <= 1.0 + PIECE_S + 4.0 * t + 1e-9  # не быстрее 4× после первой секунды
        assert ahead <= 10.0 + PIECE_S  # не больше 10 с впереди

    # 4× против воспроизведения 1×: впереди растёт на ~3 с/с — от 1 до ~10 с примерно за 3 с
    reached = next(t for t, _, ahead in log if ahead >= 9.8)
    assert 2.9 <= reached <= 3.4
    # дальше — со скоростью воспроизведения: 30 с звука уходят к ~20-й секунде
    assert 19.5 <= log[-1][0] <= 20.5


def test_silence_gives_no_credit() -> None:
    clock = FakeClock()
    pacer = _Pacer(clock)
    simulate(1.0, clock, pacer)
    clock.now += 30.0  # колонка доиграла и молчала
    sent_now = 0
    while pacer.ready():
        pacer.add(PIECE)
        sent_now += PIECE
    assert SECOND <= sent_now <= SECOND + PIECE  # снова только первая секунда сразу
