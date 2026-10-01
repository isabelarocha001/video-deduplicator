"""CLI entry point for the video processor."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from vd.cdn import (
    CdnConfigError,
    CdnUploadError,
    default_remote_path,
    delete_file,
    load_bunny_config,
    upload_file,
)
from vd.processor import (
    FFmpegNotFoundError,
    InputValidationError,
    ProcessingError,
    process_video,
)
from vd.rendi import (
    RendiConfigError,
    RendiError,
    is_configured as rendi_configured,
    process_via_rendi,
)
from vd.supabase_media import (
    SupabaseConfigError,
    SupabaseMediaError,
    register_media,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vd.cli",
        description=(
            "Remover duplicidade de vídeo – processador/normalizador de vídeo "
            "para conteúdo próprio. Utiliza FFmpeg como motor de processamento. "
            "Suporta upload para Bunny CDN."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── process ──────────────────────────────────────────────────────────
    process_parser = subparsers.add_parser(
        "process",
        help="Processa um vídeo (reencode, metadados, crop, resize, subtle, trim, CDN).",
    )
    process_parser.add_argument("--input", "-i", required=True, type=Path, help="Arquivo de vídeo de entrada.")
    process_parser.add_argument("--output", "-o", required=True, type=Path, help="Arquivo de saída (MP4).")
    process_parser.add_argument("--remove-metadata", action="store_true", default=True, help="Remove metadados (padrão: ativado).")
    process_parser.add_argument("--no-remove-metadata", action="store_false", dest="remove_metadata", help="Mantém metadados originais.")
    process_parser.add_argument("--crop", type=str, default=None, help="Crop w:h:x:y.")
    process_parser.add_argument("--width", type=int, default=None, help="Largura de saída.")
    process_parser.add_argument("--height", type=int, default=None, help="Altura de saída.")
    process_parser.add_argument("--preserve-aspect", action="store_true", default=True, help="Preserva proporção.")
    process_parser.add_argument("--no-preserve-aspect", action="store_false", dest="preserve_aspect", help="Não preserva proporção.")
    process_parser.add_argument("--crf", type=int, default=23, help="CRF libx264 (0-51).")
    process_parser.add_argument(
        "--preset", type=str, default="medium",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"],
        help="Preset libx264.",
    )
    process_parser.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=["off", "light", "medium", "strong", "heavy", "pesado"],
        help="Preset de microedições: off|light|medium|strong.",
    )
    process_parser.add_argument(
        "--hflip",
        action="store_true",
        default=False,
        help="Espelhar horizontalmente.",
    )
    process_parser.add_argument(
        "--crop-percent",
        type=float,
        default=None,
        help="Percentual de crop nas bordas (ex.: 10).",
    )
    process_parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Velocidade (ex.: 1.02).",
    )
    process_parser.add_argument(
        "--mute-audio",
        action="store_true",
        default=False,
        help="Remove a faixa de áudio do vídeo (-an).",
    )
    process_parser.add_argument(
        "--subtle", action="store_true", default=False,
        help="Ajustes mínimos (+1%% contraste/saturação, crop 1px, volume +1%%).",
    )
    process_parser.add_argument("--trim-start", type=float, default=None, metavar="SECS", help="Corta N segundos do início.")
    process_parser.add_argument("--trim-end", type=float, default=None, metavar="SECS", help="Corta N segundos do final.")
    process_parser.add_argument(
        "--rendi",
        action="store_true",
        default=False,
        help="Processa via Rendi.dev (FFmpeg na nuvem). Requer RENDI_API_KEY e input já em URL pública ou --upload-cdn antes.",
    )
    process_parser.add_argument(
        "--rendi-input-url",
        type=str,
        default=None,
        help="URL pública do vídeo de entrada para o Rendi (obrigatório com --rendi se não usar upload prévio).",
    )
    process_parser.add_argument(
        "--upload-cdn",
        action="store_true",
        default=False,
        help="Após processar, envia o arquivo para Bunny Storage e imprime a URL pública.",
    )
    process_parser.add_argument(
        "--cdn-prefix",
        type=str,
        default="uploads",
        help="Prefixo do path remoto no Storage (padrão: uploads).",
    )
    process_parser.add_argument(
        "--cdn-remote-path",
        type=str,
        default=None,
        help="Path remoto completo (sobrescreve --cdn-prefix/nome do arquivo).",
    )


    process_parser.add_argument(
        "--register-supabase",
        action="store_true",
        default=False,
        help="Após upload CDN, registra a mídia em vd_media (public_url) no Supabase.",
    )
    process_parser.add_argument(
        "--caption",
        type=str,
        default=None,
        help="Caption opcional ao registrar no Supabase.",
    )

    # ── upload-cdn ───────────────────────────────────────────────────────
    upload_parser = subparsers.add_parser(
        "upload-cdn",
        help="Envia um arquivo local já processado para o Bunny Storage/CDN.",
    )
    upload_parser.add_argument("--input", "-i", required=True, type=Path, help="Arquivo local.")
    upload_parser.add_argument(
        "--remote-path",
        type=str,
        default=None,
        help="Path remoto (padrão: uploads/<nome-do-arquivo>).",
    )
    upload_parser.add_argument(
        "--cdn-prefix",
        type=str,
        default="uploads",
        help="Prefixo se --remote-path não for informado.",
    )


    upload_parser.add_argument(
        "--register-supabase",
        action="store_true",
        default=False,
        help="Registra a mídia em vd_media no Supabase após o upload.",
    )
    upload_parser.add_argument(
        "--caption",
        type=str,
        default=None,
        help="Caption opcional ao registrar no Supabase.",
    )

    # ── cdn-config ───────────────────────────────────────────────────────
    subparsers.add_parser(
        "cdn-config",
        help="Valida e mostra a configuração CDN atual (sem exibir secrets).",
    )

    return parser


def _do_upload(local: Path, remote: str) -> str:
    cfg = load_bunny_config()
    public = upload_file(local, remote, config=cfg)
    bust = str(int(time.time()))
    return cfg.public_url(remote, cache_bust=bust)


def _maybe_register(local: Path, remote: str, public_url: str, *, enabled: bool, caption: str | None) -> None:
    if not enabled:
        return
    row = register_media(
        local,
        public_url=public_url.split("?")[0],
        storage_path=remote,
        status="ready",
        caption=caption,
    )
    print(f"✓ Registrado no Supabase vd_media")
    print(f"  id         : {row.get('id')}")
    print(f"  public_url : {row.get('public_url')}")
    print(f"  status     : {row.get('status')}")
    if row.get("_fingerprint_error"):
        print(f"  fingerprint: aviso — {row['_fingerprint_error']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "cdn-config":
        try:
            cfg = load_bunny_config()
            print("CDN configurado:")
            print(f"  storage_zone : {cfg.storage_zone}")
            print(f"  storage_host : {cfg.storage_host}")
            print(f"  cdn_hostname : {cfg.cdn_hostname or '(vazio)'}")
            print(f"  cdn_base_url : {cfg.cdn_base_url or '(vazio)'}")
            print(f"  api_key      : ****{cfg.storage_api_key[-4:] if len(cfg.storage_api_key) >= 4 else '****'}")
            try:
                print(f"  public_base  : {cfg.public_base}")
            except CdnConfigError as exc:
                print(f"  public_base  : (incompleto) {exc}")
            return 0
        except CdnConfigError as exc:
            print(f"Erro de configuração CDN: {exc}", file=sys.stderr)
            return 1

    if args.command == "upload-cdn":
        try:
            remote = args.remote_path or default_remote_path(args.input, prefix=args.cdn_prefix)
            url = _do_upload(args.input, remote)
            print(f"✓ Upload CDN concluído")
            print(f"  remote : {remote}")
            print(f"  url    : {url}")
            _maybe_register(
                args.input,
                remote,
                url,
                enabled=getattr(args, "register_supabase", False),
                caption=getattr(args, "caption", None),
            )
            return 0
        except (CdnConfigError, CdnUploadError, SupabaseConfigError, SupabaseMediaError) as exc:
            print(f"Erro CDN: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover
            print(f"Erro inesperado: {exc}", file=sys.stderr)
            return 1

    if args.command == "process":
        try:
            if getattr(args, "rendi", False):
                input_url = getattr(args, "rendi_input_url", None)
                rendi_in_remote = None
                # If no URL, upload original to CDN first to get public URL
                if not input_url:
                    rendi_in_remote = default_remote_path(args.input, prefix="rendi-in")
                    input_url = _do_upload(args.input, rendi_in_remote)
                    print(f"✓ Input no CDN para Rendi: {input_url}")
                rendi_res = process_via_rendi(
                    input_url.split("?")[0],
                    output_path=args.output,
                    subtle=args.subtle,
                    remove_metadata=args.remove_metadata,
                    mode=getattr(args, "mode", None),
                    hflip=True if getattr(args, "hflip", False) else None,
                    crop_percent=getattr(args, "crop_percent", None),
                    speed=getattr(args, "speed", None),
                    mute_audio=getattr(args, "mute_audio", False),
                    trim_start=args.trim_start,
                    trim_end=args.trim_end,
                    crf=args.crf,
                    preset=args.preset,
                    download=True,
                )
                result = rendi_res.local_path or args.output
                print(f"✓ Rendi OK command_id={rendi_res.command_id}")
                print(f"  output_url: {rendi_res.output_url}")
                print(f"✓ Processamento concluído: {result}")
                if rendi_in_remote:
                    try:
                        delete_file(rendi_in_remote)
                        print(f"✓ Original rendi-in removido do Bunny: {rendi_in_remote}")
                    except Exception as _del_exc:
                        print(f"Aviso: não removeu rendi-in ({_del_exc})")
            else:
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
                    mode=getattr(args, "mode", None),
                    hflip=getattr(args, "hflip", None) or None,
                    crop_percent=getattr(args, "crop_percent", None),
                    speed=getattr(args, "speed", None),
                    mute_audio=getattr(args, "mute_audio", False),
                    trim_start=args.trim_start,
                    trim_end=args.trim_end,
                )
                print(f"✓ Processamento concluído: {result}")

            if args.upload_cdn:
                remote = args.cdn_remote_path or default_remote_path(
                    Path(result), prefix=args.cdn_prefix
                )
                url = _do_upload(Path(result), remote)
                print(f"✓ Upload CDN concluído")
                print(f"  remote : {remote}")
                print(f"  url    : {url}")
                _maybe_register(
                    Path(result),
                    remote,
                    url,
                    enabled=getattr(args, "register_supabase", False),
                    caption=getattr(args, "caption", None),
                )
            elif getattr(args, "register_supabase", False):
                print(
                    "Aviso: --register-supabase requer --upload-cdn (precisa de public_url).",
                    file=sys.stderr,
                )

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
        except (CdnConfigError, CdnUploadError) as exc:
            print(f"Erro CDN: {exc}", file=sys.stderr)
            return 1
        except (SupabaseConfigError, SupabaseMediaError) as exc:
            print(f"Erro Supabase: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover
            print(f"Erro inesperado: {exc}", file=sys.stderr)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
