"""Поддельная программа `claude` для тестов запуска (настоящий Claude Code не вызывается).

Записывает аргументы, папку, задачу (stdin) и окружение в файл из `FAKE_CLAUDE_LOG`, потом
ведёт себя по режиму из файла `FAKE_CLAUDE_MODE_FILE`: ok (нет файла) — ответ JSON, error —
JSON с is_error, crash — код 3 и stderr, text — не JSON, sleep — висит (для отмены и
предела времени). Обе переменные задаёт обёртка `claude` из фикстуры: окружение
коннектора до процесса не доходит.
"""

import json
import os
import sys
import time


def main() -> int:
    prompt = sys.stdin.read()
    env = dict(os.environ)
    log = {"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": prompt, "pid": os.getpid(), "env": env}
    with open(os.environ["FAKE_CLAUDE_LOG"], "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False)
    mode_file = os.environ["FAKE_CLAUDE_MODE_FILE"]
    mode = open(mode_file, encoding="utf-8").read().strip() if os.path.exists(mode_file) else "ok"
    if mode == "sleep":
        time.sleep(60)
    if mode == "crash":
        print("первая строка\nError: Invalid API key", file=sys.stderr)
        return 3
    if mode == "text":
        print("просто текст")
        return 0
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": mode == "error",
        "result": "Не удалось войти." if mode == "error" else "Готово: поправила тест. Подробности ниже.",
        "session_id": "x",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
