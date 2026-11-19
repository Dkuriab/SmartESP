# Модель «Миранда» (microWakeWord)

- Откуда: https://github.com/archer-developer/miranda-wakeword, ветка `master`,
  файлы `miranda.tflite` и `miranda.json`. Скачано 2026-11-19.
- Автор: Alexander Samusevich (поле `author` в манифесте).
- SHA-256:
  - `miranda.tflite` — `e5cf688210d43347dd9d14e55c521358ad226c2ad94e610ba5ea3ea15c295cbc`
  - `miranda.json` — `616f3cc59d092c8c10a4e64c84b0823aa01a85074810c77ab5ef587e8ba022ee`
- Файлы лежат без изменений. **Порог изменён при встраивании**: в прошивке 0,9
  (`tools/embed_model.py … --cutoff 0.9`), в манифесте автора — 0,5: на
  синтетике при 0,5 слишком много ложных срабатываний (замер —
  `docs/superpowers/specs/2026-11-19-wake-word-engine-design.md`).
- Модель временная: потом её заменит своя «Кузя» (бэклог).
