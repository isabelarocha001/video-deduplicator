from vd.transforms import build_transform_plan, resolve_mode, generate_variation_params


def test_resolve_mode_subtle():
    assert resolve_mode(None, subtle=True) == "light"
    assert resolve_mode("strong") == "strong"
    assert resolve_mode("pesado") == "heavy"
    assert resolve_mode("heavy") == "heavy"


def test_strong_has_flip_and_crop():
    plan = build_transform_plan(mode="strong")
    assert any("hflip" in x for x in plan.vf)
    assert any(x.startswith("crop=") for x in plan.vf)
    assert plan.trim_start >= 1.0


def test_heavy_has_aggressive_filters():
    plan = build_transform_plan(mode="heavy")
    joined = ",".join(plan.vf)
    assert "hflip" in joined
    assert "rotate=" in joined or "noise=" in joined
    assert "eq=contrast=" in joined
    assert plan.trim_start >= 1.5
    assert any("atempo" in x or "asetrate" in x for x in plan.af)


def test_light_mild():
    plan = build_transform_plan(mode="light")
    assert not any("hflip" in x for x in plan.vf)


def test_heavy_variations():
    vs = generate_variation_params(3, mode="heavy", seed=1)
    assert len(vs) == 3
    assert all(v["mode"] == "heavy" for v in vs)
