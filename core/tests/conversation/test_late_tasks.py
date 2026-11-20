"""Запоздавший ответ в реестре «В работе»: идёт, пока ждём цель; готово или не удалось."""

from conversation_helpers import make_utterance, running, until
from handoff_helpers import TASK
from test_late_answer import GatedNetwork, late_setup, wait_turn

from fakes.fake_announcer import FakeAnnouncer
from fakes.fake_tasks import FakeTaskBoard
from smartesp.contracts import ExecutorError


async def test_late_answer_is_a_task_until_announced() -> None:
    network = GatedNetwork(["Готово. ", "Ответ сорок два."])
    setup, sink = late_setup(network)
    board = FakeTaskBoard()
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.orchestrator.use_tasks(board)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        (started,) = board.reports
        assert (started.source, started.status, started.device_id) == ("late_answer", "running", "kitchen")
        assert started.title == f"Большая модель: {TASK}"
        network.release()
        await until(lambda: len(board.reports) == 2)
    finished = board.reports[1]
    assert (finished.id, finished.status) == (started.id, "done")
    assert finished.result == "Готово. Ответ сорок два."


async def test_late_answer_failure_finishes_task_failed() -> None:
    network = GatedNetwork([], error=ExecutorError("упала"))
    setup, sink = late_setup(network)
    board = FakeTaskBoard()
    setup.orchestrator.use_announcer(FakeAnnouncer())
    setup.orchestrator.use_tasks(board)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_turn(setup, sink)
        network.release()
        await until(lambda: len(board.reports) == 2)
    assert [r.status for r in board.reports] == ["running", "failed"]
