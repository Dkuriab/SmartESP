#!/usr/bin/env bash
# Сборка прошивки через arduino-cli с теми же настройками, что в Arduino IDE.
# Запуск из любого места: tools/build.sh
# Свой arduino-cli (например, с --config-file): ARDUINO_CLI="путь --config-file файл" tools/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN="esp32:esp32:esp32s3:PartitionScheme=esp_sr_16,FlashSize=16M,PSRAM=opi"

# Библиотеки с точными версиями (те же, что в README.md).
$CLI lib install "WebSockets@2.7.2" "ArduinoJson@7.4.3" >/dev/null

$CLI compile --fqbn "$FQBN" --warnings all "$ROOT/firmware/SmartEsp"
