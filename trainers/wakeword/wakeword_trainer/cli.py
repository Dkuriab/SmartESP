"""Команды набора: wakeword download | synth | train | embed (см. README)."""

from __future__ import annotations

import argparse

from . import progress
from .paths import default_paths


def _download(args: argparse.Namespace) -> None:
    from .download import download_all

    download_all(default_paths().cache)


def _synth(args: argparse.Namespace) -> None:
    from .synth_runner import run_synth

    run_synth(default_paths(), args.target)


def _train(args: argparse.Namespace) -> None:
    from .train import train_target

    train_target(default_paths(), args.target, steps=args.steps, reuse_features=args.reuse_features)


def _embed(args: argparse.Namespace) -> None:
    from .embed import embed_run

    embed_run(default_paths(), args.run)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wakeword", description="Обучение слова пробуждения для колонки")
    parser.add_argument("--json", action="store_true", help="ход строками JSON (для ядра)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download", help="скачать данные для обучения (один раз, ~7 ГБ)").set_defaults(
        run=_download
    )
    synth = sub.add_parser("synth", help="синтетика фраз цели голосами ядра")
    synth.add_argument("--target", default="", help="id цели; пусто — все цели")
    synth.set_defaults(run=_synth)
    train = sub.add_parser("train", help="обучить модель цели")
    train.add_argument("--target", required=True)
    train.add_argument(
        "--steps", type=int, default=10000, help="шагов обучения (больше — дольше и обычно точнее)"
    )
    train.add_argument(
        "--reuse-features", action="store_true", help="не пересчитывать признаки прошлого раза"
    )
    train.set_defaults(run=_train)
    embed = sub.add_parser("embed", help="встроить модель прогона в прошивку")
    embed.add_argument("--run", required=True, help="папка прогона (runs/<время>-<цель>) или «last»")
    embed.set_defaults(run=_embed)
    args = parser.parse_args()
    progress.use_json(args.json)
    try:
        args.run(args)
    except (ValueError, OSError) as error:
        progress.fail(str(error))
