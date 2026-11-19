# SmartESP для Mac

Меню-приложение для ядра SmartESP.

Нужно заранее:
- `uv` (`brew install uv`);
- Swift-тулчейн swift.org (https://www.swift.org/install/macos/, `.pkg` ставится
  в `~/Library/Developer/Toolchains`) или Xcode. Swift из Command Line Tools
  не умеет собирать пакеты на этой macOS (`Invalid manifest`).

Сборка и установка:

```bash
cd app && ./build.sh --install
```

Приложение появится в `/Applications/SmartEsp.app`. Подробности — в `CLAUDE.md`.
