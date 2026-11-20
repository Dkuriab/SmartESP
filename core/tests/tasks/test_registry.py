"""Реестр «В работе»: задачи источников, события и уход законченных."""

from fakes.fake_events import RecordingSink
from smartesp.contracts import TaskBoard, TaskReport
from smartesp.tasks import TaskRegistry


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def setup(keep_s: float = 60.0, max_tasks: int = 200) -> tuple[TaskRegistry, RecordingSink, Clock]:
    sink, clock = RecordingSink(), Clock()
    names = {"kitchen": "Кухня"}
    board = TaskRegistry(sink, lambda d: names.get(d, d), clock=clock, keep_s=keep_s, max_tasks=max_tasks)
    return board, sink, clock


def kinds(sink: RecordingSink) -> list[str]:
    return [kind for kind, _ in sink.events]


def test_registry_satisfies_contract() -> None:
    board: TaskBoard = setup()[0]
    assert board.tasks() == []


def test_new_running_task_is_started_with_device_name() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("late_answer", "kitchen#3", "Погода на завтра", device_id="kitchen", eta=1100.0))
    (task,) = board.tasks()
    assert task.key == "late_answer/kitchen#3"
    assert (task.title, task.status, task.started_at, task.eta) == (
        "Погода на завтра",
        "running",
        1000.0,
        1100.0,
    )
    assert task.device_name == "Кухня"
    assert sink.events[0][0] == "task_started"
    assert sink.events[0][1]["key"] == "late_answer/kitchen#3"
    assert sink.events[0][1]["device_name"] == "Кухня"


def test_update_keeps_title_and_eta_and_publishes_only_changes() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("connector:timers", "t1", "Картошка", eta=1300.0))
    board.report(TaskReport("connector:timers", "t1"))  # ничего не изменилось
    board.report(TaskReport("connector:timers", "t1", eta=1400.0))
    (task,) = board.tasks()
    assert (task.title, task.eta) == ("Картошка", 1400.0)
    assert kinds(sink) == ["task_started", "task_updated"]


def test_finish_publishes_result_and_keeps_task_for_a_while() -> None:
    board, sink, clock = setup(keep_s=60.0)
    board.report(TaskReport("connector:claude", "a", "Отчёт"))
    clock.now = 1010.0
    board.report(TaskReport("connector:claude", "a", status="done", result="Готово: три файла"))
    (task,) = board.tasks()
    assert (task.status, task.finished_at, task.result) == ("done", 1010.0, "Готово: три файла")
    assert kinds(sink) == ["task_started", "task_finished"]
    clock.now = 1071.0
    assert board.tasks() == []


def test_finished_report_for_unknown_task_is_registered_finished() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("connector:claude", "b", "Сводка", status="failed", result="ошибка"))
    (task,) = board.tasks()
    assert task.status == "failed"
    assert kinds(sink) == ["task_finished"]


def test_repeated_finish_is_ignored() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("s", "a", "A"))
    board.report(TaskReport("s", "a", status="done"))
    board.report(TaskReport("s", "a", status="done"))
    assert kinds(sink) == ["task_started", "task_finished"]


def test_running_again_after_finish_starts_anew() -> None:
    board, sink, clock = setup()
    board.report(TaskReport("s", "a", "A"))
    board.report(TaskReport("s", "a", status="done"))
    clock.now = 1005.0
    board.report(TaskReport("s", "a", "A"))
    (task,) = board.tasks()
    assert (task.status, task.started_at, task.finished_at) == ("running", 1005.0, None)
    assert kinds(sink)[-1] == "task_started"


def test_task_without_title_or_id_is_ignored() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("s", "a"))
    board.report(TaskReport("s", "", "Без id"))
    assert board.tasks() == [] and sink.events == []


def test_order_running_oldest_first_then_finished_newest_first() -> None:
    board, _, clock = setup()
    for name in ("a", "b", "c", "d"):
        board.report(TaskReport("s", name, name.upper()))
        clock.now += 1
    board.report(TaskReport("s", "a", status="done"))
    clock.now += 1
    board.report(TaskReport("s", "c", status="cancelled"))
    assert [t.id for t in board.tasks()] == ["b", "d", "c", "a"]


def test_forget_cancels_running_tasks_of_source_only() -> None:
    board, sink, _ = setup()
    board.report(TaskReport("connector:timers", "t1", "Таймер"))
    board.report(TaskReport("connector:claude", "c1", "Задача"))
    board.forget("connector:timers")
    statuses = {t.id: t.status for t in board.tasks()}
    assert statuses == {"t1": "cancelled", "c1": "running"}
    assert sink.events[-1][0] == "task_finished"


def test_long_texts_are_clipped() -> None:
    board, _, _ = setup()
    board.report(TaskReport("s", "a", "т" * 500, status="done", result="р" * 1000))
    (task,) = board.tasks()
    assert len(task.title) <= 120 and len(task.result) <= 300


def test_new_tasks_beyond_limit_are_dropped_after_old_finished_go() -> None:
    board, _, _ = setup(max_tasks=2)
    board.report(TaskReport("s", "a", "A"))
    board.report(TaskReport("s", "b", "B"))
    board.report(TaskReport("s", "c", "C"))  # места нет — пропущена
    assert [t.id for t in board.tasks()] == ["a", "b"]
    board.report(TaskReport("s", "a", status="done"))
    board.report(TaskReport("s", "c", "C"))  # законченная уступает место
    assert [t.id for t in board.tasks()] == ["b", "c"]
