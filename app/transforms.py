"""Video transform presets for micro-edits / anti-reupload fingerprint shift.

Modes:
  off     — only optional explicit crop/trim/metadata
  light   — old subtle (1px, +1% color/volume)
  medium  — crop ~5%, mild color, trim defaults
  strong  — hflip, crop ~10%, stronger color, speed 1.02, audio pitch
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
    # applied as output option -filter:a already in af; speed via setpts/atempo
    extra_input_args: list[str]
    notes: list[str]


def resolve_mode(mode: Optional[str], *, subtle: bool = False) -> str:
    m = (mode or "").strip().lower()
    if m in ("off", "light", "medium", "strong"):
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

    crop_percent: percent of width/height to remove from each side total
      e.g. 10 → keep center 90% (5% each side).
    """
    mode = resolve_mode(mode, subtle=subtle)
    notes: list[str] = [f"mode={mode}"]
    vf: list[str] = []
    af: list[str] = []
    extra_in: list[str] = []

    # defaults per mode
    do_flip = False
    c_pct = 0.0
    contrast = 1.0
    saturation = 1.0
    brightness = 0.0
    vol = 1.0
    spd = 1.0
    t0 = float(trim_start or 0.0)
    t1 = float(trim_end or 0.0)

    if mode == "light":
        c_pct = 0.5  # ~1px-ish relative via percent floor later handled as filters
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

    if explicit_crop:
        vf.append(f"crop={explicit_crop}")
        notes.append(f"crop={explicit_crop}")
    elif c_pct > 0:
        # keep center (100 - c_pct)%
        keep = max(0.2, (100.0 - c_pct) / 100.0)
        # even dimensions
        vf.append(f"crop=trunc(iw*{keep}/2)*2:trunc(ih*{keep}/2)*2")
        notes.append(f"crop_percent={c_pct}")

    if do_flip:
        vf.append("hflip")
        notes.append("hflip")

    if abs(contrast - 1.0) > 1e-6 or abs(saturation - 1.0) > 1e-6 or abs(brightness) > 1e-6:
        vf.append(
            f"eq=contrast={contrast}:saturation={saturation}:brightness={brightness}"
        )
        notes.append(f"eq=c{contrast}/s{saturation}/b{brightness}")

    # speed: video setpts + audio atempo (atempo range 0.5-2.0)
    if abs(spd - 1.0) > 1e-4:
        vf.append(f"setpts=PTS/{spd}")
        # chain atempo if needed
        a = spd
        # atempo only 0.5-2.0
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

    # mild pitch via asetrate+aresample only in strong if no explicit speed conflict
    if mode == "strong" and abs(spd - 1.0) < 1e-4:
        af.append("asetrate=44100*1.02,aresample=44100")
        notes.append("pitch+2%")

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

    Each item: {mode, hflip, crop_percent, trim_start, trim_end, speed, label}
    """
    import random

    n = max(1, min(int(n), 20))
    rng = random.Random(seed)
    mode = resolve_mode(mode, subtle=False)

    # ranges by mode
    ranges = {
        "off": dict(crop=(0, 0), trim=(0.0, 0.0), speed=(1.0, 1.0), flip_p=0.0),
        "light": dict(crop=(0.5, 2.0), trim=(0.2, 0.5), speed=(1.0, 1.01), flip_p=0.0),
        "medium": dict(crop=(3.0, 7.0), trim=(0.5, 1.2), speed=(1.005, 1.02), flip_p=0.25),
        "strong": dict(crop=(8.0, 14.0), trim=(0.8, 1.8), speed=(1.01, 1.04), flip_p=0.85),
    }
    r = ranges.get(mode, ranges["strong"])

    out: list[dict] = []
    for i in range(n):
        # alternate flip for diversity when not forced
        if base_hflip is not None:
            flip = bool(base_hflip)
            # for variations after first, occasionally invert if n>1 and strong/medium
            if i > 0 and mode in ("medium", "strong") and base_hflip is True:
                flip = rng.random() < 0.7  # mostly keep flip
            elif i > 0 and base_hflip is False and mode == "strong":
                flip = rng.random() < 0.5
        else:
            flip = rng.random() < r["flip_p"]
            if i == 0 and mode == "strong":
                flip = True

        crop = (
            float(base_crop_percent)
            if base_crop_percent is not None and i == 0
            else round(rng.uniform(*r["crop"]), 2)
        )
        if base_crop_percent is not None and i > 0:
            # jitter ±2%
            crop = max(0.0, min(25.0, float(base_crop_percent) + rng.uniform(-2.0, 2.0)))

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
            t0 = max(0.0, float(base_trim_start) + rng.uniform(-0.3, 0.3))
        if base_trim_end is not None and i > 0:
            t1 = max(0.0, float(base_trim_end) + rng.uniform(-0.3, 0.3))

        spd = (
            float(base_speed)
            if base_speed is not None and i == 0
            else round(rng.uniform(*r["speed"]), 4)
        )
        if base_speed is not None and i > 0:
            spd = round(max(0.9, min(1.1, float(base_speed) + rng.uniform(-0.015, 0.015))), 4)

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
