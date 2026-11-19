#!/usr/bin/env bash
# Тесты чистой логики прошивки на ноутбуке (без платы).
# Нужен clang++ и ArduinoJson: по умолчанию из ~/Documents/Arduino/libraries,
# иначе ARDUINOJSON_DIR=<путь к ArduinoJson/src> tools/host_tests/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
JSON_DIR="${ARDUINOJSON_DIR:-$HOME/Documents/Arduino/libraries/ArduinoJson/src}"
OUT="${TMPDIR:-/tmp}/smartesp_tests"

cd "$ROOT"
clang++ -std=c++17 -Wall -Werror -I firmware/SmartEsp/src -I "$JSON_DIR" \
  tools/host_tests/*.cpp \
  firmware/SmartEsp/src/server_link/Protocol.cpp firmware/SmartEsp/src/server_link/ReplyGate.cpp \
  firmware/SmartEsp/src/session/Session.cpp firmware/SmartEsp/src/voice_frontend/SpeechTracker.cpp \
  firmware/SmartEsp/src/wake_word/WakeFeatures.cpp firmware/SmartEsp/src/wake_word/microfrontend/*.cc \
  -o "$OUT"
"$OUT"
