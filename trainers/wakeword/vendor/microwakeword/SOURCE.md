# microWakeWord (вендорено)

- Откуда: https://github.com/OHF-Voice/micro-wake-word, коммит `4665173`
  («Pin dependencies (#98)», 2026-07-06), папка `microwakeword/`. Лицензия — Apache 2.0
  (`LICENSE` рядом).
- Почему копия, а не зависимость: на PyPI пакета нет, а пакет из git ставится без подпапок
  `audio/` и `layers/` (в них нет `__init__.py`, `setuptools.find_packages` их пропускает).
- Изменений в коде нет. Его `audio_metadata` и `datasets` нужны только классу `Clips`, которым
  набор не пользуется, — вместо них заглушки (`wakeword_trainer/shims.py`).
