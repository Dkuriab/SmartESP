#!/usr/bin/env bash
# Начисто переустанавливает SmartESP на этом Mac: закрывает приложение и ядро, обновляет код
# (git pull), удаляет всё собранное (.venv, node_modules, сборки, кэш окна приложения), ставит
# заново и открывает приложение.
# Данные в ~/SmartEsp (настройки, токен, голоса, записи для обучения, заметки) НЕ трогает.
#
# Запуск из любого места:  tools/reinstall.sh            # с git pull
#                          tools/reinstall.sh --no-pull  # без обновления кода
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PULL=1
case "${1:-}" in
    "") ;;
    --no-pull) PULL=0 ;;
    *) echo "Использование: tools/reinstall.sh [--no-pull]" >&2; exit 2 ;;
esac

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nОшибка: %s\n' "$1" >&2; exit 1; }

step "Проверяю программы"
command -v uv >/dev/null || fail "нет uv — поставьте: brew install uv"
command -v npm >/dev/null || fail "нет Node.js (npm) — поставьте: brew install node"
command -v git >/dev/null || fail "нет git"

step "Закрываю приложение SmartEsp и ядро"
if pgrep -x SmartEsp >/dev/null; then
    osascript -e 'quit app "SmartEsp"' || true
    for _ in $(seq 1 30); do pgrep -x SmartEsp >/dev/null || break; sleep 1; done
fi
# ядро могло остаться запущенным из терминала: честная остановка (SIGTERM), до 20 с
if pgrep -f "python -m smartesp" >/dev/null; then
    pkill -TERM -f "python -m smartesp" || true
    for _ in $(seq 1 20); do pgrep -f "python -m smartesp" >/dev/null || break; sleep 1; done
    pgrep -f "python -m smartesp" >/dev/null && fail "ядро не остановилось — закройте его и запустите скрипт снова"
fi

if [ "$PULL" = 1 ]; then
    step "Обновляю код (git pull)"
    branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
    if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
        echo "В репозитории есть несохранённые правки — обновление пропущено (git status покажет какие)."
    elif [ "$branch" != "main" ]; then
        echo "Сейчас ветка $branch, а не main — обновление пропущено (git checkout main, затем скрипт снова)."
    else
        git -C "$ROOT" pull --ff-only
    fi
fi
echo "Версия: $(git -C "$ROOT" log --oneline -1)"

step "Удаляю собранное"
rm -rf "$ROOT/core/.venv" "$ROOT/ui/node_modules" "$ROOT/ui/dist" "$ROOT/app/build" "$ROOT/app/.build"
find "$ROOT/connectors" "$ROOT/clients" "$ROOT/trainers" -maxdepth 2 -name .venv -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$HOME/Library/Caches/com.smartesp.app"  # кэш окна приложения: иначе видна старая страница

step "Ядро (uv sync; в первый раз долго — ставится torch)"
(cd "$ROOT/core" && uv sync)

step "Коннекторы и клиенты"
for project in "$ROOT"/connectors/*/ "$ROOT"/clients/*/; do
    [ -f "$project/pyproject.toml" ] || continue
    echo "  $(basename "$project")"
    (cd "$project" && uv sync --quiet)
done

step "Интерфейс"
(cd "$ROOT/ui" && npm ci && npm run build)

step "Приложение"
(cd "$ROOT/app" && ./build.sh --install)

if command -v ollama >/dev/null; then
    models="$(ollama list 2>/dev/null || true)"
    grep -q "^gpt-oss:20b" <<<"$models" || printf '\nВнимание: нет модели gpt-oss:20b — скачайте: ollama pull gpt-oss:20b\n'
fi

step "Открываю SmartEsp"
open -a /Applications/SmartEsp.app
echo "Готово."
