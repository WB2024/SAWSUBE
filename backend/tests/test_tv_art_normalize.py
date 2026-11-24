"""Art settings and matte list replies are normalized for the API/frontend."""
from __future__ import annotations
import pytest


@pytest.mark.parametrize("key,raw,expected", [
    ("brightness", {"item": "brightness", "value": "5"}, 5),
    ("brightness", "7", 7),
    ("brightness", 3, 3),
    ("color_temp", {"value": "-2"}, -2),
    ("motion_sensitivity", {"value": "not-a-number"}, None),
    ("brightness_sensor", {"value": "on"}, True),
    ("brightness_sensor", "off", False),
    ("brightness_sensor", True, True),
    ("motion_timer", {"value": "15"}, "15"),
    ("brightness", None, None),
    ("brightness", {"value": None}, None),
])
def test_normalize_art_setting(tmp_workdir, key, raw, expected):
    from backend.services.tv_manager import normalize_art_setting
    assert normalize_art_setting(key, raw) == expected


def test_slideshow_status_is_left_untouched(tmp_workdir):
    from backend.services.tv_manager import normalize_art_setting
    raw = {"value": "3", "type": "shuffleslideshow", "category_id": "MY-C0004"}
    assert normalize_art_setting("slideshow", raw) is raw


@pytest.mark.parametrize("raw,expected", [
    (["none", "modern"], ["none", "modern"]),
    ([{"matte_type": "none"}, {"matte_type": "modern"}, {"matte_type": "none"}], ["none", "modern"]),
    ({"matte_types": [{"matte_type": "shadowbox"}]}, ["shadowbox"]),
    ({"matte_type_list": ["flexible"]}, ["flexible"]),
    ([{"color": "black"}, None, 3, ""], []),
    (None, []),
    ("oops", []),
])
def test_normalize_matte_list(tmp_workdir, raw, expected):
    from backend.services.tv_manager import normalize_matte_list
    assert normalize_matte_list(raw) == expected


async def test_get_settings_and_mattes_use_normalizers(tmp_workdir, monkeypatch):
    from types import SimpleNamespace
    from backend.services import tv_manager as tm

    class FakeArt:
        async def get_brightness(self): return {"item": "brightness", "value": "4"}
        async def get_color_temperature(self): return {"value": "1"}
        async def get_brightness_sensor_setting(self): return {"value": "off"}
        async def get_matte_list(self): return [{"matte_type": "none"}, {"matte_type": "modern"}]

    async def fake_new_art(self):
        return FakeArt()

    monkeypatch.setattr(tm.TVConnection, "_new_art", fake_new_art)
    monkeypatch.setattr(tm, "HAS_LIB", True)
    m = tm.TVManager()
    tv = SimpleNamespace(id=1, ip="192.0.2.10", port=8002, mac=None, name="t", token_path=None)
    try:
        settings = await m.get_settings(tv)
        assert settings == {"brightness": 4, "color_temp": 1, "brightness_sensor": False}
        assert await m.list_mattes(tv) == ["none", "modern"]
    finally:
        await m.shutdown()
