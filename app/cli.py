"""CLI entry point for the video processor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.processor import (
    FFmpegNotFoundError,
    InputValidationError,
    ProcessingError,
    process_video,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=(
            "Remover duplicidade de vídeo – processador/normalizador de vídeo "
            "para conteúdo próprio. Utiliza FFmpeg como motor de processamento."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser(
        "process",
        help="Processa um vídeo (reencode, remove metadados, crop, resize).",
    )
    process_parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Caminho do arquivo de vídeo de entrada.",
    )
    process_parser.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Caminho do arquivo de saída (MP4).",
    )
    process_parser.add_argument(
        "--remove-metadata",
        action="store_true",
        default=True,
        help="Remove metadados do arquivo de saída (padrão: ativado).",
    )
    process_parser.add_argument(
        "--no-remove-metadata",
        action="store_false",
        dest="remove_metadata",
        help="Mantém os metadados originais.",
    )
    process_parser.add_argument(
        "--crop",
        type=str,
        default=None,
        help="Crop no formato w:h:x:y (ex.: 1280:720:0:0).",
    )
    process_parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Largura de saída desejada (pixels).",
    )
    process_parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Altura de saída desejada (pixels).",
    )
    process_parser.add_argument(
        "--preserve-aspect",
        action="store_true",
        default=True,
        help="Preserva a proporção ao redimensionar (padrão: ativado).",
    )
    process_parser.add_argument(
        "--no-preserve-aspect",
        action="store_false",
        dest="preserve_aspect",
        help="Não preserva a proporção (força width/height exatos).",
    )
    process_parser.add_argument(
        "--crf",
        type=int,
        default=23,
        help="CRF do libx264 (0-51, padrão: 23).",
    )
    process_parser.add_argument(
        "--preset",
        type=str,
        default="medium",
        choices=[
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        help="Preset de encoding do libx264 (padrão: medium).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "process":
        try:
            result = process_video(
                input_path=args.input,
                output_path=args.output,
                remove_metadata=args.remove_metadata,
                crop=args.crop,
                width=args.width,
                height=args.height,
                preserve_aspect=args.preserve_aspect,
                crf=args.crf,
                preset=args.preset,
            )
            print(f"✓ Processamento concluído: {result}")
            return 0
        except FFmpegNotFoundError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        except InputValidationError as exc:
            print(f"Erro de validação: {exc}", file=sys.stderr)
            return 1
        except ProcessingError as exc:
            print(f"Erro de processamento: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover
            print(f"Erro inesperado: {exc}", file=sys.stderr)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
