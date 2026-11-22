# Коннектор «Колонки» (speakers)

Скиллы ассистента про колонки дома:
- `speakers_list` — какие колонки есть, в сети ли, громкость;
- `speaker_volume(percent?, change?, speaker?)` — узнать или изменить громкость («сделай погромче» —
  `change: +10`, «громкость на кухне 30» — `speaker: Кухня, percent: 30`). Без названия — колонка,
  с которой сейчас говорят (`_meta.device` вызова от ядра), иначе единственная в сети.

Коннектор ходит в API ядра: в `smartesp.json` объявлено `"core_api": true`, и ядро передаёт ему
`SMARTESP_URL` и `SMARTESP_TOKEN`. Громкость хранится в настройках ядра (`devices.<MAC>.volume`), ядро
сразу шлёт её колонке и повторяет при каждом подключении.

```bash
uv run pytest -q && uv run ruff check && uv run pyright
```
