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
- Перед коммитом: `swift build`, `swift test`; с задачи 4 — ещё `./build.sh`.

## Команды

Из папки `app/`:

```bash
swift build
swift test
./build.sh            # app/build/SmartEsp.app, подпись ad-hoc
./build.sh --install  # плюс копия в /Applications
```

## Инструменты

- Только Command Line Tools, без Xcode. Их `swift` на этом Mac не линкует
  манифест пакета (`Invalid manifest`, `Undefined symbols ... PackageDescription`),
  поэтому используется тулчейн swift.org 6.1.2:
  `~/Library/Developer/Toolchains/swift-6.1.2-RELEASE.xctoolchain`.
  `build.sh` подставляет его сам; для `swift build`/`swift test` вручную:
  `export PATH=~/Library/Developer/Toolchains/swift-6.1.2-RELEASE.xctoolchain/usr/bin:$PATH`.
- Тесты — **swift-testing** (`import Testing`, `@Test`, `#expect`): XCTest без
  Xcode недоступен (`no such module 'XCTest'`).
