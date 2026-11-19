# SmartESP UI — правила части

Веб-интерфейс ядра: Vite + React + TypeScript. Ядро отдаёт `ui/dist` по `/`;
интерфейс общается с ним только через `/api/v1` и WebSocket `/api/v1/events`
(события) и `/api/v1/logs` (журнал). Других путей к ядру нет. В окне Mac-приложения
есть ещё мост `window.smartespBridge` (`src/api/bridge.ts`): открыть файлы ядра в Finder.

## Структура

```
ui/
  src/
    api/          ← клиент (openapi-fetch), WebSocket, schema.ts (генерируется)
    state/        ← редьюсер, действия, эффекты (единственное место с сетью)
    schema/       ← построение схемы (узлы и связи) из данных ядра
    components/
      <раздел>/   ← один компонент — один файл, папка на раздел интерфейса
    theme.css     ← тёмная тема, переменные цветов
    App.tsx, main.tsx
  openapi.json    ← схема API ядра (генерируется, в git)
```

## Правила

- Компоненты не ходят в сеть сами: только через действия из `src/state/`.
- Файл — не больше 300 строк; компонент и функция — не больше 50 строк.
- Зависимости — точные версии (`--save-exact`, без `^` и `~`). Обновил — залей
  `package-lock.json`.
- Все тексты интерфейса — по-русски. Имена в коде — по-английски,
  комментарии — по-русски.
- Тема только тёмная, цвета — переменные из `theme.css`.
- Контракт API — сгенерированный `src/api/schema.ts`. Руками не правим; после
  любого изменения API ядра запусти `npm run api` и закоммить `openapi.json` и
  `schema.ts`.
- TypeScript закреплён на 5.9.x: `typescript-eslint` и `openapi-typescript`
  пока не поддерживают 6.1+ и 7.

## Команды

```bash
npm ci                 # установка по lock-файлу
npm run dev            # Vite, прокси /api (с WebSocket) на 127.0.0.1:8765
npm run build          # сборка в ui/dist
npm run typecheck      # tsc
npm run lint           # ESLint, без предупреждений
npm test -- --run      # Vitest (jsdom)
npm run api            # openapi.json из ядра + src/api/schema.ts
```

Перед коммитом: `typecheck`, `lint`, `test`, `build` — без ошибок и
предупреждений.
