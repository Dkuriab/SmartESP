#!/usr/bin/env bash
# Тесты чистой логики прошивки на ноутбуке (без платы).
# Нужен clang++ и ArduinoJson: по умолчанию из ~/Documents/Arduino/libraries,
# иначе ARDUINOJSON_DIR=<путь к ArduinoJson/src> tools/host_tests/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
JSON_DIR="${ARDUINOJSON_DIR:-$HOME/Documents/Arduino/libraries/ArduinoJson/src}"
OUT="${TMPDIR:-/tmp}/smartesp_tests"

cd "$ROOT"
clang++ -std=c++17 -Wall -Werror -I src -I "$JSON_DIR" \
  tools/host_tests/*.cpp \
  src/server_link/Protocol.cpp src/server_link/ReplyGate.cpp \
  src/session/Session.cpp src/voice_frontend/SpeechTracker.cpp \
  -o "$OUT"
"$OUT"
