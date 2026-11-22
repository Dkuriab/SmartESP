"""Связи людей с аккаунтами каналов и человек вопроса через API."""

from pathlib import Path

import pytest

from fakes.fake_voiceprint import FakeVoicePrint
from smartesp.contracts import PeopleLookupError, PersonLink, Question
from smartesp.people import People


def _people(root: Path) -> People:
    async def record(device_id: str) -> bytes | None:
        return None

    return People(root / "people", root / "m.onnx", FakeVoicePrint(), lambda p: None, record, lambda d: True)


def test_links_persist_and_account_belongs_to_one_person(tmp_path: Path) -> None:
    people = _people(tmp_path)
    anya, bob = people.add("Аня"), people.add("Боб")
    linked = people.add_link(anya.id, " telegram ", " 111 ")
    assert linked.links == (PersonLink("telegram", "111"),)
    assert people.add_link(anya.id, "telegram", "111") == linked  # повтор ничего не меняет
    people.add_link(anya.id, "matrix", "@anya:home")
    with pytest.raises(ValueError, match="уже связан с «Аня»"):
        people.add_link(bob.id, "telegram", "111")
    for channel, account in (("Telegram", "1"), ("telegram", ""), ("telegram", "a/b"), ("t", "x" * 65)):
        with pytest.raises(ValueError):
            people.add_link(bob.id, channel, account)
    again = _people(tmp_path)  # с диска
    assert again.people()[0].links == (PersonLink("telegram", "111"), PersonLink("matrix", "@anya:home"))
    again.remove_link(anya.id, "telegram", "111")
    assert again.people()[0].links == (PersonLink("matrix", "@anya:home"),)
    with pytest.raises(PeopleLookupError):
        again.remove_link(anya.id, "telegram", "111")
    with pytest.raises(PeopleLookupError):
        again.add_link("00000000", "telegram", "5")


def test_identify_linked_guest_and_plain(tmp_path: Path) -> None:
    people = _people(tmp_path)
    anya = people.add("Аня")
    people.add_link(anya.id, "telegram", "111")
    linked = people.identify(Question(text="?", person="Анечка", source="telegram", account="111"))
    assert (linked.person_id, linked.person) == (anya.id, "Аня")  # имя — из «Людей»
    guest = people.identify(Question(text="?", person="Гость", source="telegram", account="222"))
    assert (guest.person_id, guest.person) == ("telegram:222", "Гость")
    plain = Question(text="?", person="Кто-то", source="telegram")
    assert people.identify(plain) == plain  # без аккаунта — как есть
    assert people.name_of(anya.id) == "Аня" and people.name_of("telegram:222") == "Гость"
    assert people.name_of("unknown") == "unknown"
    people.rename(anya.id, "Анна")
    again = people.identify(Question(text="?", person="Анечка", source="telegram", account="111"))
    assert (again.person_id, again.person) == (anya.id, "Анна")  # id тот же — скиллам ничего не меняется
