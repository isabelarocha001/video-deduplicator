"""Video transform presets for micro-edits / anti-reupload fingerprint shift.

Modes:
  off     — only optional explicit crop/trim/metadata
  light   — mild (crop ~0.5%, +2% color/volume)
  medium  — crop ~5%, mild color, trim defaults
  strong  — hflip, crop ~10%, stronger color, speed 1.02, audio pitch
  heavy   — edição pesada: flip, crop 18%, zoom, rotate, grade forte, noise, trim longo
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TransformPlan:
    mode: str
    vf: list[str]
    af: list[str]
    trim_start: float
    trim_end: float
    extra_input_args: list[str]
    notes: list[str]


_MODE_ALIASES = {
    "pesado": "heavy",
    "aggressive": "heavy",
    "agressivo": "heavy",
    "hard": "heavy",
    "multi": "multi",
    "contas": "multi",
    "multi-contas": "multi",
    "accounts": "multi",
}


def resolve_mode(mode: Optional[str], *, subtle: bool = False) -> str:
    m = (mode or "").strip().lower()
    m = _MODE_ALIASES.get(m, m)
    if m in ("off", "light", "medium", "strong", "heavy", "multi"):
        return m
    if subtle:
        return "light"
    return "off"


def build_transform_plan(
    *,
    mode: str = "off",
    subtle: bool = False,
    hflip: Optional[bool] = None,
    crop_percent: Optional[float] = None,
    trim_start: Optional[float] = None,
    trim_end: Optional[float] = None,
    speed: Optional[float] = None,
    explicit_crop: Optional[str] = None,
) -> TransformPlan:
    """
    Build video/audio filter lists.

    crop_percent: percent of frame removed total (center keep).
      e.g. 10 → keep center 90%.
    """
    mode = resolve_mode(mode, subtle=subtle)
    notes: list[str] = [f"mode={mode}"]
    vf: list[str] = []
    af: list[str] = []
    extra_in: list[str] = []

    do_flip = False
    do_rotate = False
    rotate_rad = 0.0
    do_zoom = False
    zoom = 1.0
    do_unsharp = False
    do_noise = False
    do_vignette = False
    c_pct = 0.0
    contrast = 1.0
    saturation = 1.0
    brightness = 0.0
    gamma = 1.0
    vol = 1.0
    spd = 1.0
    pitch = 1.0
    t0 = float(trim_start or 0.0)
    t1 = float(trim_end or 0.0)

    if mode == "light":
        c_pct = 0.5
        contrast, saturation, vol = 1.02, 1.02, 1.02
        if t0 <= 0 and trim_start is None:
            t0 = 0.3
        if t1 <= 0 and trim_end is None:
            t1 = 0.3
    elif mode == "medium":
        c_pct = 5.0
        contrast, saturation, brightness = 1.05, 1.06, 0.02
        vol = 1.03
        if t0 <= 0 and trim_start is None:
            t0 = 0.8
        if t1 <= 0 and trim_end is None:
            t1 = 0.8
        spd = 1.01
    elif mode == "strong":
        do_flip = True
        c_pct = 10.0
        contrast, saturation, brightness = 1.08, 1.10, 0.03
        vol = 1.04
        if t0 <= 0 and trim_start is None:
            t0 = 1.0
        if t1 <= 0 and trim_end is None:
            t1 = 1.0
        spd = 1.02
        pitch = 1.02
    elif mode in ("heavy", "multi"):
        # multi = same aggressive visual base as heavy; segments come from clip windows

        # Edição pesada — mudanças visíveis de propósito
        do_flip = True
        c_pct = 18.0
        do_zoom = True
        zoom = 1.12
        do_rotate = True
        rotate_rad = 0.028  # ~1.6°
        contrast, saturation, brightness = 1.14, 1.18, 0.04
        gamma = 1.05
        do_unsharp = True
        do_noise = True
        do_vignette = True
        vol = 1.06
        if t0 <= 0 and trim_start is None:
            t0 = 1.5
        if t1 <= 0 and trim_end is None:
            t1 = 1.5
        spd = 1.04
        pitch = 1.05

    # user overrides
    if hflip is not None:
        do_flip = hflip
    if crop_percent is not None:
        c_pct = max(0.0, min(40.0, float(crop_percent)))
    if speed is not None and speed > 0:
        spd = float(speed)
    if trim_start is not None:
        t0 = max(0.0, float(trim_start))
    if trim_end is not None:
        t1 = max(0.0, float(trim_end))

    # --- filter chain order matters ---
    if do_zoom and zoom > 1.001:
        # scale up then center-crop back to even dims (visual reframe)
        vf.append(f"scale=trunc(iw*{zoom}/2)*2:trunc(ih*{zoom}/2)*2")
        vf.append("crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2".format(z=zoom))
        notes.append(f"zoom={zoom}")

    if explicit_crop:
        vf.append(f"crop={explicit_crop}")
        notes.append(f"crop={explicit_crop}")
    elif c_pct > 0:
        keep = max(0.2, (100.0 - c_pct) / 100.0)
        vf.append(f"crop=trunc(iw*{keep}/2)*2:trunc(ih*{keep}/2)*2")
        notes.append(f"crop_percent={c_pct}")

    if do_rotate and abs(rotate_rad) > 1e-6:
        # rotate + autocrop black borders from rotation
        vf.append(f"rotate={rotate_rad}:c=none:ow=rotw({rotate_rad}):oh=roth({rotate_rad})")
        vf.append("crop=trunc(iw*0.92/2)*2:trunc(ih*0.92/2)*2")
        notes.append(f"rotate_rad={rotate_rad}")

    if do_flip:
        vf.append("hflip")
        notes.append("hflip")

    if (
        abs(contrast - 1.0) > 1e-6
        or abs(saturation - 1.0) > 1e-6
        or abs(brightness) > 1e-6
        or abs(gamma - 1.0) > 1e-6
    ):
        vf.append(
            f"eq=contrast={contrast}:saturation={saturation}:brightness={brightness}:gamma={gamma}"
        )
        notes.append(f"eq=c{contrast}/s{saturation}/b{brightness}/g{gamma}")

    if do_unsharp:
        vf.append("unsharp=5:5:0.8:5:5:0.4")
        notes.append("unsharp")

    if do_noise:
        # light temporal noise — changes fingerprint without destroying quality
        vf.append("noise=alls=4:allf=t+u")
        notes.append("noise")

    if do_vignette:
        vf.append("vignette=PI/5")
        notes.append("vignette")

    # ensure even dimensions for libx264
    vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    # speed: video setpts + audio atempo
    if abs(spd - 1.0) > 1e-4:
        vf.append(f"setpts=PTS/{spd}")
        a = spd
        while a > 2.0:
            af.append("atempo=2.0")
            a /= 2.0
        while a < 0.5:
            af.append("atempo=0.5")
            a /= 0.5
        af.append(f"atempo={a:.6f}")
        notes.append(f"speed={spd}")

    if abs(vol - 1.0) > 1e-6:
        af.append(f"volume={vol}")
        notes.append(f"volume={vol}")

    if abs(pitch - 1.0) > 1e-4:
        af.append(f"asetrate=44100*{pitch:.4f},aresample=44100")
        notes.append(f"pitch={pitch}")

    if t0:
        notes.append(f"trim_start={t0}")
    if t1:
        notes.append(f"trim_end={t1}")

    return TransformPlan(
        mode=mode,
        vf=vf,
        af=af,
        trim_start=t0,
        trim_end=t1,
        extra_input_args=extra_in,
        notes=notes,
    )


def generate_variation_params(
    n: int,
    *,
    mode: str = "strong",
    base_hflip: Optional[bool] = None,
    base_crop_percent: Optional[float] = None,
    base_trim_start: Optional[float] = None,
    base_trim_end: Optional[float] = None,
    base_speed: Optional[float] = None,
    seed: int = 42,
) -> list[dict]:
    """
    Build N slightly different param dicts for micro-variations of the same source.
    """
    import random

    n = max(1, min(int(n), 20))
    rng = random.Random(seed)
    mode = resolve_mode(mode, subtle=False)

    ranges = {
        "off": dict(crop=(0, 0), trim=(0.0, 0.0), speed=(1.0, 1.0), flip_p=0.0),
        "light": dict(crop=(0.5, 2.0), trim=(0.2, 0.5), speed=(1.0, 1.01), flip_p=0.0),
        "medium": dict(crop=(3.0, 7.0), trim=(0.5, 1.2), speed=(1.005, 1.02), flip_p=0.25),
        "strong": dict(crop=(8.0, 14.0), trim=(0.8, 1.8), speed=(1.01, 1.04), flip_p=0.85),
        "heavy": dict(crop=(14.0, 22.0), trim=(1.2, 2.5), speed=(1.03, 1.06), flip_p=0.95),
        "multi": dict(crop=(14.0, 22.0), trim=(1.2, 2.5), speed=(1.03, 1.06), flip_p=0.95),
    }
    r = ranges.get(mode, ranges["strong"])

    out: list[dict] = []
    for i in range(n):
        if base_hflip is not None:
            flip = bool(base_hflip)
            if i > 0 and mode in ("medium", "strong", "heavy") and base_hflip is True:
                flip = rng.random() < 0.75
            elif i > 0 and base_hflip is False and mode in ("strong", "heavy"):
                flip = rng.random() < 0.5
        else:
            flip = rng.random() < r["flip_p"]
            if i == 0 and mode in ("strong", "heavy"):
                flip = True

        crop = (
            float(base_crop_percent)
            if base_crop_percent is not None and i == 0
            else round(rng.uniform(*r["crop"]), 2)
        )
        if base_crop_percent is not None and i > 0:
            jitter = 3.0 if mode == "heavy" else 2.0
            crop = max(0.0, min(30.0, float(base_crop_percent) + rng.uniform(-jitter, jitter)))

        t0 = (
            float(base_trim_start)
            if base_trim_start is not None and i == 0
            else round(rng.uniform(*r["trim"]), 2)
        )
        t1 = (
            float(base_trim_end)
            if base_trim_end is not None and i == 0
            else round(rng.uniform(*r["trim"]), 2)
        )
        if base_trim_start is not None and i > 0:
            t0 = max(0.0, float(base_trim_start) + rng.uniform(-0.4, 0.4))
        if base_trim_end is not None and i > 0:
            t1 = max(0.0, float(base_trim_end) + rng.uniform(-0.4, 0.4))

        spd = (
            float(base_speed)
            if base_speed is not None and i == 0
            else round(rng.uniform(*r["speed"]), 4)
        )
        if base_speed is not None and i > 0:
            spd = round(max(0.9, min(1.12, float(base_speed) + rng.uniform(-0.02, 0.02))), 4)

        out.append(
            {
                "mode": mode,
                "hflip": flip,
                "crop_percent": crop,
                "trim_start": t0,
                "trim_end": t1,
                "speed": spd,
                "label": f"v{i + 1}",
                "index": i + 1,
            }
        )
    return out



def generate_multi_account_params(
    n: int,
    total_duration: float,
    *,
    seed: int = 42,
    clip_duration: Optional[float] = None,
    base_mode: str = "multi",
) -> list[dict]:
    """
    N exports for posting the same master on different accounts.

    Each variation:
      - a *different time window* of the source (not the same middle with tiny trims)
      - heavy visual jitter (crop/flip/speed)
      - label conta1, conta2, ...

    mute_audio is recommended by the caller (default on in UI/CLI for this mode).
    """
    import random

    n = max(1, min(int(n), 10))
    rng = random.Random(seed)
    total = max(0.5, float(total_duration or 1.0))

    # Default clip: ~55% of source, min 6s, max 20s (or full if shorter)
    if clip_duration is not None and clip_duration > 0:
        clip = min(float(clip_duration), total)
    else:
        clip = min(20.0, max(6.0, total * 0.55))
        clip = min(clip, total)

    max_start = max(0.0, total - clip)
    out: list[dict] = []
    for i in range(n):
        if n == 1 or max_start <= 0.05:
            start = 0.0
        else:
            # spread windows across the timeline + small jitter
            start = (i / (n - 1)) * max_start
            start = max(0.0, min(max_start, start + rng.uniform(-0.35, 0.35)))

        # visual diversity on top of different segment
        flip = True if i % 2 == 0 else rng.random() < 0.6
        crop = round(rng.uniform(14.0, 22.0), 2)
        spd = round(rng.uniform(1.03, 1.06), 4)

        out.append(
            {
                "mode": "multi",
                "hflip": flip,
                "crop_percent": crop,
                "trim_start": round(start, 3),
                "trim_end": 0.0,  # unused when clip_duration is set
                "clip_duration": round(clip, 3),
                "speed": spd,
                "mute_audio": True,
                "label": f"conta{i + 1}",
                "index": i + 1,
            }
        )
    return out
