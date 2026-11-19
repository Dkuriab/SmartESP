#!/usr/bin/env bash
# Собирает app/build/SmartEsp.app и подписывает ad-hoc.
# С флагом --install копирует приложение в /Applications (старая версия заменяется).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$APP_DIR/.." && pwd)"
BUNDLE="$APP_DIR/build/SmartEsp.app"

# Swift из Command Line Tools на этом Mac не линкует манифест пакета;
# если стоит тулчейн swift.org — берём его.
TOOLCHAIN="$HOME/Library/Developer/Toolchains/swift-6.1.2-RELEASE.xctoolchain/usr/bin"
[ -d "$TOOLCHAIN" ] && export PATH="$TOOLCHAIN:$PATH"

cd "$APP_DIR"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/SmartEsp"

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BIN" "$BUNDLE/Contents/MacOS/SmartEsp"
# Путь к репозиторию экранируем для sed.
ESCAPED="$(printf '%s' "$REPO" | sed -e 's/[&|\\]/\\&/g')"
sed "s|__REPO_PATH__|$ESCAPED|" "$APP_DIR/Resources/Info.plist.template" > "$BUNDLE/Contents/Info.plist"
[ -f "$APP_DIR/Resources/AppIcon.icns" ] && cp "$APP_DIR/Resources/AppIcon.icns" "$BUNDLE/Contents/Resources/"

codesign --force --sign - --deep "$BUNDLE"
echo "Собрано: $BUNDLE"

if [ "${1:-}" = "--install" ]; then
    rm -rf /Applications/SmartEsp.app
    cp -R "$BUNDLE" /Applications/SmartEsp.app
    echo "Установлено: /Applications/SmartEsp.app"
fi
