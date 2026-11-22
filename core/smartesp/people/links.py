"""Связи людей с аккаунтами каналов (Telegram и др.): проверка, поиск владельца, id гостя канала."""

import re
from collections.abc import Iterable

from smartesp.contracts import Person, PersonLink

CHANNEL = re.compile(r"^[a-z0-9_-]{1,32}$")  # как source хода через API
MAX_ACCOUNT = 64
# аккаунт идёт в id гостя "<канал>:<аккаунт>", а скиллы делают из id папку: без разделителей пути
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f/\\]")


def clean_link(channel: str, account: str) -> PersonLink:
    """Связь без лишних пробелов; канал не [a-z0-9_-]{1,32}, аккаунт пуст, длинный или с «/» — ValueError."""
    channel, account = channel.strip(), account.strip()
    if not CHANNEL.match(channel):
        raise ValueError("канал — латиница в нижнем регистре, цифры, «_» и «-», до 32 знаков")
    if not account or len(account) > MAX_ACCOUNT or _FORBIDDEN.search(account):
        raise ValueError(f"аккаунт — от 1 до {MAX_ACCOUNT} знаков, без «/», «\\» и служебных символов")
    return PersonLink(channel, account)


def owner(people: Iterable[Person], link: PersonLink) -> Person | None:
    """Человек, с которым связан аккаунт, или None."""
    return next((p for p in people if link in p.links), None)


def guest_id(link: PersonLink) -> str:
    """Постоянный id того, кто не связан ни с кем из людей: "<канал>:<аккаунт>"."""
    return f"{link.channel}:{link.account}"
