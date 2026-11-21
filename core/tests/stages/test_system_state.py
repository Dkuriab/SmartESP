"""Обработчик «система»: справка о задачах в работе и навыках."""

from smartesp.contracts import Utterance
from smartesp.stages import SystemSnapshot, SystemState
from smartesp.stages.system_state import SKILLS_LABEL, TASKS_LABEL, SystemFacts, describe_tasks


def _utterance() -> Utterance:
    return Utterance(device_id="A", turn=1, pcm=b"", started_at=0.0, text="что сейчас делается")


async def test_empty_system_says_nothing_in_work_and_no_skills_note() -> None:
    notes = await SystemState(SystemFacts()).analyze(_utterance())
    assert [(n.label, n.text, n.reference) for n in notes] == [(TASKS_LABEL, "ничего", True)]


async def test_running_tasks_and_skills_are_reference_notes() -> None:
    facts = SystemFacts()
    snapshot = SystemSnapshot([("Таймер «картошка»", 1300.0), ("Клод: отчёт", None)], ["Заметки", "Погода"])
    facts.use(lambda: snapshot)
    notes = await SystemState(facts, now=lambda: 1000.0).analyze(_utterance())
    assert [(n.label, n.text) for n in notes] == [
        (TASKS_LABEL, "Таймер «картошка» (ещё 5 мин), Клод: отчёт"),
        (SKILLS_LABEL, "Заметки, Погода"),
    ]
    assert all(n.reference and n.source == "system" for n in notes)


def test_overdue_and_many_tasks_are_short() -> None:
    tasks: list[tuple[str, float | None]] = [(f"т{i}", 900.0) for i in range(7)]
    soon = ", ".join(f"т{i} (вот-вот)" for i in range(5))
    assert describe_tasks(tasks, 1000.0) == f"{soon}, и ещё 2"
