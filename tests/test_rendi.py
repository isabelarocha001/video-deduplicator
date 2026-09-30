"""Tests for app.rendi (offline)."""

from app.rendi import build_subtle_command


def test_build_subtle_command_contains_placeholders():
    cmd = build_subtle_command(subtle=True)
    assert "{{in_1}}" in cmd
    assert "{{out_1}}" in cmd
    assert "libx264" in cmd
    assert "eq=contrast=" in cmd
    assert "-map_metadata" in cmd


def test_build_without_subtle():
    cmd = build_subtle_command(subtle=False)
    assert "eq=contrast" not in cmd
    assert "{{in_1}}" in cmd
