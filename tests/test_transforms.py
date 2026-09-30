from app.transforms import build_transform_plan, resolve_mode


def test_resolve_mode_subtle():
    assert resolve_mode(None, subtle=True) == "light"
    assert resolve_mode("strong") == "strong"


def test_strong_has_flip_and_crop():
    plan = build_transform_plan(mode="strong")
    assert any("hflip" in x for x in plan.vf)
    assert any(x.startswith("crop=") for x in plan.vf)
    assert plan.trim_start >= 1.0
    assert any("atempo" in x or "volume" in x for x in plan.af)


def test_light_mild():
    plan = build_transform_plan(mode="light")
    assert not any("hflip" in x for x in plan.vf)
