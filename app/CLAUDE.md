# SmartESP — Mac-приложение (`app/`)

Меню-приложение: запускает и следит за Python-ядром, показывает веб-интерфейс
в окне. Общие правила проекта — в корневом `CLAUDE.md`.

## Структура

```
app/
  Package.swift
  Sources/
    SmartEspKit/     ← библиотека: вся логика (пути, uv, процесс ядра, опрос)
    SmartEsp/        ← исполняемый файл: только связка с AppKit и WebKit
  Tests/SmartEspKitTests/
  Resources/Info.plist.template
  build.sh           ← сборка и подпись app/build/SmartEsp.app
```

## Правила

- Логика — в `SmartEspKit` и с тестами. Цель `SmartEsp` тонкая: AppKit/WebKit.
- Имена по-английски, комментарии по-русски. Типы — `UpperCamelCase`,
  остальное — `lowerCamelCase`.
- Файл ≤ 300 строк, функция ≤ 50 строк.
- Минимальная macOS — 14. Язык Swift 6.
- Перед коммитом: `./swift.sh build`, `./swift.sh test`; с задачи 4 — ещё `./build.sh`.

## Команды

Из папки `app/` (`swift.sh` сам выбирает тулчейн, см. «Инструменты»):

```bash
./swift.sh build
./swift.sh test
./build.sh            # app/build/SmartEsp.app, подпись ad-hoc
./build.sh --install  # закрывает запущенное приложение, копирует в /Applications
```

## Инструменты

- Только Command Line Tools, без Xcode. Их `swift` на этом Mac не линкует
  манифест пакета (`Invalid manifest`, `Undefined symbols ... PackageDescription`),
  поэтому нужен тулчейн swift.org (https://www.swift.org/install/macos/, `.pkg`
  ставится в `~/Library/Developer/Toolchains`) или Xcode.
- `swift.sh` берёт самый свежий `~/Library/Developer/Toolchains/swift-*.xctoolchain`,
  иначе системный `swift`; при ошибке сборки печатает подсказку про тулчейн.
  `build.sh` ходит через `swift.sh`. Здесь стоит swift.org 6.1.2.
- Тесты — **swift-testing** (`import Testing`, `@Test`, `#expect`): XCTest без
  Xcode недоступен (`no such module 'XCTest'`).
