"""Image transformation families for adversarial testing."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass
class TransformSpec:
    """Describes a single transformation that was applied."""
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    family: str = "image"


class ImageTransforms:
    """Controlled perceptual transforms for still images."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def load(self, path: Path) -> Image.Image:
        img = Image.open(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img

    def save(self, img: Image.Image, path: Path, quality: int = 85, fmt: str = "JPEG") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt.upper() in ("JPEG", "JPG"):
            img = img.convert("RGB")
            img.save(path, format="JPEG", quality=quality, optimize=True)
        elif fmt.upper() == "WEBP":
            img.save(path, format="WEBP", quality=quality)
        elif fmt.upper() == "PNG":
            img.save(path, format="PNG")
        else:
            img.save(path, format=fmt)

    # ---- individual transforms ----

    def recompress_jpeg(self, img: Image.Image, quality: Optional[int] = None) -> tuple[Image.Image, TransformSpec]:
        q = quality if quality is not None else self.rng.randint(40, 95)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=q)
        buf.seek(0)
        out = Image.open(buf).convert("RGB")
        return out, TransformSpec("recompress_jpeg", {"quality": q}, "recompression")

    def recompress_webp(self, img: Image.Image, quality: Optional[int] = None) -> tuple[Image.Image, TransformSpec]:
        q = quality if quality is not None else self.rng.randint(40, 95)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="WEBP", quality=q)
        buf.seek(0)
        out = Image.open(buf).convert("RGB")
        return out, TransformSpec("recompress_webp", {"quality": q}, "recompression")

    def resize(self, img: Image.Image, scale: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        s = scale if scale is not None else self.rng.uniform(0.5, 1.5)
        w, h = img.size
        new_w = max(16, int(w * s))
        new_h = max(16, int(h * s))
        # keep even dimensions for video compatibility
        new_w -= new_w % 2
        new_h -= new_h % 2
        out = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return out, TransformSpec("resize", {"scale": round(s, 4), "size": (new_w, new_h)}, "resize")

    def crop(self, img: Image.Image, ratio: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        r = ratio if ratio is not None else self.rng.uniform(0.85, 0.98)
        w, h = img.size
        new_w = max(16, int(w * r))
        new_h = max(16, int(h * r))
        left = self.rng.randint(0, max(0, w - new_w))
        top = self.rng.randint(0, max(0, h - new_h))
        out = img.crop((left, top, left + new_w, top + new_h))
        return out, TransformSpec(
            "crop",
            {"ratio": round(r, 4), "box": (left, top, left + new_w, top + new_h)},
            "crop",
        )

    def pad(self, img: Image.Image, pad_ratio: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        pr = pad_ratio if pad_ratio is not None else self.rng.uniform(0.02, 0.12)
        w, h = img.size
        pad_x = max(1, int(w * pr))
        pad_y = max(1, int(h * pr))
        color = (
            self.rng.randint(0, 40),
            self.rng.randint(0, 40),
            self.rng.randint(0, 40),
        )
        out = ImageOps.expand(img, border=(pad_x, pad_y, pad_x, pad_y), fill=color)
        return out, TransformSpec("pad", {"pad_x": pad_x, "pad_y": pad_y, "color": color}, "padding")

    def letterbox(self, img: Image.Image, target_ratio: float = 16 / 9) -> tuple[Image.Image, TransformSpec]:
        w, h = img.size
        current = w / h
        if abs(current - target_ratio) < 0.01:
            return img, TransformSpec("letterbox", {"skipped": True}, "letterbox")
        if current > target_ratio:
            new_h = int(w / target_ratio)
            pad = (new_h - h) // 2
            out = ImageOps.expand(img, border=(0, pad, 0, new_h - h - pad), fill=(0, 0, 0))
        else:
            new_w = int(h * target_ratio)
            pad = (new_w - w) // 2
            out = ImageOps.expand(img, border=(pad, 0, new_w - w - pad, 0), fill=(0, 0, 0))
        return out, TransformSpec("letterbox", {"target_ratio": target_ratio, "size": out.size}, "letterbox")

    def brightness(self, img: Image.Image, factor: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        f = factor if factor is not None else self.rng.uniform(0.75, 1.25)
        out = ImageEnhance.Brightness(img).enhance(f)
        return out, TransformSpec("brightness", {"factor": round(f, 4)}, "color")

    def contrast(self, img: Image.Image, factor: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        f = factor if factor is not None else self.rng.uniform(0.75, 1.25)
        out = ImageEnhance.Contrast(img).enhance(f)
        return out, TransformSpec("contrast", {"factor": round(f, 4)}, "color")

    def saturation(self, img: Image.Image, factor: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        f = factor if factor is not None else self.rng.uniform(0.7, 1.3)
        out = ImageEnhance.Color(img).enhance(f)
        return out, TransformSpec("saturation", {"factor": round(f, 4)}, "color")

    def slight_rotate(self, img: Image.Image, angle: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        a = angle if angle is not None else self.rng.uniform(-4.0, 4.0)
        out = img.rotate(a, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(0, 0, 0))
        return out, TransformSpec("slight_rotate", {"angle": round(a, 3)}, "geometric")

    def slight_blur(self, img: Image.Image, radius: Optional[float] = None) -> tuple[Image.Image, TransformSpec]:
        r = radius if radius is not None else self.rng.uniform(0.3, 1.2)
        out = img.filter(ImageFilter.GaussianBlur(radius=r))
        return out, TransformSpec("slight_blur", {"radius": round(r, 3)}, "filter")

    def flip_horizontal(self, img: Image.Image) -> tuple[Image.Image, TransformSpec]:
        out = ImageOps.mirror(img)
        return out, TransformSpec("flip_horizontal", {}, "geometric")

    # ---- composition ----

    AVAILABLE = [
        "recompress_jpeg",
        "recompress_webp",
        "resize",
        "crop",
        "pad",
        "letterbox",
        "brightness",
        "contrast",
        "saturation",
        "slight_rotate",
        "slight_blur",
    ]

    def apply_random(
        self,
        img: Image.Image,
        max_transforms: int = 4,
        families: Optional[list[str]] = None,
    ) -> tuple[Image.Image, list[TransformSpec]]:
        """Apply a random sequence of transforms."""
        candidates = list(self.AVAILABLE)
        if families:
            # filter by family name present in TransformSpec
            pass  # keep simple for now

        n = self.rng.randint(1, max_transforms)
        chosen = self.rng.sample(candidates, min(n, len(candidates)))
        specs: list[TransformSpec] = []
        current = img
        for name in chosen:
            method = getattr(self, name)
            current, spec = method(current)
            specs.append(spec)
        return current, specs

    def apply_named(
        self,
        img: Image.Image,
        transform_names: list[str],
        params: Optional[dict[str, dict]] = None,
    ) -> tuple[Image.Image, list[TransformSpec]]:
        """Apply a deterministic list of named transforms (for replay)."""
        params = params or {}
        specs: list[TransformSpec] = []
        current = img
        for name in transform_names:
            method = getattr(self, name)
            kwargs = params.get(name, {})
            current, spec = method(current, **kwargs)
            specs.append(spec)
        return current, specs
