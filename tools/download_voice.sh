#!/usr/bin/env bash
# Скачивает голос Piper в ${SMARTESP_HOME:-~/SmartEsp}/voices.
# Запуск из любого места: tools/download_voice.sh [голос]
# По умолчанию голос ru_RU-irina-medium.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VOICE=${1:-ru_RU-irina-medium}
DIR="${SMARTESP_HOME:-$HOME/SmartEsp}/voices"

mkdir -p "$DIR"
uv run --project "$ROOT/core" python -m piper.download_voices "$VOICE" --data-dir "$DIR"
