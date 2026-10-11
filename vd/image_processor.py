"""Processamento de fotos: remove metadados + microedições imperceptíveis.

Separado do pipeline de vídeo. Usa Pillow.
Re-salvar como JPEG remove a maioria dos metadados (EXIF, XMP, IPTC, C2PA).
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


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


def _load_rgb(path: Path) -> Image.Image:
    try:
        img = Image.open(path)
    except Exception as exc:
        raise ImageProcessingError(f"Não foi possível abrir a imagem: {exc}") from exc
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    return img


def _save_clean_jpeg(img: Image.Image, path: Path, quality: int = 88) -> None:
    """Salva JPEG sem metadados (re-encode limpa EXIF/XMP/IPTC/C2PA)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    # Não passar exif= nem icc_profile= → metadados não são copiados
    rgb.save(
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

    # Presets por modo
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
        # fallback light
        c_pct = 1.2
        rot = 0.4
        b_f, c_f, s_f = 1.02, 1.02, 1.02
        noise = False
        quality_jitter = 3

    # Overrides do usuário
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

    # Pequena variação aleatória para não ficar idêntico entre runs
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

    # 2. Rotação leve + recorte das bordas pretas
    if abs(rot) > 0.05:
        out = out.rotate(rot, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(0, 0, 0))
        # corta 1% das bordas para esconder cantos pretos da rotação
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

    # 4. Ruído muito leve (só em medium+)
    if noise:
        # Adiciona ruído sutil via filtro + blend simples
        noisy = out.filter(ImageFilter.GaussianBlur(radius=0.4))
        # misturar 3% de versão levemente desfocada + sharpen de volta
        out = Image.blend(out, noisy, alpha=0.04)
        out = out.filter(ImageFilter.UnsharpMask(radius=0.6, percent=40, threshold=2))
        notes.append("noise+unsharp")
        changes["noise"] = True

    # Garante dimensões pares (bom para alguns pipelines)
    w, h = out.size
    if w % 2 or h % 2:
        out = out.crop((0, 0, w - (w % 2), h - (h % 2)))

    changes["quality_jitter"] = quality_jitter
    changes["metadata_removed"] = True

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
    """Processa uma foto: microedições + remove metadados ao re-salvar.

    Args:
        input_path: foto original
        output_path: destino (.jpg recomendado)
        mode: off | light | medium | strong | heavy
        seed: para variação controlada
        jpeg_quality: qualidade base do JPEG (com jitter por modo)
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    validate_image(input_path)

    img = _load_rgb(input_path)
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

    # Qualidade com pequeno jitter (muda o bitstream)
    q = max(70, min(95, jpeg_quality + changes.get("quality_jitter", 0) - 4))
    changes["jpeg_quality"] = q

    # Força extensão .jpg no output se não for imagem conhecida
    if output_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        output_path = output_path.with_suffix(".jpg")

    try:
        if output_path.suffix.lower() in {".png"}:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(output_path, format="PNG", optimize=True)
        elif output_path.suffix.lower() == ".webp":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out.save(output_path, format="WEBP", quality=q)
        else:
            _save_clean_jpeg(out, output_path, quality=q)
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
                "rotate_deg": round(rng.uniform(*base["rot"]) * rng.choice([-1, 1]), 2),
                "seed": seed + i * 17,
                "label": f"v{i + 1}",
                "index": i + 1,
            }
        )
    return out
