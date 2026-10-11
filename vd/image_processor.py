"""Processamento de fotos: remove metadados + microedições imperceptíveis.

Separado do pipeline de vídeo. Usa Pillow.

Limpeza agressiva:
  1. Cópia pixel-only (descarta .info, EXIF, ICC do objeto PIL)
  2. Microedições
  3. Duplo re-encode JPEG sem exif/icc/xmp
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageEnhance, ImageFilter


SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}


@dataclass
class ImageProcessResult:
    output_path: Path
    mode: str
    changes: dict[str, Any]
    notes: list[str]


class ImageValidationError(ValueError):
    """Arquivo de imagem inválido."""


class ImageProcessingError(RuntimeError):
    """Falha ao processar a imagem."""


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_EXT


def validate_image(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise ImageValidationError(f"Arquivo não encontrado: {path}")
    if not is_image_file(path):
        raise ImageValidationError(
            f"Formato não suportado: {path.suffix}. "
            f"Aceitos: {', '.join(sorted(SUPPORTED_IMAGE_EXT))}"
        )


def _pixel_only_copy(img: Image.Image) -> Image.Image:
    """Cria imagem nova só com pixels — descarta .info, EXIF, ICC, XMP do objeto PIL.

    Qualquer metadado que o Pillow ainda estivesse carregando no objeto
    original não sobrevive a esta cópia.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    clean = Image.new("RGB", img.size)
    clean.paste(img)
    # Garante que o dict info está vazio
    clean.info = {}
    return clean


def _load_rgb_clean(path: Path) -> Image.Image:
    """Abre a imagem e já devolve cópia só de pixels (sem metadados no objeto)."""
    try:
        img = Image.open(path)
        # Carrega os pixels para memória antes de fechar o arquivo
        img.load()
    except Exception as exc:
        raise ImageProcessingError(f"Não foi possível abrir a imagem: {exc}") from exc

    return _pixel_only_copy(img)


