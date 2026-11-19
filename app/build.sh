#!/usr/bin/env bash
# Собирает app/build/SmartEsp.app и подписывает ad-hoc.
# С флагом --install копирует приложение в /Applications (старая версия заменяется).
# Использование: ./build.sh [--install]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$APP_DIR/.." && pwd)"
BUNDLE="$APP_DIR/build/SmartEsp.app"

INSTALL=0
case "${1:-}" in
    "") ;;
    --install) INSTALL=1 ;;
    *) echo "Использование: ./build.sh [--install]" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "Использование: ./build.sh [--install]" >&2; exit 2; }

"$APP_DIR/swift.sh" build -c release
BIN="$("$APP_DIR/swift.sh" build -c release --show-bin-path)/SmartEsp"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BIN" "$BUNDLE/Contents/MacOS/SmartEsp"
cp "$APP_DIR/Resources/Info.plist.template" "$BUNDLE/Contents/Info.plist"
plutil -replace SmartEspRepoPath -string "$REPO" "$BUNDLE/Contents/Info.plist"
if [ -f "$APP_DIR/Resources/AppIcon.icns" ]; then
    cp "$APP_DIR/Resources/AppIcon.icns" "$BUNDLE/Contents/Resources/"
fi

codesign --force --sign - --deep "$BUNDLE"
echo "Собрано: $BUNDLE"

if [ "$INSTALL" = 1 ]; then
    # Закрываем запущенное приложение, ждём до 20 с.
    if pgrep -x SmartEsp >/dev/null; then
        osascript -e 'quit app "SmartEsp"' || true
        for _ in $(seq 1 20); do pgrep -x SmartEsp >/dev/null || break; sleep 1; done
    fi
    # Копия под временным именем, старая версия убирается только после успешной копии.
    TMP="/Applications/.SmartEsp.app.new"
    rm -rf "$TMP"
    cp -R "$BUNDLE" "$TMP"
    rm -rf /Applications/SmartEsp.app
    mv "$TMP" /Applications/SmartEsp.app
    echo "Установлено: /Applications/SmartEsp.app"
fi
