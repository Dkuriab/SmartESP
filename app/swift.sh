#!/usr/bin/env bash
# Обёртка над swift: берёт самый свежий тулчейн swift.org из
# ~/Library/Developer/Toolchains, иначе системный swift (Xcode или CLT).
# Использование: ./swift.sh build | test | ... (аргументы уходят в swift).
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

TOOLCHAIN="$(ls -d "$HOME"/Library/Developer/Toolchains/swift-*.xctoolchain 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$TOOLCHAIN" ] && [ -x "$TOOLCHAIN/usr/bin/swift" ]; then
    export PATH="$TOOLCHAIN/usr/bin:$PATH"
    exec swift "$@"
fi

swift "$@"
code=$?
if [ $code -ne 0 ]; then
    cat >&2 <<'MSG'

Сборка не удалась. Если выше ошибка «Invalid manifest» или «Undefined symbols ...
PackageDescription» — swift из Command Line Tools не умеет собирать пакеты на этой
macOS. Установите тулчейн swift.org (https://www.swift.org/install/macos/ — .pkg
ставится в ~/Library/Developer/Toolchains) или Xcode и повторите.
MSG
fi
exit $code