def _save_clean_jpeg_aggressive(img: Image.Image, path: Path, quality: int = 88) -> None:
    """Salva JPEG com limpeza máxima de metadados.

    - Cópia pixel-only antes de salvar
    - Nunca passa exif=, icc_profile=, xmp=
    - Duplo encode: salva em buffer → reabre → salva no disco
      (segundo passe elimina qualquer resíduo que o primeiro possa ter deixado)
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # 1ª passagem: pixels puros → buffer JPEG
    pure = _pixel_only_copy(img)
    buf = io.BytesIO()
    pure.save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        # explicitamente SEM exif, SEM icc_profile, SEM xmp
    )
    buf.seek(0)

    # 2ª passagem: reabre o buffer e salva de novo no disco
    # Garante que nada de APP0/APP1/APP2/APP13 residual sobrevive
    second = Image.open(buf)
    second.load()
    final = _pixel_only_copy(second)

    final.save(
        path,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )


def _apply_micro_edits(
    img: Image.Image,
    *,
    mode: str = "light",
    seed: int = 42,
    crop_percent: Optional[float] = None,
    rotate_deg: Optional[float] = None,
    brightness: Optional[float] = None,
    contrast: Optional[float] = None,
    saturation: Optional[float] = None,
    add_noise: bool = False,
) -> tuple[Image.Image, dict[str, Any], list[str]]:
    """Aplica microedições imperceptíveis. Retorna (imagem, changes, notes)."""
    rng = random.Random(seed)
    notes: list[str] = [f"mode={mode}"]
    changes: dict[str, Any] = {"mode": mode}

    if mode == "off":
        c_pct = 0.0
        rot = 0.0
        b_f, c_f, s_f = 1.0, 1.0, 1.0
        noise = False
        quality_jitter = 0
    elif mode == "light":
        c_pct = 1.2
        rot = 0.4
        b_f, c_f, s_f = 1.02, 1.02, 1.02
        noise = False
        quality_jitter = 3
    elif mode == "medium":
        c_pct = 2.5
        rot = 0.7
        b_f, c_f, s_f = 1.04, 1.05, 1.04
        noise = True
        quality_jitter = 5
    elif mode in ("strong", "heavy"):
        c_pct = 4.0 if mode == "strong" else 6.0
        rot = 1.0 if mode == "strong" else 1.4
        b_f, c_f, s_f = 1.06, 1.08, 1.07
        noise = True
        quality_jitter = 8
    else:
        c_pct = 1.2
        rot = 0.4
        b_f, c_f, s_f = 1.02, 1.02, 1.02
        noise = False
        quality_jitter = 3

    if crop_percent is not None:
        c_pct = max(0.0, min(15.0, float(crop_percent)))
    if rotate_deg is not None:
        rot = float(rotate_deg)
    if brightness is not None:
        b_f = float(brightness)
    if contrast is not None:
        c_f = float(contrast)
    if saturation is not None:
        s_f = float(saturation)
    if add_noise:
        noise = True

    c_pct = max(0.0, c_pct + rng.uniform(-0.3, 0.3))
    rot = rot * rng.choice([-1, 1]) + rng.uniform(-0.15, 0.15)
    b_f += rng.uniform(-0.01, 0.01)
    c_f += rng.uniform(-0.01, 0.01)
    s_f += rng.uniform(-0.01, 0.01)

    out = img

    # 1. Crop central leve
    if c_pct > 0.05:
        keep = max(0.85, (100.0 - c_pct) / 100.0)
        w, h = out.size
        new_w = max(16, int(w * keep))
        new_h = max(16, int(h * keep))
        left = (w - new_w) // 2
        top = (h - new_h) // 2
        out = out.crop((left, top, left + new_w, top + new_h))
        notes.append(f"crop={c_pct:.2f}%")
        changes["crop_percent"] = round(c_pct, 2)

    # 2. Rotação leve + recorte das bordas
    if abs(rot) > 0.05:
        out = out.rotate(
            rot, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(0, 0, 0)
        )
        w, h = out.size
        m = max(1, int(min(w, h) * 0.01))
        out = out.crop((m, m, w - m, h - m))
        notes.append(f"rotate={rot:.2f}°")
        changes["rotate_deg"] = round(rot, 2)

    # 3. Ajustes de cor
    if abs(b_f - 1.0) > 0.005:
        out = ImageEnhance.Brightness(out).enhance(b_f)
        notes.append(f"brightness={b_f:.3f}")
        changes["brightness"] = round(b_f, 3)
    if abs(c_f - 1.0) > 0.005:
        out = ImageEnhance.Contrast(out).enhance(c_f)
        notes.append(f"contrast={c_f:.3f}")
        changes["contrast"] = round(c_f, 3)
    if abs(s_f - 1.0) > 0.005:
        out = ImageEnhance.Color(out).enhance(s_f)
        notes.append(f"saturation={s_f:.3f}")
        changes["saturation"] = round(s_f, 3)

    # 4. Ruído muito leve (medium+)
    if noise:
        noisy = out.filter(ImageFilter.GaussianBlur(radius=0.4))
        out = Image.blend(out, noisy, alpha=0.04)
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=40, threshold=2))
        notes.append("noise+unsharp")
        changes["noise"] = True

    # Dimensões pares
    w, h = out.size
    if w % 2 or h % 2:
        out = out.crop((0, 0, w - (w % 2), h - (h % 2)))

    # Cópia final pixel-only depois das edições
    out = _pixel_only_copy(out)

    changes["quality_jitter"] = quality_jitter
    changes["metadata_removed"] = True
    changes["strip_method"] = "pixel_only + double_jpeg_reencode"
    notes.append("strip=pixel_only+double_reencode")

    return out, changes, notes


def process_image(
    input_path: Path,
    output_path: Path,
    *,
    mode: str = "light",
    seed: int = 42,
    crop_percent: Optional[float] = None,
    rotate_deg: Optional[float] = None,
    brightness: Optional[float] = None,
    contrast: Optional[float] = None,
    saturation: Optional[float] = None,
    add_noise: bool = False,
    jpeg_quality: int = 88,
) -> ImageProcessResult:
    """Processa uma foto: microedições + limpeza agressiva de metadados.

    Fluxo:
      1. Abre e faz cópia só de pixels (joga fora EXIF/ICC/XMP do objeto)
      2. Aplica microedições
      3. Duplo re-encode JPEG sem nenhum metadado
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    validate_image(input_path)

    img = _load_rgb_clean(input_path)
    out, changes, notes = _apply_micro_edits(
        img,
        mode=mode,
        seed=seed,
        crop_percent=crop_percent,
        rotate_deg=rotate_deg,
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        add_noise=add_noise,
    )

    q = max(70, min(95, jpeg_quality + changes.get("quality_jitter", 0) - 4))
    changes["jpeg_quality"] = q

    # Sempre JPEG limpo no final (PNG/WebP opcionais só se pedido explicitamente)
    if output_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        output_path = output_path.with_suffix(".jpg")

    try:
        if output_path.suffix.lower() == ".png":
            # PNG também em cópia limpa, sem info
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pure = _pixel_only_copy(out)
            pure.save(output_path, format="PNG", optimize=True)
        elif output_path.suffix.lower() == ".webp":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pure = _pixel_only_copy(out)
            pure.save(output_path, format="WEBP", quality=q)
        else:
            _save_clean_jpeg_aggressive(out, output_path, quality=q)
    except Exception as exc:
        raise ImageProcessingError(f"Falha ao salvar imagem: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ImageProcessingError(f"Arquivo de saída não gerado: {output_path}")

    return ImageProcessResult(
        output_path=output_path,
        mode=mode,
        changes=changes,
        notes=notes,
    )


def generate_image_variations(
    n: int,
    *,
    mode: str = "light",
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Gera N conjuntos de parâmetros ligeiramente diferentes para fotos."""
    n = max(1, min(int(n), 10))
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []

    base = {
        "off": dict(crop=(0, 0), rot=(0, 0)),
        "light": dict(crop=(0.8, 1.8), rot=(0.2, 0.6)),
        "medium": dict(crop=(1.8, 3.5), rot=(0.4, 1.0)),
        "strong": dict(crop=(3.0, 5.5), rot=(0.7, 1.3)),
        "heavy": dict(crop=(4.5, 8.0), rot=(1.0, 1.8)),
    }.get(mode, dict(crop=(0.8, 1.8), rot=(0.2, 0.6)))

    for i in range(n):
        out.append(
            {
                "mode": mode,
                "crop_percent": round(rng.uniform(*base["crop"]), 2),
                "rotate_deg": round(
                    rng.uniform(*base["rot"]) * rng.choice([-1, 1]), 2
                ),
                "seed": seed + i * 17,
                "label": f"v{i + 1}",
                "index": i + 1,
            }
        )
    return out
