"""CLI entry point — processamento local (vídeo e foto). Sem Supabase obrigatório."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from vd.processor import (
    FFmpegNotFoundError,
    InputValidationError,
    ProcessingError,
    process_video,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vd.cli",
        description=(
            "Processador local de vídeo e foto. "
            "Remove metadados + microedições. Saída em disco local."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── process (vídeo) ──────────────────────────────────────────────────
    vp = subparsers.add_parser("process", help="Processa um vídeo (FFmpeg local).")
    vp.add_argument("--input", "-i", required=True, type=Path)
    vp.add_argument("--output", "-o", required=True, type=Path)
    vp.add_argument("--remove-metadata", action="store_true", default=True)
    vp.add_argument("--no-remove-metadata", action="store_false", dest="remove_metadata")
    vp.add_argument("--crop", type=str, default=None)
    vp.add_argument("--width", type=int, default=None)
    vp.add_argument("--height", type=int, default=None)
    vp.add_argument("--preserve-aspect", action="store_true", default=True)
    vp.add_argument("--no-preserve-aspect", action="store_false", dest="preserve_aspect")
    vp.add_argument("--crf", type=int, default=23)
    vp.add_argument(
        "--preset",
        type=str,
        default="medium",
        choices=[
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow",
        ],
    )
    vp.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=["off", "light", "medium", "strong", "heavy", "pesado", "multi", "contas"],
    )
    vp.add_argument("--variations", type=int, default=1)
    vp.add_argument("--hflip", action="store_true", default=False)
    vp.add_argument("--crop-percent", type=float, default=None)
    vp.add_argument("--speed", type=float, default=None)
    vp.add_argument("--mute-audio", action="store_true", default=False)
    vp.add_argument("--subtle", action="store_true", default=False)
    vp.add_argument("--trim-start", type=float, default=None, metavar="SECS")
    vp.add_argument("--trim-end", type=float, default=None, metavar="SECS")

    # ── process-image (uma foto) ─────────────────────────────────────────
    ip = subparsers.add_parser(
        "process-image",
        help="Processa uma foto localmente (limpa metadados + microedições).",
    )
    ip.add_argument("--input", "-i", required=True, type=Path, help="Foto de entrada")
    ip.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Arquivo de saída (padrão: output/<nome>_clean.jpg)",
    )
    ip.add_argument(
        "--mode",
        type=str,
        default="light",
        choices=["off", "light", "medium", "strong", "heavy"],
    )
    ip.add_argument("--crop-percent", type=float, default=None)
    ip.add_argument("--seed", type=int, default=42)

    # ── process-images (lote de fotos) ───────────────────────────────────
    bp = subparsers.add_parser(
        "process-images",
        help="Processa várias fotos em lote (pasta ou lista de arquivos).",
    )
    bp.add_argument(
        "--input", "-i", required=True, type=Path,
        help="Pasta com fotos OU um arquivo",
    )
    bp.add_argument(
        "--output-dir", "-o", type=Path, default=Path("output"),
        help="Pasta de saída (padrão: output/)",
    )
    bp.add_argument(
        "--mode",
        type=str,
        default="light",
        choices=["off", "light", "medium", "strong", "heavy"],
    )
    bp.add_argument("--crop-percent", type=float, default=None)
    bp.add_argument("--variations", type=int, default=1, help="Variações por foto (1-5)")
    bp.add_argument("--seed", type=int, default=42)

    return parser


def _cmd_process_video(args: argparse.Namespace) -> int:
    mode = getattr(args, "mode", None)
    n_var = max(1, min(int(getattr(args, "variations", 1) or 1), 10))

    if mode in ("multi", "contas") and n_var >= 1:
        from vd.processor import get_duration_seconds
        from vd.transforms import generate_multi_account_params

        dur = get_duration_seconds(args.input) or 30.0
        params = generate_multi_account_params(n_var, dur, seed=42)
        out_base = Path(args.output)
        for p in params:
            out_i = out_base.parent / f"{out_base.stem}_{p['label']}{out_base.suffix or '.mp4'}"
            process_video(
                input_path=args.input,
                output_path=out_i,
                remove_metadata=args.remove_metadata,
                crop=args.crop,
                width=args.width,
                height=args.height,
                preserve_aspect=args.preserve_aspect,
                crf=args.crf,
                preset=args.preset,
                subtle=True,
                mode="multi",
                hflip=p["hflip"],
                crop_percent=p["crop_percent"],
                speed=p["speed"],
                mute_audio=True,
                trim_start=p["trim_start"],
                trim_end=0,
                clip_duration=p.get("clip_duration"),
            )
            print(f"✓ {p['label']}: {out_i}")
        print(f"✓ Concluído → {out_base.parent}")
        return 0

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
        subtle=args.subtle,
        mode=mode,
        hflip=getattr(args, "hflip", None) or None,
        crop_percent=getattr(args, "crop_percent", None),
        speed=getattr(args, "speed", None),
        mute_audio=getattr(args, "mute_audio", False),
        trim_start=args.trim_start,
        trim_end=args.trim_end,
    )
    print(f"✓ Processamento concluído: {result}")
    return 0


def _cmd_process_image(args: argparse.Namespace) -> int:
    from vd.image_processor import process_image, ImageValidationError, ImageProcessingError

    inp = Path(args.input)
    out = args.output
    if out is None:
        out = Path("output") / f"{inp.stem}_clean.jpg"

    try:
        result = process_image(
            inp,
            out,
            mode=args.mode,
            seed=args.seed,
            crop_percent=args.crop_percent,
        )
        print(f"✓ Foto processada: {result.output_path}")
        print(f"  modo: {result.mode}")
        print(f"  mudanças: {result.changes}")
        return 0
    except (ImageValidationError, ImageProcessingError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


def _cmd_process_images(args: argparse.Namespace) -> int:
    from vd.image_processor import (
        process_image,
        is_image_file,
        generate_image_variations,
        ImageValidationError,
        ImageProcessingError,
        SUPPORTED_IMAGE_EXT,
    )

    src = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if src.is_file():
        files = [src] if is_image_file(src) else []
    elif src.is_dir():
        files = sorted(
            p for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXT
        )
    else:
        print(f"Erro: caminho não encontrado: {src}", file=sys.stderr)
        return 1

    if not files:
        print("Nenhuma imagem encontrada.", file=sys.stderr)
        return 1

    n_var = max(1, min(int(args.variations or 1), 5))
    ok = 0
    fail = 0

    print(f"Processando {len(files)} foto(s), {n_var} variação(ões) cada → {out_dir}")

    for idx, f in enumerate(files):
        params = generate_image_variations(n_var, mode=args.mode, seed=args.seed + idx * 100)
        if args.crop_percent is not None and params:
            params[0]["crop_percent"] = float(args.crop_percent)

        for p in params:
            label = p["label"]
            out = out_dir / f"{f.stem}_{label}.jpg"
            try:
                result = process_image(
                    f,
                    out,
                    mode=p.get("mode", args.mode),
                    seed=int(p.get("seed", args.seed)),
                    crop_percent=p.get("crop_percent"),
                    rotate_deg=p.get("rotate_deg"),
                )
                print(f"✓ {f.name} → {result.output_path.name}")
                ok += 1
            except (ImageValidationError, ImageProcessingError) as exc:
                print(f"✗ {f.name}: {exc}", file=sys.stderr)
                fail += 1
            except Exception as exc:
                print(f"✗ {f.name}: {exc}", file=sys.stderr)
                fail += 1

    print(f"\nConcluído: {ok} ok, {fail} erro(s). Saída em: {out_dir.resolve()}")
    return 0 if fail == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "process":
            return _cmd_process_video(args)
        if args.command == "process-image":
            return _cmd_process_image(args)
        if args.command == "process-images":
            return _cmd_process_images(args)
    except FFmpegNotFoundError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except InputValidationError as exc:
        print(f"Erro de validação: {exc}", file=sys.stderr)
        return 1
    except ProcessingError as exc:
        print(f"Erro de processamento: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Erro inesperado: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
